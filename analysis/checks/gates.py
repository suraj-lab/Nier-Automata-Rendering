#!/usr/bin/env python3
"""Run the gates a change can affect, in parallel, and leave a receipt.

  gates.py --changed                 list gates affected by the working-tree changes
  gates.py --files a.h b.cpp         list gates affected by those files
  gates.py --all                     every gate (the full suite)
  add --run to run them; --jobs N (default 8) runs independent gates concurrently
  gates.py --list                    every gate and what it depends on

Why parallel is safe: every Wine gate has its own work directory, prefix and `xvfb-run -a` display. The two shared
things are handled here: the proxy DLL is built once before anything runs (gates then reuse it, see
test_menu_overlay.build), the gate that always rebuilds it runs alone first, and gates writing the same output
directory are chained in one lane. Receipt: analysis/runtime/gates/last.json (DLL SHA, source unchanged, per-gate).
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import time
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
REPO = C.parents[1]
OUT = A / 'runtime' / 'gates'
DLL = A / 'runtime' / 'menu-dll' / 'd3d11.dll'
DLL_SOURCES = ['menu_overlay.cpp', 'remix_live.cpp', 'd3d11_scale_setter.cpp', 'd3d11_log_proxy.def']
DLL_HEADERS = ['live_capture.h', 'live_scene.h', 'live_types.h', 'live_vertex_decode.h', 'normal_octahedral.h',
               'visibility_trace.h', 'funnel.h', 'dropout_watch.h', 'visibility_math.h', 'layout_signature.h',
               'texture_capture.h', 'nscn_scene.h', 'alpha_test.h', 'camera_capture.h', 'hud_replay.h',
               'light_convert.h', 'input_layout_hook.h', 'vtable_hook.h']
ARGS = {'test_camera_decode.py': ['camera_decode.h'], 'test_camera_decode_hidden.py': ['camera_decode.h'],
        'test_nscn_scene.py': ['nscn_scene.h'], 'test_nscn_scene_hidden.py': ['nscn_scene.h'],
        'test_remix_scale.py': ['render_settings.h']}
EXCLUSIVE = {'test_setter_proxy_integration.py'}   # rebuilds the shared DLL in place: nothing may copy it meanwhile
INFRA_RETRY = ('Xvfb failed to start',)            # a display that could not start; not a test result
SHIM = C / 'gate_shim'                             # xvfb-run wrapper: -a becomes the display assigned below
DISPLAYS = queue.Queue()                           # one X display per running gate, never shared


def free_displays(count, first=150):
    n = first
    while DISPLAYS.qsize() < count:
        if not Path(f'/tmp/.X{n}-lock').exists() and not Path(f'/tmp/.X11-unix/X{n}').exists():
            DISPLAYS.put(n)
        n += 1


def gate_sources():
    headers = {p.name for p in C.glob('*.h')}
    out = {}
    for gate in sorted(C.glob('test_*.py')):
        text = gate.read_text(errors='replace')
        deps = {name for name in headers if name in text}
        if 'tmo.build' in text or 'build_menu_dll' in text or 'd3d11.dll' in text:
            deps.update(DLL_SOURCES, DLL_HEADERS)
        out[gate.name] = deps
    return out


def lane_key(gate):
    """Gates writing the same OUT directory share a lane (run one after another)."""
    for line in (C / gate).read_text(errors='replace').splitlines():
        if line.startswith('OUT ='):
            parts = re.findall(r"['\"]([^'\"]+)['\"]", line)
            if parts:
                return '/'.join(parts)
    return gate


def changed_files():
    run = lambda *a: subprocess.run(a, cwd=REPO, capture_output=True, text=True).stdout.splitlines()
    files = run('git', 'diff', '--name-only', 'HEAD') + run('git', 'ls-files', '--others', '--exclude-standard')
    return [Path(f.strip()).name for f in files if f.strip()]


def select(changed, everything):
    gates = gate_sources()
    if everything:
        return sorted(gates), gates
    changed = set(changed)
    picked = {g for g, deps in gates.items() if deps & changed}
    picked |= {c for c in changed if c in gates}
    return sorted(picked), gates


def snapshot():
    files = list(C.glob('*.h')) + list(C.glob('*.cpp')) + list(C.glob('test_*.py'))
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def history():
    """Last known seconds per gate, to start the longest first."""
    seen = {}
    for path in (A / 'runtime' / 'present-overlay-rehook' / 'full-suite.json', OUT / 'last.json'):
        try:
            for r in json.loads(path.read_text()).get('results', []):
                seen[r.get('gate') or r.get('test')] = r['seconds']
        except (OSError, ValueError, KeyError):
            pass
    return seen


def run_gate(gate):
    log = OUT / 'logs' / (gate + '.log')
    for attempt in (1, 2):
        started = time.monotonic()
        display = DISPLAYS.get()
        env = dict(os.environ, PATH=f'{SHIM}:{os.environ.get("PATH", "")}', NIER_GATE_DISPLAY=str(display))
        try:
            p = subprocess.run(['python3', str(C / gate), *ARGS.get(gate, [])], cwd=C, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=1800, env=env)
            output, code = p.stdout, p.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = exc.stdout or b'', 124
        finally:
            DISPLAYS.put(display)
        log.write_bytes(output)
        text = output.decode(errors='replace')
        if code == 0 or attempt == 2 or not any(m in text for m in INFRA_RETRY):
            return {'gate': gate, 'ok': code == 0, 'exit': code, 'seconds': round(time.monotonic() - started, 1),
                    'attempts': attempt, 'tail': '' if code == 0 else text[-600:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--changed', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--files', nargs='*', default=[])
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()

    if a.list:
        for g, deps in gate_sources().items():
            print(f'{g:42} {len(deps):3d} deps  lane={lane_key(g)}')
        return 0
    changed = (changed_files() if a.changed else []) + a.files
    if not changed and not a.all:
        print('nothing selected; pass --files, --changed or --all', file=sys.stderr)
        return 2
    picked, gates = select(changed, a.all)
    print(f'{len(picked)} of {len(gates)} gates', flush=True)
    if not a.run:
        for g in picked:
            print(' ', g)
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'logs').mkdir(exist_ok=True)
    before = snapshot()
    wall = time.monotonic()
    results = []
    if any(gates[g] & set(DLL_SOURCES) for g in picked):
        b = subprocess.run(['python3', str(C / 'build_menu_dll.py')], capture_output=True, text=True)
        if b.returncode:
            print('DLL build failed:\n' + (b.stdout + b.stderr)[-1500:])
            return 1
        print(f'built DLL {hashlib.sha256(DLL.read_bytes()).hexdigest()[:16]} ({time.monotonic() - wall:.0f}s)',
              flush=True)

    def report(r):
        results.append(r)
        flag = 'pass' if r['ok'] else 'FAIL'
        print(f'  {r["gate"]:42} {flag} {r["seconds"]:>6.1f}s{"  (retried: Xvfb)" if r["attempts"] > 1 else ""}',
              flush=True)

    free_displays(max(1, a.jobs))
    for g in [g for g in picked if g in EXCLUSIVE]:
        report(run_gate(g))
    lanes = {}
    for g in picked:
        if g not in EXCLUSIVE:
            lanes.setdefault(lane_key(g), []).append(g)
    took = history()
    order = sorted(lanes.values(), key=lambda lane: -sum(took.get(g, 60) for g in lane))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        futures = [pool.submit(lambda lane: [run_gate(g) for g in lane], lane) for lane in order]
        for f in concurrent.futures.as_completed(futures):
            for r in f.result():
                report(r)

    after = snapshot()
    failed = [r for r in results if not r['ok']]
    receipt = {'passed': not failed and before == after, 'source_unchanged': before == after,
               'dll_sha256': hashlib.sha256(DLL.read_bytes()).hexdigest() if DLL.exists() else None,
               'jobs': a.jobs, 'gates': len(results), 'failed': [r['gate'] for r in failed],
               'wall_seconds': round(time.monotonic() - wall, 1),
               'gate_seconds': round(sum(r['seconds'] for r in results), 1),
               'results': sorted(results, key=lambda r: r['gate']), 'source_sha256': before}
    (OUT / 'last.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: receipt[k] for k in ('passed', 'source_unchanged', 'gates', 'failed', 'wall_seconds',
                                              'gate_seconds')}) + f"  dll={str(receipt['dll_sha256'])[:16]}")
    for r in failed:
        print(f'--- {r["gate"]} (log: {OUT / "logs" / (r["gate"] + ".log")})\n{r["tail"]}')
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())

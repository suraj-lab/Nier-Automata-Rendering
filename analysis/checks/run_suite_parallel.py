#!/usr/bin/env python3
"""Full gate suite in parallel lanes; same report as the serial runtime/*/full_suite_runner.py.

  run_suite_parallel.py <out-dir> [-j N]

Tests that name the same analysis/runtime/<dir> (shared output dir / Wine prefix) share a lane and run in order;
lanes run concurrently. Tests that rebuild runtime/menu-dll in place run first, alone, because every Wine gate
copies that DLL. TMPDIR points into <out-dir> (a /tmp quota filled once). Each lane gets its own X display: concurrent
`xvfb-run -a` calls pick the same free number and one kills the other's server (seen: :99), so an `xvfb-run` shim on
PATH swaps `-a` for `-n <lane display>`.
"""
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

C = pathlib.Path(__file__).resolve().parent
ARGS = {'test_camera_decode.py': ['camera_decode.h'], 'test_camera_decode_hidden.py': ['camera_decode.h'],
        'test_nscn_scene.py': ['nscn_scene.h'], 'test_nscn_scene_hidden.py': ['nscn_scene.h'],
        'test_remix_scale.py': ['render_settings.h']}
SHIM = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if '-a' in args:
    i = args.index('-a')
    args[i:i + 1] = ['-n', os.environ['NIER_XVFB_DISPLAY']]
os.execv('/usr/bin/xvfb-run', ['xvfb-run', *args])
'''
FIRST = []  # build_menu_dll.py now writes only changed files, by rename, so its callers run in lanes like the rest


def keys(test):
    s = test.read_text()
    k = set(re.findall(r"runtime['\"]?\s*/\s*['\"]?([\w.-]+)", s)) | set(re.findall(r"runtime/([\w.-]+)", s))
    return k - {'menu-dll'}  # read-only after FIRST


def lanes(tests):
    owner, out = {}, []  # key -> lane index; tests joining two lanes merge them
    for t in tests:
        hit = sorted({owner[k] for k in keys(t) if k in owner})
        if hit:
            lane = hit[0]
            for other in hit[1:]:
                out[lane] += out[other]
                out[other] = []
                owner.update({k: lane for k, v in owner.items() if v == other})
        else:
            lane = len(out)
            out.append([])
        out[lane].append(t)
        owner.update({k: lane for k in keys(t)})
    return [l for l in out if l]


def run(test, out, display=99):
    started = time.monotonic()
    try:
        p = subprocess.run(['python3', str(test), *ARGS.get(test.name, [])], cwd=C, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=1200, env={**os.environ, 'NIER_XVFB_DISPLAY': str(display)})
        output, code = p.stdout, p.returncode
    except subprocess.TimeoutExpired as exc:
        output, code = exc.stdout or b'', 124
    (out / ('suite-' + test.name + '.log')).write_bytes(output)
    print(test.name, code, round(time.monotonic() - started, 1), flush=True)
    return {'test': test.name, 'exit': code, 'seconds': round(time.monotonic() - started, 1)}


def main():
    out = pathlib.Path(sys.argv[1]).resolve()
    jobs = int(sys.argv[sys.argv.index('-j') + 1]) if '-j' in sys.argv else os.cpu_count() // 2
    out.mkdir(parents=True, exist_ok=True)
    (out / 'tmp').mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(out / 'tmp')
    (out / 'bin').mkdir(exist_ok=True)
    (out / 'bin/xvfb-run').write_text(SHIM)
    (out / 'bin/xvfb-run').chmod(0o755)
    os.environ['PATH'] = str(out / 'bin') + os.pathsep + os.environ['PATH']
    files = list(C.glob('*.h')) + list(C.glob('*.cpp')) + list(C.glob('test_*.py'))
    snapshot = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    tests = sorted(C.glob('test_*.py'))
    first = [t for t in tests if t.name in FIRST]
    started = time.monotonic()
    results = [run(t, out) for t in first]
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        for lane_results in pool.map(lambda i, lane: [run(t, out, 200 + i) for t in lane],
                                     *zip(*enumerate(lanes([t for t in tests if t.name not in FIRST])))):
            results += lane_results
    results.sort(key=lambda r: r['test'])
    unchanged = all(hashlib.sha256((C / k).read_bytes()).hexdigest() == v for k, v in snapshot.items())
    report = {'passed': all(r['exit'] == 0 for r in results) and unchanged, 'source_unchanged': unchanged,
              'total': len(results), 'wall_seconds': round(time.monotonic() - started, 1), 'jobs': jobs,
              'results': results, 'source_sha256': snapshot}
    (out / 'full-suite.json').write_text(json.dumps(report, indent=2) + '\n')
    print('passed' if report['passed'] else 'FAILED', f"{sum(r['exit'] == 0 for r in results)}/{len(results)}",
          f"wall {report['wall_seconds']} s")
    sys.exit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()

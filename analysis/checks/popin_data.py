#!/usr/bin/env python3
"""Pop-in data set: every live run's counters as tables, one plot per run.

Usage: python3 analysis/checks/popin_data.py [run.json ...]
Default: every analysis/runtime/laptop-port/live-*.json that has funnel lines.
Writes:  analysis/runtime/popin/<table>.csv (all runs, long form) and analysis/runtime/popin/<run>.png

Read-only on the runs. Lines are the DLL's own format strings (remix_live.cpp): `funnel` is one window of
stats_every frames, `live rebuilds`/`live reads` counters are cumulative (diff them for rates), `presence` and
`presence_why` are one line per notable frame. t is seconds since `remix: enabled` of the last run in the log.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'analysis/runtime/laptop-port'
OUT = ROOT / 'analysis/runtime/popin'

# tag in the log -> table name. Order matters: "presence_why" before "presence".
TAGS = [('funnel ', 'funnel'), ('presence_why ', 'why'), ('presence ', 'presence'), ('live rebuilds ', 'rebuilds'),
        ('live reads=', 'reads'), ('live draws=', 'draws'), ('coverage ', 'coverage'), ('drive ', 'drive')]
FPS = re.compile(r'([\d.]+) fps over the last (\d+) frames \(ms/frame: (.*)\)')
KV = re.compile(r'(\w+)=(-?[\d.]+)(?=[\s|]|$)')


def parse(text, run):
    """Records {run, t, table, **numbers} for the last `remix: enabled` in text."""
    rows, t0 = [], None
    for line in text.splitlines():
        m = re.match(r'(\d+):(\d+):([\d.]+) pid=\d+ remix: (.*)', line)
        if not m:
            continue
        t, body = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), m[4]
        if body.startswith('enabled '):
            rows, t0 = [], t
        if t0 is None:
            continue
        if t < t0:
            t += 86400  # run crossed midnight
        row = {'run': run, 't': round(t - t0, 3)}
        if f := FPS.match(body):
            row.update(table='fps', fps=float(f[1]), frames=int(f[2]),
                       **{k: float(v) for k, v in re.findall(r'(\w+) (-?[\d.]+)', f[3])})
            rows.append(row)
            continue
        for tag, table in TAGS:
            if body.startswith(tag):
                row['table'] = table
                row.update({k: float(v) for k, v in KV.findall(body[len(tag):])})
                if tag.endswith('='):  # first key is part of the tag ("live draws=143")
                    row[tag.split()[-1][:-1]] = float(re.match(r'[\d.]+', body[len(tag):])[0])
                rows.append(row)
                break
    return rows


def label(path):
    try:
        return json.loads(path.read_text())['label']
    except (KeyError, ValueError):
        return path.stem


def plot(df, run, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    f = df[(df.run == run) & (df.table == 'funnel')]
    r = df[(df.run == run) & (df.table == 'rebuilds')].sort_values('t')
    p = df[(df.run == run) & (df.table == 'presence')]
    w = df[(df.run == run) & (df.table == 'why')]
    fig, ax = plt.subplots(4, 1, figsize=(12, 13), sharex=True)
    if 'missing_inst' in p and p.missing_inst.notna().any():  # per-frame log (PRESENCE_MIN=0)
        ax[0].plot(p.t, p.inst * 60, lw=0.6, label='instances per frame x60')
        ax[0].plot(p.t, p.missing_inst * 60, lw=0.6, label='missing per frame x60')
        for t0, t1, ph in phase_spans(p):
            for a in ax:
                a.axvspan(t0, t1, alpha=0.08, color=f'C{ph % 10}')
            ax[0].text(t0, 1, f'phase {ph}', fontsize=7, transform=ax[0].get_xaxis_transform(), va='top')
    ax[0].plot(f.t, f.instances, '-o', label='instances submitted (window)')
    ax[0].plot(f.t, f.mesh_missing, '-o', label='instances without a built mesh')
    ax[0].set_yscale('symlog')
    a2 = ax[0].twinx()
    a2.plot(f.t, f.mesh_missing / f.instances.clip(lower=1), 'r--', label='missing share')
    a2.set_ylim(0, 1)
    a2.set_ylabel('missing share', color='r')
    ax[0].legend(loc='upper left')
    ax[0].set_title(f'{run}: renderer side (funnel, one point per window)')
    for col in ('deferred_budget', 'read_pending', 'accepted', 'decode_failed'):
        if col in f:
            ax[1].plot(f.t, f[col].fillna(0), '-o', label=f'{col} draws (window)')
    ax[1].plot(r.t, r['first'].diff(), '-s', label='new captures (Δ first)')
    ax[1].plot(r.t, r['buffer'].diff(), '-s', label='re-captures (Δ buffer)')
    ax[1].set_yscale('symlog')
    ax[1].legend(loc='upper left', fontsize=8)
    ax[1].set_title('capture side: arrivals and what the budget held back')
    if len(w):
        churn = w[[c for c in w if c.startswith('churn_')]].sum(axis=1)
        ax[2].scatter(w.t, w.absent, s=6, label='absent (game stopped drawing)')
        ax[2].scatter(w.t, churn, s=6, label='churn (re-keyed)')
        ax[2].scatter(w.t, w.arrived_missing, s=6, label='churned and arrived unbuilt')
        if 'carried' in w:
            ax[2].plot(w.t, w.carried.diff().clip(lower=0), 'k-', lw=0.8, label='stand-ins carried (Δ)')
    elif len(p):
        ax[2].scatter(p.t, p.dropped, s=6, label='dropped keys')
    ax[2].set_yscale('symlog')
    ax[2].legend(loc='upper left', fontsize=8)
    ax[2].set_title('pop events (one point per notable frame): who dropped out')
    if len(p):
        ax[3].scatter(p.t, p.cam_moved, s=6, label='camera moved (units/frame)')
        ax[3].scatter(p.t, p.cam_turned, s=6, label='camera turned (deg/frame)')
        ax[3].set_yscale('symlog')
    g = df[(df.run == run) & (df.table == 'fps')]
    if len(g):
        ax[3].plot(g.t, g.fps, 'k-', label='Remix fps')
    ax[3].legend(loc='upper left', fontsize=8)
    ax[3].set_xlabel('seconds since remix enabled')
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def phase_spans(p):
    """(start, end, phase) for each run of equal drive phase >= 0 in the per-frame log."""
    spans, q = [], p[p.phase.notna()].sort_values('t')
    for ph, g in q.groupby((q.phase != q.phase.shift()).cumsum()):
        if g.phase.iloc[0] >= 0:
            spans.append((g.t.iloc[0], g.t.iloc[-1], int(g.phase.iloc[0])))
    return spans


def main():
    import pandas as pd
    paths = [Path(a) for a in sys.argv[1:]] or sorted(RUNS.glob('live-*.json'))
    rows = []
    for path in paths:
        text = json.loads(path.read_text()).get('log', '')
        if 'remix: funnel ' in text:
            rows += parse(text, label(path))
    if not rows:
        sys.exit('no run with funnel lines')
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    for table, part in df.groupby('table'):
        part.dropna(axis=1, how='all').to_csv(OUT / f'{table}.csv', index=False)
    for run in df.run.unique():
        plot(df, run, OUT / f'{run}.png')
    print(df.groupby(['run', 'table']).size().unstack(fill_value=0).to_string())
    print(f'wrote {OUT}')


def _self_check():
    text = ('00:00:01.000 pid=1 remix: enabled runtime=x\n'
            '00:00:04.000 pid=1 remix: funnel draws=10 small=7 deferred_budget=3 | instances=5 drawn=4 '
            'mesh_missing=1 bad_transform=0 draw_failed=0 balance=ok\n'
            '00:00:04.100 pid=1 remix: presence_why seq=9 dropped=2 absent=1 key_moved=0x3 key_names=vb0_ptr\n'
            '00:00:04.200 pid=1 remix: live draws=143 instances=143 meshes=51\n'
            '00:00:04.300 pid=1 remix: 18.2 fps over the last 61 frames (ms/frame: update 1.5, other -2.0)\n')
    r = parse(text, 'x')
    assert [x['table'] for x in r] == ['funnel', 'why', 'draws', 'fps'], r
    assert r[0]['t'] == 3.0 and r[0]['deferred_budget'] == 3 and r[0]['mesh_missing'] == 1 and 'balance' not in r[0]
    assert r[1]['absent'] == 1 and r[2]['draws'] == 143 and r[3]['fps'] == 18.2 and r[3]['other'] == -2.0, r
    q = parse('00:00:01.000 pid=1 remix: enabled x\n00:00:02.000 pid=1 remix: presence seq=3 present=5 dropped=0 '
              'decode_failed=0 | queue inst=40 missing_inst=2 first=9 first_us=700 budget_us=4000 game_frames=80 '
              'phase=-1\n', 'x')[0]
    assert q['table'] == 'presence' and q['missing_inst'] == 2 and q['phase'] == -1 and q['budget_us'] == 4000, q


if __name__ == '__main__':
    _self_check()
    main()

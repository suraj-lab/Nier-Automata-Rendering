#!/usr/bin/env python3
"""List the Remix options that exist in a given runtime build, read out of the binary.

`RtxOptions.md` (written by the runtime's `writeAllMarkdownDocs` export) is the authoritative source, but
it only exists after a run, and the dump from 2026-10-26 is gone. This recovers the *names* without running
anything, which is enough to stop guessing whether a key exists -- unknown keys are never warned about at
any log level, so a conf line being echoed proves nothing.

How: the option registry in `.trex/d3d9.dll` is a stream of description strings (prose) interleaved with
option names (bare camelCase, no spaces). A token counts as an option name when it has no spaces and a
prose string sits within 400 bytes of it.

What it does NOT recover: types, defaults, min/max and the `rtx.`-prefixed category path -- those are in
`RtxOptions.md`, so this file cannot tell you a legal value, only that a name exists.

Usage:
  rtx_options.py <d3d9.dll> [--out FILE] [--grep substr] [--self-check]
"""
import re
import sys

# Known-good keys, so a silent change in extraction shows up as a failure rather than a shorter list.
SELF_CHECK = ['useDenoiser', 'useDenoiserReferenceMode', 'upscalerType', 'dlssPreset',
              'enableRayReconstruction', 'enableCullingInSecondaryRays', 'enableVirtualInstances',
              'froxelDepthSlices', 'enableBakingArrays']


def extract(path):
    data = open(path, 'rb').read()
    anchor = data.find(b'useDenoiser\0')
    if anchor < 0:
        raise SystemExit('rtx_options: registry anchor not found; wrong build or wrong file')
    lo, hi = max(0, anchor - 2_000_000), min(len(data), anchor + 4_000_000)
    seg = data[lo:hi]
    strs = [(m.start() + lo, m.group().decode('latin-1'))
            for m in re.finditer(rb'[ -~]{4,400}', seg)]

    def is_prose(s):
        return ' ' in s and '.' in s and len(s) > 25

    def is_name(s):
        return (' ' not in s and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,47}', s) is not None
                and any(c.isupper() for c in s[1:]))

    names = set()
    for idx, (off, s) in enumerate(strs):
        if not is_name(s):
            continue
        near = strs[max(0, idx - 2):idx] + strs[idx + 1:idx + 3]
        if any(is_prose(t) and abs(o - off) < 400 for o, t in near):
            names.add(s)
    return sorted(names)


def main(argv):
    if not argv:
        print(__doc__.split('Usage:')[1].strip(), file=sys.stderr)
        return 2
    path = argv[0]
    names = extract(path)
    if '--self-check' in argv:
        missing = [k for k in SELF_CHECK if k not in names]
        if missing:
            print(f'rtx_options: SELF-CHECK FAILED, missing {missing}', file=sys.stderr)
            return 1
        if not 700 <= len(names) <= 1500:
            print(f'rtx_options: SELF-CHECK FAILED, implausible count {len(names)}', file=sys.stderr)
            return 1
        print(f'rtx_options: self-check ok ({len(names)} names, all {len(SELF_CHECK)} known keys present)')
        return 0
    if '--grep' in argv:
        sub = argv[argv.index('--grep') + 1].lower()
        names = [n for n in names if sub in n.lower()]
    if '--out' in argv:
        out = argv[argv.index('--out') + 1]
        with open(out, 'w') as fh:
            fh.write(f'# Option names present in this runtime build\n'
                     f'# source: {path}\n'
                     f'# recovered by analysis/tools/rtx_options.py (binary strings; names only, no types/defaults)\n'
                     f'# {len(names)} names\n')
            fh.write('\n'.join(names) + '\n')
        print(f'{len(names)} option names -> {out}')
    else:
        print('\n'.join(names))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

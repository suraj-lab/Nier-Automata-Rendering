#!/usr/bin/env python3
"""Control experiment: cross-build NVIDIA's RemixAPI_C sample (pinned commit) with ONE change:
the runtime path comes from the REMIX_DLL environment variable instead of a bare relative "d3d9.dll"
(which Windows would resolve to the system D3D9). Nothing else in the sample is modified."""
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'runtime' / 'remix-probe' / 'sample'
COMMIT = 'bbd74a1287c2fa887f4a2b0e46a1530177890b64'
URL = f'https://raw.githubusercontent.com/NVIDIAGameWorks/dxvk-remix/{COMMIT}/tests/rtx/apps/RemixAPI_C/remixapi_example_c.c'
ORIGINAL = '  const wchar_t* path = L"d3d9.dll";\n'
PATCHED = '  const wchar_t* path = _wgetenv(L"REMIX_DLL");  /* lead change: absolute runtime path */\n'


def main():
    (OUT / 'include/remix').mkdir(parents=True, exist_ok=True)
    source = urllib.request.urlopen(URL).read().decode()
    assert source.count(ORIGINAL) == 1, 'pinned sample changed'
    patched = source.replace(ORIGINAL, PATCHED)
    header = (HERE / 'vendor/remix_c.h').read_bytes()
    (OUT / 'include/remix/remix_c.h').write_bytes(header)
    (OUT / 'remixapi_example_c.c').write_text(patched)
    exe = OUT / 'remixapi_example_c.exe'
    p = subprocess.run(['x86_64-w64-mingw32-gcc', '-std=c11', '-O2', '-I', str(OUT / 'include'),
                        str(OUT / 'remixapi_example_c.c'), '-o', str(exe), '-static', '-luser32'],
                       capture_output=True, text=True)
    (OUT / 'build.log').write_text(p.stdout + p.stderr)
    if p.returncode:
        print(p.stderr[-3000:])
        raise SystemExit(p.returncode)
    sha = lambda b: hashlib.sha256(b).hexdigest()
    receipt = {'source': URL, 'upstream_sha256': sha(source.encode()), 'patched_sha256': sha(patched.encode()),
               'only_change': 'runtime path from REMIX_DLL env var', 'exe_sha256': sha(exe.read_bytes()),
               'warnings': p.stderr.count('warning')}
    (OUT / 'validation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Frozen native/cross-build gate for a pure, byte-preserving INI preset edit."""
import argparse
import hashlib
import json
import resource
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ROOT / 'analysis/checks'
OUT = ROOT / 'analysis/runtime/settings-writer/codec-gates'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, default=CHECKS/'preset_rewrite.h')
    args = parser.parse_args()
    candidate = args.candidate.resolve(strict=True)
    assert candidate.is_file() and candidate.stat().st_size <= 50000, 'Expected one bounded C++ header'
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='gate-', dir=OUT))
    shutil.copyfile(candidate, work/'candidate.h')
    shutil.copyfile(CHECKS/'preset_rewrite_test.cpp', work/'test.cpp')
    (work/'extra.cpp').write_text('#include "candidate.h"\nvoid codec_link_probe() { std::vector<unsigned char> out; (void)render_settings_file::rewrite({}, render_settings::Mode::Native, out); }\n')
    common = ['-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-pedantic',
              '-I'+str(work),'-I'+str(CHECKS),str(work/'test.cpp'),str(work/'extra.cpp')]
    steps = []
    commands = [
        ('native-build',['g++',*common,'-fsanitize=address,undefined','-fno-omit-frame-pointer','-o',str(work/'test')]),
        ('native-test',[str(work/'test')]),
        ('windows-cross-build',['x86_64-w64-mingw32-g++',*common,'-o',str(work/'test.exe')]),
    ]
    passed = True
    for name, command in commands:
        p = subprocess.run(command,cwd=work,capture_output=True,text=True,
                           preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_CORE,(0,0)))
        (work/(name+'.log')).write_text(p.stdout+p.stderr)
        steps.append({'name':name,'exit':p.returncode})
        if p.returncode:
            passed = False
            print('\n'.join((p.stdout+p.stderr).splitlines()[-18:]))
            break
    result = {'passed':passed,'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
              'steps':steps,'artifacts':str(work),'limits':'pure transformation only, no filesystem commit or native Windows execution'}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()

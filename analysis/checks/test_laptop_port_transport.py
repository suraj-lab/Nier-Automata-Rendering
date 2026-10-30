#!/usr/bin/env python3
"""No SSH: long Unicode PowerShell scripts travel over stdin, not cmd.exe's 8191-character command line."""
import base64
import json
import re
import tempfile
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import laptop_port as lp


def main():
    script = "Write-Output '日本語 😃'\n" + '# comment\n' * 4000
    observed = {}

    def fake_run(args, **kw):
        observed.update(args=args, **kw)
        return subprocess.CompletedProcess(args, 0, '\ufeffok\r\n', '')

    with patch.object(lp.subprocess, 'run', fake_run):
        assert lp.ps(script, timeout=15) == 'ok'
    assert len(observed['args'][-1]) < 1000, 'payload expanded the SSH/cmd command line'
    assert base64.b64decode(observed['input']).decode('utf-16le') == script
    assert 'ReadToEnd' in base64.b64decode(observed['args'][-1].split()[-1]).decode('utf-16le')
    assert observed['timeout'] == 15
    receipt = dict(pids=[42], task_result=0, alive_at_end=True, log='', crash=[])
    lp.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=lp.OUT) as folder, patch.object(lp, 'OUT', Path(folder)):
        for steam in (False, True):
            scripts = []
            def fake_ps(script, **kw):
                scripts.append(script)
                return json.dumps(receipt)
            with patch.object(lp, 'ps', fake_ps):
                lp.run('live-launch-probe', True, 5, no_ec_hooks=True, steam=steam, live=True)
            script = scripts[0]
            variable = 'envfile' if steam else 'cmd'
            encoded = re.search(r"WriteAllBytes\(\$" + variable + r",\s*\[Convert\]::FromBase64String\('([^']+)'\)", script).group(1)
            decoded = base64.b64decode(encoded).decode('utf-8')
            assert 'NIER_REMIX_LIVE=1' in decoded
            assert 'NIER_REMIX_LIVE_TEX=' + lp.WORK + r'\live-textures' in decoded
            assert 'NIER_REMIX_LIVE_STATS_EVERY=60' in decoded
            assert lp.RUNTIME in decoded
    print('test_laptop_port_transport: passed (Unicode stdin and direct/Steam live launch settings)')


if __name__ == '__main__':
    main()

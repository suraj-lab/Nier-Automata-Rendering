#!/usr/bin/env python3
"""No SSH: long Unicode PowerShell scripts travel over stdin, not cmd.exe's 8191-character command line."""
import base64
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
    print('test_laptop_port_transport: passed (long Unicode script, bounded command line, exact payload)')


if __name__ == '__main__':
    main()

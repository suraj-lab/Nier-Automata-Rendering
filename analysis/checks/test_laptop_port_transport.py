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
    calls = []
    staged = {}

    def fake_run(args, **kw):
        calls.append((list(args), kw))
        if args[0] == 'scp':
            staged['bytes'] = Path(args[-2]).read_bytes()
        return subprocess.CompletedProcess(args, 0, '\ufeffok\r\n', '')

    with patch.object(lp.subprocess, 'run', fake_run):
        assert lp.ps(script, timeout=15) == 'ok'
    # The script must travel as a staged UTF-16 file, not on the command line and not through stdin: the stdin
    # bootstrap hung three times with no side effects, and a file path has no 8191-character cmd.exe limit.
    kinds = [c[0][0] for c in calls]
    assert kinds == ['scp', 'ssh', 'ssh'], kinds
    assert staged['bytes'][:2] == b'\xff\xfe', 'staged script is not a UTF-16 file with BOM'
    assert staged['bytes'][2:].decode('utf-16le') == script, 'script did not round-trip byte for byte'
    ssh_call = calls[1][0]
    assert '-File' in ssh_call[-1] and 'EncodedCommand' not in ssh_call[-1], ssh_call[-1]
    assert len(ssh_call[-1]) < 1000, 'the command line carries more than the path'
    assert calls[1][1].get('timeout') == 15
    assert 'input' not in calls[1][1], 'the script still goes through stdin'
    assert calls[2][0][-1].startswith('del '), 'the staged script is not removed'
    assert not Path(str(calls[1][0][-1]).split(' -File ')[-1].strip('"')).exists(), 'local temp file left behind'
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
            # --runtime must travel instead of the default: ARM64EC runs are a separate, named configuration.
            scripts.clear()
            with patch.object(lp, 'ps', lambda script, **kw: (scripts.append(script) or json.dumps(receipt))):
                lp.run('ec-live', True, 5, live=True, runtime=r'C:\ARM64EC\d3d9_a64ec.dll')
            encoded = re.search(r"WriteAllBytes\(\$cmd,\s*\[Convert\]::FromBase64String\('([^']+)'\)", scripts[0]).group(1)
            decoded = base64.b64decode(encoded).decode('utf-8')
            assert 'NIER_REMIX_RUNTIME=C:\\ARM64EC\\d3d9_a64ec.dll' in decoded, decoded
            assert lp.RUNTIME not in decoded
            # --capture asks the host for the composited frame; it only makes sense for a live run.
            scripts.clear()
            with patch.object(lp, 'ps', lambda script, **kw: (scripts.append(script) or json.dumps(receipt))):
                lp.run('ec-capture', True, 5, live=True, capture=True)
            encoded = re.search(r"WriteAllBytes\(\$cmd,\s*\[Convert\]::FromBase64String\('([^']+)'\)", scripts[0]).group(1)
            assert 'NIER_REMIX_CAPTURE_COMPOSITE=' + lp.WORK + r'\composite.raw' in base64.b64decode(encoded).decode('utf-8')
            scripts.clear()
            with patch.object(lp, 'ps', lambda script, **kw: (scripts.append(script) or json.dumps(receipt))):
                lp.run('options-doc', True, 5, live=True, options_doc=True)
            encoded = re.search(r"WriteAllBytes\(\$cmd,\s*\[Convert\]::FromBase64String\('([^']+)'\)", scripts[0]).group(1)
            assert 'DXVK_DOCUMENTATION_WRITE_RTX_OPTIONS_MD=1' in base64.b64decode(encoded).decode('utf-8')
            try:
                lp.run('capture-no-live', True, 5, capture=True)
            except AssertionError:
                pass
            else:
                raise AssertionError('--capture without --live was accepted')
        # --draw-probe: CPU-only hook-health diagnostic, so Remix must be off and the probe flag must travel.
        scripts = []
        def fake_ps_probe(script, **kw):
            scripts.append(script)
            return json.dumps(receipt | {'draw_probe': True})
        with patch.object(lp, 'ps', fake_ps_probe):
            lp.run('draw-probe', False, 5, no_ec_hooks=True, draw_probe=True)
        encoded = re.search(r"WriteAllBytes\(\$cmd,\s*\[Convert\]::FromBase64String\('([^']+)'\)", scripts[0]).group(1)
        decoded = base64.b64decode(encoded).decode('utf-8')
        assert 'NIER_DRAW_PROBE=1' in decoded, decoded
        assert 'NIER_REMIX=0' in decoded and 'NIER_REMIX_RUNTIME' not in decoded
        assert 'NIER_DRAW_PROBE_REHOOK' not in decoded  # re-hooking is a separate experiment, never implicit
        scripts.clear()
        with patch.object(lp, 'ps', fake_ps_probe):
            lp.run('draw-probe-rehook', False, 5, draw_probe=True, rehook=True)
        encoded = re.search(r"WriteAllBytes\(\$cmd,\s*\[Convert\]::FromBase64String\('([^']+)'\)", scripts[0]).group(1)
        decoded = base64.b64decode(encoded).decode('utf-8')
        assert 'NIER_DRAW_PROBE_REHOOK=1' in decoded, decoded
        try:
            lp.run('rehook-only', False, 5, rehook=True)
        except AssertionError:
            pass
        else:
            raise AssertionError('--rehook without --draw-probe was accepted')
        try:
            lp.run('draw-probe-mixed', True, 5, draw_probe=True)
        except AssertionError:
            pass
        else:
            raise AssertionError('--draw-probe with --remix was accepted')
    print('test_laptop_port_transport: passed (staged-file transport, direct/Steam live launch, draw-probe and runtime overrides)')


if __name__ == '__main__':
    main()

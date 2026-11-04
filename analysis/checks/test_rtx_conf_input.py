#!/usr/bin/env python3
"""Gate: every laptop rtx.conf turns off Remix's GameOverlay input sink, by an option name the runtime really has.

With rtx.useNewGuiInputMethod on (the default), remix-1.6.1 registers the keyboard for the whole process with
RIDEV_INPUTSINK | RIDEV_NOLEGACY (rtx_overlay_window.cpp:491-502), so the game window gets no WM_KEYDOWN and NieR,
which reads keys through GetKeyState, sees none (frametime2-demo, 2026-11-04). A misspelt option is ignored silently,
so the name is checked against the option list the runtime itself wrote (RtxOptions-1.6.md).
"""
import pathlib
import re

A = pathlib.Path(__file__).resolve().parents[1]
OPTION = 'rtx.useNewGuiInputMethod'

options = (A / 'runtime/remix-probe/RtxOptions-1.6.md').read_text()
assert re.search(r'^\|' + re.escape(OPTION) + r'\|bool\|True\|', options, re.M), f'{OPTION} not in the runtime option list'
confs = sorted((A / 'deploy/rtx').glob('laptop-*.conf'))
assert confs, 'no laptop confs'
for conf in confs:
    values = re.findall(r'^\s*' + re.escape(OPTION) + r'\s*=\s*(\S+)\s*$', conf.read_text(), re.M)
    assert values == ['False'], f'{conf.name}: {OPTION} must be set once to False, found {values}'
print(f'passed: {len(confs)} confs set {OPTION} = False')

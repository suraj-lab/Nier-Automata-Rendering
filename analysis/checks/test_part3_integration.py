#!/usr/bin/env python3
"""Frozen gate for Part 3 (slot-0 redirect to the FSR Output + copy-back skip).

Candidate files: analysis/checks/redirect_logic.h (new) and analysis/checks/d3d11_scale_setter.cpp.
Prints one JSON object; "passed": true only if every check passes. Builds in temp dirs only.
    python3 analysis/checks/test_part3_integration.py
"""
import hashlib, json, pathlib, re, subprocess, sys, tempfile

C = pathlib.Path(__file__).resolve().parent
FROZEN = {
    "proxy_patch.h": "60eae2113d50060ce8765a7dd7ea25f6f7e28635200c198a4be4a69fcd0268a6",
    "proxy_patch_test.cpp": "236d4f2b3e243edea2f34f09c693e30ec50870e777b1a0e2a327f3f6128f0d60",
    "redirect_logic_test.cpp": "bb5336c702dc4ceede96d8e80d6eb0f6998b4869bebd93feffc36f1cdbcacb53",
    "test_setter_proxy_integration.py": "2f1040e9026c8b0bfa104715380e89f6121bfb8f06677b5d0f566b10d45972d3",
    "depth_patch.h": "5fa527b05c4ff9e278f613aa929fd935219e1b504c44581ec11a78b8c1c98517",
    "scale_patch.h": "f02217c1d5f0bbb1a1bde090b9e8e803c1aeb7390bc4a897dda5354d37f3e7eb",
    "d3d11_log_proxy.def": "4a8c1556b94182924fb9d05039871e9d2f1d599a3558b7369418d53ff4c67945",
}
results = []

def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), **({"detail": str(detail)[-1500:]} if detail and not ok else {})})

def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr

for name, want in FROZEN.items():
    got = hashlib.sha256((C / name).read_bytes()).hexdigest()
    check(f"frozen {name}", got == want, f"sha256 {got} != {want}")

# 1. redirect_logic.h: pure header, frozen test passes
hdr = C / "redirect_logic.h"
check("redirect_logic.h exists", hdr.exists())
if hdr.exists():
    h = re.sub(r"//[^\n]*", "", hdr.read_text())
    check("redirect_logic.h is pure (no windows/d3d includes)", not re.search(r"#include\s*[<\"](windows|d3d|dxgi)", h, re.I))
    with tempfile.TemporaryDirectory() as td:
        exe = pathlib.Path(td) / "redirect_logic_test"
        rc, out = run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", str(C / "redirect_logic_test.cpp"), "-o", str(exe)])
        check("redirect_logic_test builds", rc == 0, out)
        if rc == 0:
            rc, out = run([str(exe)])
            check("redirect_logic_test passes", rc == 0 and "all passed" in out, out)

# 2. previous gate (setter builds with -Werror, exports, kSites loop, scale-slot contract, proxy_patch_test)
rc, out = run([sys.executable, str(C / "test_setter_proxy_integration.py")])
try:
    prev = json.loads(out[out.index("{"):])
except ValueError:
    prev = {"passed": False, "failed": out}
check("previous setter gate passes", prev.get("passed") is True, json.dumps(prev.get("failed")))

# 3. setter contract for on_dispatch_exit
src = re.sub(r"//[^\n]*", "", (C / "d3d11_scale_setter.cpp").read_text())
check('includes "redirect_logic.h"', re.search(r'#include\s+"redirect_logic\.h"', src))
m = re.search(r"static\s+void\s+on_dispatch_exit\s*\(\s*ID3D11DeviceContext\s*\*\s*\w+\s*\)\s*\{", src)
check("static void on_dispatch_exit(ID3D11DeviceContext*) defined", m)
body = ""
if m:
    depth, i = 1, m.end()
    while i < len(src) and depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    body = src[m.end():i]
    for g in ("kImmediateCtxRva", "kCurFrameRva", "kDispatchFrameRva", "kOutputTexRva"):
        check(f"on_dispatch_exit reads proxy_patch::{g}", f"proxy_patch::{g}" in body)
    check("calls redirect_logic::should_redirect", "redirect_logic::should_redirect(" in body)
    for call in ("PSGetShaderResources(0, 1,", "PSSetShaderResources(0, 1,", "CreateShaderResourceView(", "GetDevice(", "GetResource("):
        check(f"uses {call}", call in body.replace("0,1,", "0, 1,"))
    get = body.find("PSGetShaderResources")
    check("cheap early-outs (immediate ctx + frame compare) before any COM call",
          get != -1 and -1 < body.find("kImmediateCtxRva") < get and -1 < body.find("kDispatchFrameRva") < get
          and -1 < body.find("kOutputTexRva") < get)
    check("releases what it gets (>= 3 Release calls)", body.count("->Release()") >= 3, body.count("->Release()"))
    check("logs the redirect", re.search(r'logf_line\([^;]*redirect', body))
check("emit_cave receives on_dispatch_exit", re.search(r"emit_cave\([^;]*on_dispatch_exit[^;]*\)", src))
check("no new hard-coded proxy RVAs in the setter",
      not re.search(r"0x(abc08|6a288|abfc8|abf70)\b", src, re.I))

passed = all(r["ok"] for r in results)
print(json.dumps({"passed": passed, "failed": [r for r in results if not r["ok"]], "total": len(results)}, indent=1))
sys.exit(0 if passed else 1)

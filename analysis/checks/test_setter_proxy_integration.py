#!/usr/bin/env python3
"""Frozen gate: d3d11_scale_setter.cpp integrates the 4-site proxy_patch (incl. the gate cave).

Prints one JSON object; "passed": true only if every check passes. Builds into a temp dir
(never touches build/scale-setter/d3d11.dll). Run from anywhere:
    python3 analysis/checks/test_setter_proxy_integration.py
"""
import hashlib, json, pathlib, re, subprocess, sys, tempfile

C = pathlib.Path(__file__).resolve().parent
SRC = C / "d3d11_scale_setter.cpp"
FROZEN = {  # files the candidate must not modify
    "proxy_patch.h": "60eae2113d50060ce8765a7dd7ea25f6f7e28635200c198a4be4a69fcd0268a6",
    "proxy_patch_test.cpp": "236d4f2b3e243edea2f34f09c693e30ec50870e777b1a0e2a327f3f6128f0d60",
    "depth_patch.h": "5fa527b05c4ff9e278f613aa929fd935219e1b504c44581ec11a78b8c1c98517",
    "scale_patch.h": "f02217c1d5f0bbb1a1bde090b9e8e803c1aeb7390bc4a897dda5354d37f3e7eb",
    "d3d11_log_proxy.def": "4a8c1556b94182924fb9d05039871e9d2f1d599a3558b7369418d53ff4c67945",
}
results = []

def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), **({"detail": detail[-1500:]} if detail and not ok else {})})

def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr

# 1. frozen files untouched
for name, want in FROZEN.items():
    got = hashlib.sha256((C / name).read_bytes()).hexdigest()
    check(f"frozen {name}", got == want, f"sha256 {got} != {want}")

src = SRC.read_text()
code = re.sub(r"//[^\n]*", "", src)  # ignore comments for contract checks

# 2. native cave test still passes (header is frozen, so this guards the build env)
with tempfile.TemporaryDirectory() as td:
    exe = pathlib.Path(td) / "proxy_patch_test"
    rc, out = run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                   "-fno-sanitize-recover=all", str(C / "proxy_patch_test.cpp"), "-o", str(exe)])
    check("proxy_patch_test builds", rc == 0, out)
    if rc == 0:
        rc, out = run([str(exe)])
        check("proxy_patch_test passes", rc == 0 and "all passed" in out, out)

    # 3. setter DLL builds with -Werror (same flags as SCALE_SETTER.md)
    dll = pathlib.Path(td) / "d3d11.dll"
    rc, out = run(["x86_64-w64-mingw32-g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-shared",
                   "-static", "-static-libgcc", "-static-libstdc++", "-o", str(dll), str(SRC),
                   str(C / "d3d11_log_proxy.def")], cwd=C)
    check("setter dll builds (-Werror)", rc == 0, out)
    if rc == 0:
        rc, out = run(["x86_64-w64-mingw32-objdump", "-p", str(dll)])
        fwd = set(re.findall(r"d3d11_dlaa\.(\w+)", out))
        check("49 forwarders to d3d11_dlaa", len(fwd) == 49, f"{len(fwd)} forwarders")
        imports = set(re.findall(r"DLL Name: (\S+)", out))
        check("no d3d11/dxgi imports", not any(i.lower().startswith(("d3d11", "dxgi")) for i in imports), str(imports))

# 4. source contract
check("patch loop iterates proxy_patch::kSites", re.search(r"for\s*\(\s*const\s+auto\s*&\s*\w+\s*:\s*proxy_patch::kSites\s*\)", code))
check("no hard-coded cave offsets / local Patch table",
      not re.search(r"struct\s+Patch\b", code) and not re.search(r",\s*(19|38)\s*}", code))
check("alloc_cave_near takes a size",
      re.search(r"alloc_cave_near\s*\(\s*const\s+void\s*\*\s*\w+\s*,\s*std::size_t\s+\w+\s*\)", code))
check("depth cave allocated with depth_patch::kCaveSize",
      re.search(r"alloc_cave_near\s*\([^;]*depth_patch::kCaveSize\s*\)", code))
check("proxy cave allocated with proxy_patch::kCaveSize",
      re.search(r"alloc_cave_near\s*\([^;]*proxy_patch::kCaveSize\s*\)", code))
check("no other VirtualAlloc size", "VirtualAlloc(" in code and not re.search(r"VirtualAlloc\([^;]*depth_patch::kCaveSize", code))
check("emit_cave result compared to kCaveSize", re.search(r"!=\s*proxy_patch::kCaveSize", code))
check("proxy cave pointer kept in static proxy_cave", re.search(r"static\s+std::uint8_t\s*\*\s*proxy_cave\s*=\s*nullptr\s*;", code))

uses = [m.start() for m in re.finditer(r"proxy_patch::kScaleOff", code)]
check("kScaleOff written exactly once", len(uses) == 1, f"{len(uses)} uses")
if len(uses) == 1:
    i = uses[0]
    before = code[:i]
    loop = before.rfind("scale_patch::try_apply")
    guard = before.rfind("if")
    guard_text = code[guard:i]
    check("scale slot written after the scale apply loop", loop != -1 and loop < i)
    check("write guarded by scale Applied AND proxy Applied",
          "scale_patch::Result::Applied" in guard_text and "proxy_patch::Result::Applied" in guard_text
          and "proxy_cave" in guard_text, guard_text[-300:])
    stmt = code[i - 200:i + 120]
    check("writes kScale into the slot", "kScale" in stmt.replace("kScaleOff", ""), stmt)
check("logs the gate scale", re.search(r'logf_line\([^;]*gate scale', code))

passed = all(r["ok"] for r in results)
print(json.dumps({"passed": passed, "failed": [r for r in results if not r["ok"]],
                  "total": len(results)}, indent=1))
sys.exit(0 if passed else 1)

#!/usr/bin/env python3
"""Check the scale-setter DLL exports the same names/ordinals as original NIER_DLAA,
with 49 forwarders to d3d11_dlaa and the two create functions implemented locally."""
import argparse, re, subprocess, sys, pathlib

A = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("dll", nargs="?", type=pathlib.Path, default=A / "build/scale-setter/d3d11.dll")
ORIG, NEW = A / "input/NIER_DLAA_1.1.dll", parser.parse_args().dll
WRAPPED = {"D3D11CreateDevice", "D3D11CreateDeviceAndSwapChain"}

def exports(dll):
    out = subprocess.run(["x86_64-w64-mingw32-objdump", "-p", str(dll)], check=True, capture_output=True, text=True).stdout
    table = out.split("[Ordinal/Name Pointer] Table", 1)[1].split("\n\n", 1)[0]
    # rows look like: "[  15] +base[  16]  0000 CreateDirect3D11DeviceFromDXGIDevice"
    names = {m.group(2): int(m.group(1)) for m in re.finditer(r"\+base\[\s*(\d+)\]\s+[0-9a-f]{4} (\S+)", table)}
    return names, out

orig, _ = exports(ORIG)
new, raw = exports(NEW)
forwarders = set(re.findall(r"d3d11_dlaa\.(\w+)", raw))
ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name); ok &= bool(cond)

check(f"51 exports (orig {len(orig)}, new {len(new)})", len(orig) == len(new) == 51)
check("same names and ordinals as original", orig == new)
check("49 forwarders to d3d11_dlaa", forwarders == set(new) - WRAPPED and len(forwarders) == 49)
check("create functions are local, not forwarded", not (WRAPPED & forwarders))
imports = set(re.findall(r"DLL Name: (\S+)", raw))
check(f"imports only system DLLs, never d3d11 ({sorted(imports)})",
      not any(i.lower().startswith(("d3d11", "dxgi")) for i in imports))
sys.exit(0 if ok else 1)

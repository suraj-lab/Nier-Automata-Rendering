#!/usr/bin/env python3
"""Re-derive the viewport / render-scale facts in VIEWPORT_RESULTS.md from the
unpacked exe (static only, never executes it). Exits non-zero on any mismatch."""
import re, struct, subprocess, sys, pathlib, hashlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE = ROOT / "input/NieRAutomata_win10.unpacked.exe"
EXE_SHA = "44ee2dc0e1f2fd939ddb39f028edb4238ecac4e9c80daad3ce925d50545a28c2"
RENDERER = "0x14177f1a0"

raw = EXE.read_bytes()
assert hashlib.sha256(raw).hexdigest() == EXE_SHA, "unexpected exe hash"

dis = subprocess.run(["x86_64-w64-mingw32-objdump", "-d", "--no-show-raw-insn", "-M", "intel", str(EXE)],
                     check=True, capture_output=True, text=True).stdout
ins, idx = [], {}
for line in dis.splitlines():
    m = re.match(r"\s+([0-9a-f]+):\t(.*)", line)
    if m:
        idx[int(m.group(1), 16)] = len(ins)
        ins.append((int(m.group(1), 16), m.group(2).strip()))

def func_start(i):
    while i > 0 and not (ins[i - 1][1] == "int3" and ins[i][1] != "int3"):
        i -= 1
    return ins[i][0]

def body(addr):
    k, out = idx[addr], []
    while ins[k][1] != "int3":
        out.append(ins[k][1]); k += 1
    return out

def callers(addr):
    return [i for i, (_, t) in enumerate(ins) if re.match(rf"(call|jmp)\s+{addr:#x}$", t)]

# PE helpers for .rdata reads
pe = struct.unpack_from("<I", raw, 0x3C)[0]
nsec, opt = struct.unpack_from("<H", raw, pe + 6)[0], struct.unpack_from("<H", raw, pe + 20)[0]
base = struct.unpack_from("<Q", raw, pe + 48)[0]
secs = [struct.unpack_from("<IIII", raw, pe + 24 + opt + 40 * s + 8) for s in range(nsec)]
def rd(va, n):
    rva = va - base
    for vs, sva, rs, ra in secs:
        if sva <= rva < sva + min(vs, rs):
            return raw[ra + rva - sva: ra + rva - sva + n]
    raise KeyError(hex(va))
q = lambda va: struct.unpack("<Q", rd(va, 8))[0]

fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

# 1. Engine context wrapper vtable
VT = 0x140db1788
check("wrapper slot 14 (+0x70) = SetViewport 0x140255c50", q(VT + 0x70) == 0x140255c50)
check("wrapper +0x1a0 = getCurW 0x140257140", q(VT + 0x1a0) == 0x140257140)
check("wrapper +0x1a8 = getCurH 0x140257150", q(VT + 0x1a8) == 0x140257150)
check("getCurW returns [this+0x570]", body(0x140257140)[0] == "mov    eax,DWORD PTR [rcx+0x570]")
check("getCurH returns [this+0x574]", body(0x140257150)[0] == "mov    eax,DWORD PTR [rcx+0x574]")
check("SetViewport calls ID3D11DeviceContext slot 44 (+0x160)",
      "call   QWORD PTR [r9+0x160]" in body(0x140255c50))

# 2. Only two RSSetViewports-like call sites in the whole exe
rs = [func_start(i) for i, (_, t) in enumerate(ins)
      if re.match(r"call\s+QWORD PTR \[r\w+\+0x160\]$", t)
      and any(re.match(r"mov\s+edx,0x1$", x[1]) for x in ins[max(0, i - 12):i])]
check("RSSetViewports sites only in wrapper + teardown 0x1405941f0",
      sorted(rs) == [0x140255c50, 0x1405941f0])

# 3. Current size written only by the RT setters (from bound target / DSV)
w570 = {func_start(i) for i, (_, t) in enumerate(ins)
        if re.match(r"mov\s+DWORD PTR \[r\w+\+0x57[04]\],eax$", t)}
# (other +0x570 writers exist but belong to unrelated object types)
check("current size written by SetRT 0x140255720 and MRT setter 0x140255cf0",
      {0x140255720, 0x140255cf0} <= w570)

# 4. Begin-pass routine sets viewport from current size
bp = body(0x140243b90)
check("0x140243b90 calls getCurH/getCurW then passState SetViewport",
      "call   QWORD PTR [rax+0x1a8]" in bp and "call   QWORD PTR [rax+0x1a0]" in bp
      and "call   0x1402436c0" in bp)
check("0x140243b90 has >=40 direct callers", len(callers(0x140243b90)) >= 40)

# 5. Renderer +0x00 / +0x80 writers via the renderer global
w0, w80 = set(), set()
for i, (_, t) in enumerate(ins):
    m = re.match(rf"mov\s+(r\w+),QWORD PTR \[rip\+0x[0-9a-f]+\]\s+# {RENDERER}$", t)
    if not m: continue
    R = m.group(1)
    for k in range(i + 1, min(i + 40, len(ins))):
        tt = ins[k][1]
        if re.match(rf"mov\s+{R},", tt) or tt.startswith("ret"): break
        if re.match(rf"mov\s+(DWORD|BYTE|QWORD) PTR \[{R}\],", tt): w0.add(func_start(k))
        if re.match(rf"movss\s+DWORD PTR \[{R}\+0x80\],", tt): w80.add(func_start(k))
check("only renderer+0x80 setter via global is 0x14024d2b0", w80 == {0x14024d2b0})
check("only renderer+0x00 setter via global is 0x14024d2f0", w0 == {0x14024d2f0})
check("scale setter callers all in debug-key fn 0x14075eaf0",
      {func_start(i) for i in callers(0x14024d2b0)} == {0x14075eaf0})
check("debug fn passes 1.0f (0x140dba840) as scale", struct.unpack("<f", rd(0x140dba840, 4))[0] == 1.0)
mode_args = []
for i in callers(0x14024d2f0):
    prev = ins[i - 1][1]
    mode_args.append(prev)
check("mode setter args are only 0/1 (imm 1, xor, setcc-derived)",
      all(re.match(r"(mov\s+ecx,0x1|xor\s+ecx,ecx|set\w+\s+cl|mov\s+ecx,esi)$", a) for a in mode_args)
      and len(mode_args) == 4)
check("renderer init writes mode=1 and scale=1.0",
      ins[idx[0x140249797]][1] == "mov    DWORD PTR [rax],0x1"
      and ins[idx[0x1402497bf]][1] == "mov    DWORD PTR [rax+0x80],0x3f800000")

# 6. 0x1402f3e60 is AMD CasSetup (const0 scale/offset, -1/lerp(8,5,sharp), 8*in/out)
cas = " ".join(body(0x1402f3e60))
check("0x1402f3e60 compares renderer mode with 2", "cmp    DWORD PTR [rdx],0x2" in cas)
check("0x1402f3e60 writes CAS const layout +0x40..+0x5c", all(f"[rbx+{o}]" in cas or f"[rdi+{o}]" in cas
      or f"+{o}]" in cas for o in ("0x40", "0x44", "0x48", "0x4c", "0x50", "0x54", "0x58", "0x5c")))

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)

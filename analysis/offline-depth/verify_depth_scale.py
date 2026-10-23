#!/usr/bin/env python3
"""Verify saved-executable depth sizing and recorded frame facts; never run the game.
Run from any directory. --record writes new evidence files here, never overwrites.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
A = HERE.parent
EXE = A / "input/NieRAutomata_win10.unpacked.exe"
SHA = "44ee2dc0e1f2fd939ddb39f028edb4238ecac4e9c80daad3ce925d50545a28c2"
BASE = 0x140000000
RANGES = {
    "colour_initial_size": (0x140248170, 0x140248262),
    "depth_initial_size": (0x14024c340, 0x14024c431),
    "depth_resize": (0x140252210, 0x140252322),
    "colour_resize_size_branch": (0x1402526f5, 0x140252780),
    "depth_init_callers": (0x140772505, 0x140772572),
    "half_depth_init_caller": (0x140772632, 0x140772652),
    "depth_object_factory": (0x14024aa90, 0x14024ab94),
    "depth_backend_dispatch": (0x140253410, 0x1402534e1),
    "depth_backend_thunk": (0x14025ce80, 0x14025ce8c),
    "depth_d3d_creation": (0x140258fe0, 0x1402591a0),
    "pass_validation": (0x1402439a0, 0x140243b85),
    "begin_pass": (0x140243b90, 0x140243e98),
    "half_velocity_pass": (0x14077edc0, 0x14077ee17),
    "old_resize_attribution": (0x14024a9c0, 0x14024aa82),
}


def instructions(text):
    return {int(m[1], 16): " ".join(m[2].split()) for m in
            re.finditer(r"^\s*([0-9a-f]+):\s+([^\n]+)", text, re.M)}


def frame(text):
    ops, sep, resources = text.partition("# Resources")
    if not sep:
        raise ValueError("missing frame resource table")
    table = dict(re.findall(r"^(T\d+)\s+([^\n]+)", resources, re.M))
    scene = []
    for line in ops.splitlines():
        m = re.search(r"\bDraw\w*\s+.*?RT=\[(T\d+)\].*?DS=(\S+) VP=(\S+)", line)
        if m and table.get(m[1], "").startswith("tex2d 1440x810 R11G11B10F ") and m[3] == "1440x810@0,0":
            scene.append(m[2])
    return ops, table, scene


def main():
    if sys.argv[1:] not in ([], ["--record"]):
        raise ValueError("usage: verify_depth_scale.py [--record]")
    # Small parser self-checks: malformed/missing input must not silently pass.
    assert instructions(" 140000010:\tcmp    eax,0x1\n junk\n") == {0x140000010: "cmp eax,0x1"}
    try:
        frame("not a frame")
    except ValueError:
        pass
    else:
        raise AssertionError("frame parser accepted missing resource table")
    _, _, sample = frame("#0000 x1 n=3 Draw VS=a RT=[T1] DS=- VP=1440x810@0,0\n# Resources\nT1 tex2d 1440x810 R11G11B10F mips=1")
    assert sample == ["-"]

    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
        print("PASS " + name)

    binary = EXE.read_bytes()
    check("analysed executable SHA-256", hashlib.sha256(binary).hexdigest() == SHA)
    pe = struct.unpack_from("<I", binary, 0x3c)[0]
    ns = struct.unpack_from("<H", binary, pe + 6)[0]
    opt = struct.unpack_from("<H", binary, pe + 20)[0]
    sections = [struct.unpack_from("<8sIIII", binary, pe + 24 + opt + 40 * i) for i in range(ns)]

    def readva(va, size):
        for _, _, rva, raw_size, raw_offset in sections:
            offset = va - BASE - rva
            if 0 <= offset and offset + size <= raw_size:
                return binary[raw_offset + offset:raw_offset + offset + size]
        raise ValueError(f"VA {va:#x} not file-backed")

    traces, ins = {}, {}
    for name, (start, stop) in RANGES.items():
        traces[name] = subprocess.check_output([
            "x86_64-w64-mingw32-objdump", "-d", "--no-show-raw-insn", "-M", "intel",
            f"--start-address={start:#x}", f"--stop-address={stop:#x}", str(EXE)], text=True)
        parsed = instructions(traces[name])
        check(f"trace starts at {name} {start:#x}", start in parsed)
        ins.update(parsed)

    def at(address, expected):
        return ins.get(address) == expected

    check("half-size constant is 0.5, not renderer scale", struct.unpack("<f", readva(0x140dba7f0, 4))[0] == 0.5)
    for name in ("depth_initial_size", "depth_resize"):
        check(name + " uses native W/H but never reads +0x80",
              "+0x3c]" in traces[name] and "+0x40]" in traces[name] and "+0x80]" not in traces[name])
    check("colour creation multiplies both dimensions by renderer scale",
          at(0x1402481b8, "mulss xmm0,DWORD PTR [r10+0x80]") and at(0x1402481e0, "mulss xmm0,DWORD PTR [r10+0x80]"))
    check("colour resize multiplies both dimensions by renderer scale",
          at(0x140252705, "mulss xmm0,DWORD PTR [rdx+0x80]") and at(0x14025273f, "mulss xmm0,DWORD PTR [r10+0x80]"))
    check("three full-screen depth handles pass half-size flag=0",
          all(at(a, "mov BYTE PTR [rsp+0x20],0x0") for a in (0x14077250b, 0x140772532, 0x140772556)))
    check("half-screen depth handle passes half-size flag=1",
          at(0x140772632, "mov r9d,r12d") and at(0x140772635, "mov BYTE PTR [rsp+0x20],r12b")
          and at(0x140772505, "mov r12d,0x1"))
    check("initial depth creation dispatches through backend +0x50",
          at(0x14024ab3e, "call 0x140253410") and at(0x140253469, "call QWORD PTR [rax+0x50]"))
    check("backend +0x50 points to depth creation thunk",
          struct.unpack("<Q", readva(0x140db1490 + 0x50, 8))[0] == 0x14025ce80
          and at(0x14025ce87, "jmp 0x140258fe0"))
    check("depth backend uses D24S8 enum 45 and D3D11 CreateTexture2D/CreateDSV",
          at(0x140259084, "mov r13d,0x2d") and at(0x1402590e5, "call QWORD PTR [rax+0x28]")
          and at(0x140259145, "call QWORD PTR [r10+0x50]"))
    check("backend records descriptor W/H in engine depth metadata",
          at(0x140259154, "mov DWORD PTR [rsi+0x8],ecx") and at(0x14025915a, "mov DWORD PTR [rsi+0xc],ecx"))
    check("depth resize callback is registered in depth node vtable",
          struct.unpack("<Q", readva(0x140db1e48 + 0x10, 8))[0] == 0x140252210)
    check("engine validator rejects either depth dimension mismatch",
          at(0x140243b5c, "cmp DWORD PTR [rcx+0x8],r9d") and at(0x140243b62, "cmp DWORD PTR [rcx+0xc],r8d")
          and at(0x140243b60, "jne 0x140243b78") and at(0x140243b66, "jne 0x140243b78")
          and at(0x140243b7d, "xor eax,eax"))
    check("failed validation returns before backend target-binding call",
          at(0x140243be2, "call 0x1402439a0") and at(0x140243be9, "je 0x140243d17")
          and at(0x140243d17, "xor eax,eax") and at(0x140243c0b, "call QWORD PTR [rax+0x80]"))
    check("old alleged target-resize helper builds a 16-byte constant buffer",
          at(0x14024aa10, "mov r9d,0x10") and at(0x14024aa4d, "call 0x14024bc50"))

    captures = {}
    for name, path in {
        "scaled": A / "scale-test-20261023/NIER_DLAA_frame_20261023_125421_835.txt",
        "native": A / "framedump-capture/NIER_DLAA_frame_20261019_224339_508.txt",
    }.items():
        data = path.read_bytes()
        ops, table, scene = frame(data.decode())
        captures[name] = {"path": str(path.relative_to(A)), "sha256": hashlib.sha256(data).hexdigest(),
                          "referenced_D24S8_textures": sum(" D24S8 " in r for r in table.values())}
        if name == "scaled":
            check("scaled capture has 444 HDR scene draw entries, all DS=-", len(scene) == 444 and set(scene) == {"-"})
            depth_rows = [r for r in table.values() if " D24S8 " in r]
            check("scaled capture references only fixed 256x256 D24S8, not scene depth",
                  len(depth_rows) == 1 and depth_rows[0].startswith("tex2d 256x256 D24S8 "))
            check("scaled capture has native 1920x1080 output resources", any(r.startswith("tex2d 1920x1080 ") for r in table.values()))
            captures[name]["scene_draw_entries"] = len(scene)
        else:
            check("native capture references full-size D24S8 scene depth", any(r.startswith("tex2d 3440x1440 D24S8 ") for r in table.values()))

    if "--record" in sys.argv:
        manifest = {"scope": "static executable + previously recorded frames; no game execution or new GPU work",
                    "exe": str(EXE.relative_to(A)), "exe_sha256": SHA,
                    "address_base": hex(BASE), "checks": checks, "passed": True, "captures": captures,
                    "ranges": {k: [hex(s), hex(e)] for k, (s, e) in RANGES.items()}}
        # Exclusive creation preserves prior evidence if --record is accidentally repeated.
        asm = HERE / "binary-traces.asm"
        report = HERE / "verification.json"
        if asm.exists() or report.exists():
            raise FileExistsError("evidence already exists; rerun without --record")
        with asm.open("x") as f:
            for name, trace in traces.items():
                f.write(f"\n; === {name} ===\n{trace}")
        manifest["traces_sha256"] = hashlib.sha256(asm.read_bytes()).hexdigest()
        with report.open("x") as f:
            f.write(json.dumps(manifest, indent=2) + "\n")
    print(f"\n{len(checks)} checks passed; game not executed.")


if __name__ == "__main__":
    main()

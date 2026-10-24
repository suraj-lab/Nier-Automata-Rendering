#!/usr/bin/env python3
"""Analyze a D3D11 frame-dump capture: scene texture, tone-map RT, depth buffers.

Usage: python3 analyze_framedump.py <dump.txt>
Prints one JSON object to stdout; exit 0 iff depth_matches_scene is true.
"""
import json
import re
import sys

TONE_MAP_PS = "2C76D68A52500A65"

# T2782  tex2d 2580x1080 R11G11B10F mips=1 array=1 msaa=1 bind=0x28
RES_RE = re.compile(
    r"^T(\d+)\s+tex2d\s+(\d+)x(\d+)\s+(\S+)\s+mips=\d+\s+array=(\d+)\b"
)
# ... PS=2C76D68A52500A65 ... VP=3440x1440@0,0 PS.SRV=[T2782,T5250,...] ...
VP_RE = re.compile(r"VP=(\d+)x(\d+)")
SRV_RE = re.compile(r"PS\.SRV=\[([^\]]*)\]")


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <dump.txt>", file=sys.stderr)
        return 2

    textures = {}
    tone_vp = None
    slot0 = None
    with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RES_RE.match(line)
            if m:
                tid, w, h, fmt, array = m.groups()
                textures[f"T{tid}"] = {
                    "w": int(w), "h": int(h), "fmt": fmt, "array": int(array),
                }
                continue
            if f"PS={TONE_MAP_PS}" not in line:
                continue
            vp = VP_RE.search(line)
            srv = SRV_RE.search(line)
            if vp and srv:
                tone_vp = (int(vp.group(1)), int(vp.group(2)))
                slot0 = srv.group(1).split(",")[0].strip()

    if slot0 in (None, "", "-"):
        scene = {"w": 0, "h": 0, "tex": "-"}
    else:
        t = textures.get(slot0, {"w": 0, "h": 0})
        scene = {"w": t["w"], "h": t["h"], "tex": slot0}

    depth = [
        {"w": t["w"], "h": t["h"], "array": t["array"], "tex": tid}
        for tid, t in textures.items() if t["fmt"] == "D24S8"
    ]

    matches = any(
        d["w"] == scene["w"] and d["h"] == scene["h"] and d["array"] == 1
        for d in depth
    )

    out = {
        "scene": scene,
        "tone_map_rt": {
            "w": tone_vp[0] if tone_vp else 0,
            "h": tone_vp[1] if tone_vp else 0,
        },
        "depth": depth,
        "depth_matches_scene": matches,
    }
    print(json.dumps(out))
    return 0 if matches else 1


if __name__ == "__main__":
    sys.exit(main())

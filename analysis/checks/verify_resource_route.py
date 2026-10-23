#!/usr/bin/env python3
"""Verify this fixed synthetic route/trace, not an arbitrary game render graph."""
import json
from pathlib import Path
import re
import sys


def fields(text):
    return dict(re.findall(r"([a-zA-Z_][a-zA-Z_0-9]*)=([^\s;]+)", text))


def verify(trace, output):
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require("ERROR:" not in trace, "trace error or truncation")
    require("RESULT route-probe PASS (mock reconstruction, not FSR/game)" in output, "probe incomplete")
    for name in ("draw", "draw-instanced", "draw-indexed", "draw-indexed-instanced", "hazard-null",
                 "OM-uav-retained", "OM-uav-keep", "native-post", "deferred-copy", "region-copy"):
        require(f"CHECK {name} PASS" in output, f"missing readback/API check: {name}")
    route = re.findall(r"^ROUTE (.+)$", output, re.M)
    require(len(route) == 1, "expected one route identity record")
    ids = {key: int(value, 16) for key, value in fields(route[0]).items()}
    require(set(ids) == {"source_id", "native_id", "post_id", "copied_id", "region_id"}, "route IDs missing")
    require(all(ids.values()) and len(set(ids.values())) == 5, "route IDs not distinct")
    rows = []
    for line in trace.splitlines():
        match = re.fullmatch(r"pid=(\d+) tid=(\d+) event=(\d+) draw=(\d+) (.+)", line)
        require(match is not None, "unrecognized trace line")
        pid, tid, event, draw, body = match.groups()
        rows.append({"pid": int(pid), "tid": int(tid), "event": int(event), "draw": int(draw),
                     "body": body, "f": fields(body)})
    require(bool(rows), "empty trace")
    require(len({row["pid"] for row in rows}) == 1, "multiple processes merged")
    require([row["event"] for row in rows] == list(range(1, len(rows) + 1)), "missing/duplicate/reordered events")
    require(rows[-1]["body"].startswith("ClearState "), "fixed fixture end marker missing")
    require(any("exports_ready=1" in row["body"] for row in rows), "next-stage loader not ready")
    creations = {int(row["f"]["id"], 16): row["f"] for row in rows if row["body"].startswith("CreateTexture2D ")}
    for key, identity in ids.items():
        require(identity in creations, f"unmapped creation: {key}")
        desc = creations[identity]
        expected = ("16", "8") if key == "source_id" else ("32", "16")
        require((desc["w"], desc["h"]) == expected and desc["fmt"] == "10", f"wrong extent/format: {key}")
    for row in rows:
        if row["body"].startswith("View "):
            f = row["f"]
            identity = int(f["id"], 16)
            if identity:
                require(identity in creations, "view resource creation missing")
                desc = creations[identity]
                require((f["w"], f["h"], f["fmt"]) == (desc["w"], desc["h"], desc["fmt"]), "view extent/format mismatch")

    def view(rows_to_check, stage, slot, identity):
        return any(row["body"].startswith("View ") and row["f"].get("stage") == stage
                   and row["f"].get("slot") == str(slot) and int(row["f"]["id"], 16) == identity
                   for row in rows_to_check)

    dispatches = [i for i, row in enumerate(rows) if row["body"].startswith("Dispatch-entry ")]
    require(len(dispatches) == 1, "expected one dispatch")
    snapshot = rows[dispatches[0] + 1:dispatches[0] + 6]
    require(view(snapshot, "CS-observed", 0, ids["source_id"]), "dispatch source not observed")
    require(view(snapshot, "CSUAV-observed", 0, ids["native_id"]), "native reconstruction UAV not observed")
    draw_events = []
    for method in ("Draw", "DrawIndexed", "DrawInstanced", "DrawIndexedInstanced"):
        entries = [row for row in rows if row["body"].startswith(method + "-entry ")]
        require(len(entries) == 1, f"missing/duplicate {method}")
        event = entries[0]["event"]
        draw_events.append(event)
        group = [row for row in rows if row["draw"] == event]
        require(view(group, "PS-observed", 0, ids["native_id"]), f"native PS input missing: {method}")
        require(view(group, "RTV-observed", 0, ids["post_id"]), f"native post target missing: {method}")
    after_draws = [i for i, row in enumerate(rows) if row["event"] > max(draw_events)
                   and row["body"].startswith("PSSetShaderResources ")]
    require(bool(after_draws) and view(rows[after_draws[0] + 1:after_draws[0] + 2], "PS-observed", 0, 0),
            "hazard did not log the effective null binding")
    keeps = [i for i, row in enumerate(rows) if row["body"].startswith("UAV-keep ")]
    require(len(keeps) == 1 and rows[keeps[0]]["f"].get("observed") == "1", "immediate UAV KEEP not observed")
    kept = rows[keeps[0] + 1:keeps[0] + 9]
    require(view(kept, "OMUAV-observed", 1, ids["native_id"]), "retained UAV missing after KEEP")
    require({row["f"].get("slot") for row in kept if row["f"].get("stage") == "OMUAV-observed"}
            == {str(i) for i in range(8)}, "KEEP did not query all base UAV slots")
    require(view(rows, "PS-requested", 0, ids["native_id"]), "deferred requested input missing")
    copies = [row for row in rows if row["body"].startswith(("CopyResource ", "CopySubresourceRegion "))]
    for row in copies:
        f = row["f"]
        if row["body"].startswith("CopyResource "):
            require((f["src_w"], f["src_h"], f["src_fmt"]) == (f["dst_w"], f["dst_h"], f["dst_fmt"]),
                    "incompatible full copy in fixed fixture")
    full = [row for row in copies if row["body"].startswith("CopyResource ")
            and int(row["f"]["src_id"], 16) == ids["post_id"]
            and int(row["f"]["dst_id"], 16) == ids["copied_id"]]
    require(len(full) == 1, "deferred full copy endpoints missing")
    region = [row for row in copies if row["body"].startswith("CopySubresourceRegion ")
              and int(row["f"]["src_id"], 16) == ids["post_id"]
              and int(row["f"]["dst_id"], 16) == ids["region_id"]]
    require(len(region) == 1, "region copy endpoints missing")
    require(any(row["body"].startswith("CopyRegionArgs ") and row["f"].get("copy_event") == str(region[0]["event"])
                and row["f"].get("xyz") == "16,8,0" and row["f"].get("bounds") == "0,0,0,16,8,1"
                for row in rows), "region copy arguments missing")
    finished = [row for row in rows if row["body"].startswith("FinishCommandList ")]
    executed = [row for row in rows if row["body"].startswith("ExecuteCommandList ")]
    require(len(finished) == len(executed) == 1, "command-list boundaries missing")
    require(int(finished[0]["f"]["list"], 16) != 0 and finished[0]["f"]["list"] == executed[0]["f"]["list"],
            "command-list identity mismatch")
    require(full[0]["f"]["ctx"] == finished[0]["f"]["ctx"] and full[0]["event"] < finished[0]["event"] < executed[0]["event"],
            "deferred recording/execution sequence mismatch")
    return {"passed": True, "events": len(rows), "draw_entries": len(draw_events), "resource_ids": ids,
            "scope": "fixed mock route only; not game/FSR integration or GPU execution ordering"}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: verify_resource_route.py texture-map.log probe-steam-0.log")
    try:
        print(json.dumps(verify(Path(sys.argv[1]).read_text(), Path(sys.argv[2]).read_text()), indent=2))
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"FAIL: {error}")

# Standing authorization for the overnight loop (written by the user, not the agent)

The loop's live actions go through `checks/unattended_guard.py` (gate `checks/test_unattended_guard.py`).
Without the file below every live action is refused and the loop stays offline.

To authorize one night, run this yourself (adjust the numbers and the expiry):

```bash
mkdir -p ~/.config/nier-auto
cat > ~/.config/nier-auto/authorization.json <<'EOF'
{"expires": "2026-11-16T12:00:00Z",
 "desktop_live_runs": 14,
 "dll_installs": 4,
 "laptop_sessions": 10,
 "attempts_per_item": 2}
EOF
chmod 444 ~/.config/nier-auto/authorization.json
```

| Key | Meaning |
| --- | --- |
| `expires` | UTC; after it every live action is refused |
| `desktop_live_runs` | `game_run.py` launches (headless RX 6800 XT, copied prefix, save hashed before/after) |
| `dll_installs` | `install_live_dll.py --install`; also needs a green full suite under 3 h old; rollback folder each time |
| `laptop_sessions` | calls to `laptop_port.py install/run/restore` over `ssh spaghetti` (each call counts; runs count attempts by run label); 0 = laptop untouched |
| `attempts_per_item` | runs per experiment label (a trailing `-N` is ignored), so one failure cannot eat the night |

Counts are per authorization file: writing a new file starts from zero. Every granted use is logged in
`~/.config/nier-auto/usage.jsonl`. To revoke: `rm ~/.config/nier-auto/authorization.json` (takes effect at the next
action) and/or `touch analysis/runtime/auto/STOP`.

Never granted to the loop, whatever this file says: commits/pushes, package or system changes, Steam/display settings,
artistic defaults, Remix MCP/Toolkit, restoring a save.

Limits: this is a tripwire, not a sandbox. The agent runs as you and could in principle edit the guard or this file;
`overnight.sh` pins their hashes at launch and stops the loop if either changes, and `usage.jsonl` plus the run
folders are the audit trail. Check `analysis/runtime/auto/REPORT.md`, `BLOCKED` and the game DLL hash in the morning.

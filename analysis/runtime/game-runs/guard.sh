#!/bin/bash
# Save guard for every unattended game run (PLAN_2026-11-13, constraint 2). The real save folder is hashed before and
# after the run; a single byte of change is reported and the verified backup is restored over it. The runs themselves
# use a COPY of the Proton prefix, so the real folder should never be touched at all.
REAL="/mnt/second/SteamLibrary/steamapps/compatdata/524220/pfx/drive_c/users/steamuser/Documents/My Games/NieR_Automata"
BACKUP="$(dirname "$0")/save-backup-2026-11-13"
case "${1:-}" in
  before) sha256sum "$REAL"/*.dat > /tmp/save-before.sha ;;
  after)
    sha256sum "$REAL"/*.dat > /tmp/save-after.sha
    if diff -q /tmp/save-before.sha /tmp/save-after.sha >/dev/null; then
      echo "save guard: real save unchanged"
    else
      echo "save guard: REAL SAVE CHANGED — restoring the verified backup"
      diff /tmp/save-before.sha /tmp/save-after.sha
      cp -a "$BACKUP"/SlotData_0.dat "$BACKUP"/GameData.dat "$BACKUP"/SystemData.dat "$BACKUP"/Graphic.ini "$REAL"/
      sha256sum "$REAL"/*.dat
    fi ;;
esac

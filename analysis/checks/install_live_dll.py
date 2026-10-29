#!/usr/bin/env python3
"""Install the candidate proxy DLL into NieR, hash-pinned, with a rollback folder. Refuses unless asked.

Usage: python3 analysis/checks/install_live_dll.py --install --expect <sha256 of the reviewed candidate>
Refuses unless the candidate's hash equals --expect (the hash recorded in analysis/ROADMAP.md for the reviewed build),
refuses while NieR is running, backs up the current file plus a RESTORE.md and receipt.json, writes the candidate
through a temporary file and an atomic rename, then verifies the installed hash. Without --install (still with --expect):
dry run.
"""
import datetime
import hashlib
import json
import shutil
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / 'runtime/menu-dll/d3d11.dll'
TARGET = Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/d3d11.dll')
BACKUPS = ROOT.parent / 'backups'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def game_running():
    if not shutil.which('pgrep'):
        sys.exit('pgrep not found: cannot prove NieR is closed, refusing')
    out = subprocess.run(['pgrep', '-af', 'NieRAutomata.exe'], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if 'pgrep' not in line]


def main():
    if not CANDIDATE.exists():
        sys.exit(f'candidate missing: {CANDIDATE}; build it first (build_menu_dll.py)')
    candidate_hash = sha256(CANDIDATE)
    current_hash = sha256(TARGET) if TARGET.exists() else ''
    print(f'candidate {CANDIDATE} {candidate_hash}')
    print(f'target    {TARGET} {current_hash}')
    expect = sys.argv[sys.argv.index('--expect') + 1].lower() if '--expect' in sys.argv[:-1] else None
    if expect != candidate_hash:
        sys.exit(f'candidate hash {candidate_hash} is not the reviewed one (--expect {expect}); rebuild or re-review')
    if not TARGET.exists():
        sys.exit(f'no DLL at {TARGET}: this installer replaces an existing proxy only')
    if '--install' not in sys.argv:
        print('dry run: nothing copied. Re-run with --install after the user approves (game must be closed).')
        return
    running = game_running()
    if running:
        sys.exit(f'NieR is running, refusing to replace the DLL:\n' + '\n'.join(running))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = BACKUPS / f'live-scene-{stamp}'
    folder.mkdir(parents=True)
    shutil.copyfile(TARGET, folder / 'd3d11.dll')
    backup_hash = sha256(folder / 'd3d11.dll')
    if backup_hash != current_hash:
        sys.exit('backup hash differs from the live file; stopping')
    staged = TARGET.with_name(TARGET.name + '.new')
    shutil.copyfile(CANDIDATE, staged)
    if sha256(staged) != candidate_hash:
        staged.unlink()
        sys.exit('staged copy hash mismatch; nothing replaced')
    os.replace(staged, TARGET)  # atomic: the game directory never holds a half-written d3d11.dll
    installed = sha256(TARGET)
    if installed != candidate_hash:
        shutil.copyfile(folder / 'd3d11.dll', staged)
        os.replace(staged, TARGET)
        restored = sha256(TARGET)
        sys.exit('installed hash mismatch; ' + ('original restored' if restored == backup_hash else
                 f'RESTORE FAILED ({restored}): copy {folder / "d3d11.dll"} back by hand'))
    receipt = {'installed_at': stamp, 'candidate': str(CANDIDATE), 'candidate_sha256': candidate_hash,
               'previous_sha256': backup_hash, 'target': str(TARGET)}
    (folder / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (folder / 'RESTORE.md').write_text(
        '# Rollback - live draw-stream scene\n\nOnly with NieR closed. Verify the current hash before replacing it.\n\n'
        f'- Backup: `{folder / "d3d11.dll"}`\n- Backup SHA256: `{backup_hash}`\n'
        f'- Candidate SHA256: `{candidate_hash}`\n- Target: `{TARGET}`\n\n'
        'Copy the verified backup back to the target to restore the previous proxy.\n'
        'Remove NIER_REMIX_LIVE from the launch options to keep this DLL but show the captured scene.\n')
    print(f'installed {installed}\nrollback {folder}')


if __name__ == '__main__':
    main()

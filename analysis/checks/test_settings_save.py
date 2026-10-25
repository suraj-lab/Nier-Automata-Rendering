#!/usr/bin/env python3
"""Run the real settings writer + real startup reader under an isolated Wine prefix.
Fixtures live in fresh directories below analysis/runtime/settings-writer/save-io/; never the game.
Python observes the actual files afterwards and checks them with the frozen save_commit_cases oracle.
Wine is not native Windows: this does not prove NTFS/ACL/ReplaceFile behavior on Windows or ARM64.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

from save_commit_cases import CASES, EXTERNAL, ORIGINAL, assert_observation
from test_startup_settings import function

C = pathlib.Path(__file__).resolve().parent
OUT = C.parent / "runtime" / "settings-writer" / "save-io"
FOREIGN = {"NIER_RENDER.ini.backup-foreign.tmp": b"foreign backup", "notes.txt": b"keep me"}
UTF16 = lambda s: b"\xff\xfe" + s.encode("utf-16-le")

EXTRA = [  # lead-added cases beyond the frozen oracle
    {'name':'invalid_preset_repair', 'initial':b'[Rendering]\r\nPreset=Quality\r\n', 'fault':None,
     'expected':{'outcome':'Committed','target_bytes':b'[Rendering]\r\nPreset=Native\r\n'}},
    {'name':'utf16_preserved', 'initial':UTF16('; c\r\n[Rendering]\r\nPreset=Custom75\r\n'), 'fault':None,
     'expected':{'outcome':'Committed','target_bytes':UTF16('; c\r\n[Rendering]\r\nPreset=Native\r\n')}},
    {'name':'unsupported_encoding_refused', 'initial':b'\xfe\xff\x00[', 'fault':None,
     'expected':{'outcome':'PreCommitFailure','target_bytes':b'\xfe\xff\x00['}},
    {'name':'directory_target_refused', 'initial':'DIR', 'fault':None,
     'expected':{'outcome':'PreCommitFailure','target_bytes':'DIR'}},
    {'name':'missing_then_created_before_save', 'initial':None, 'external_bytes':EXTERNAL,
     'fault':'before_prepare', 'expected':{'outcome':'PreCommitFailure','target_bytes':EXTERNAL}},
    # Another file with IDENTICAL bytes replaces the target: identity changed, so refuse.
    {'name':'identical_bytes_different_file', 'initial':ORIGINAL, 'external_bytes':ORIGINAL,
     'fault':'swap_identical', 'expected':{'outcome':'PreCommitFailure','target_bytes':ORIGINAL}},
    # File deleted between the menu's snapshot and reader: re-observed as missing, never "invalid".
    {'name':'deleted_between_snapshot_and_reader', 'initial':ORIGINAL, 'fault':'delete_before_reader',
     'expected':{'outcome':'Committed','target_bytes':b'[Rendering]\r\nPreset=Native\r\n'}},
]

HARNESS = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cassert>
#include <cstdio>
#include <string>
#include "render_settings.h"
#include "settings_save.h"
#include "menu_settings_io.h"
'''

MAIN = r'''
struct Ctx { std::string fault; std::wstring external; std::wstring backup; };
static bool hook(void* p, settings_save::Point point, const settings_save::Attempt& a) {
    using P = settings_save::Point;
    auto& c = *static_cast<Ctx*>(p);
    c.backup = a.backup;
    const auto external = [&] { assert(CopyFileW(c.external.c_str(), a.target.c_str(), FALSE)); return false; };
    const auto& f = c.fault;
    if (point == P::BeforePrepare && f == "before_prepare") return external();
    if (point == P::BeforePublishRecheck && f == "before_publish_recheck") return external();
    if (point == P::BeforePublishRecheck && f == "swap_identical") {  // new file created before old is unlinked
        const std::wstring swap = a.target + L".swap";
        assert(CopyFileW(c.external.c_str(), swap.c_str(), TRUE));
        assert(MoveFileExW(swap.c_str(), a.target.c_str(), MOVEFILE_REPLACE_EXISTING));
        return false;
    }
    if (point == P::Publish && f == "atomic_missing_publish") return external();
    if (point == P::Publish && f == "replace_original_moved") { assert(MoveFileW(a.target.c_str(), a.backup.c_str())); return true; }
    return (point == P::StageCreated && f == "before_stage_contents") || (point == P::StageWrite && f == "stage_write") ||
           (point == P::StageFlush && f == "stage_flush") || (point == P::StageClose && f == "stage_close") ||
           (point == P::StageValidation && f == "stage_reader_validation") || (point == P::Publish && f == "replace_unchanged") ||
           (point == P::FinalObservation && f == "after_publish_observation");
}
static bool delete_on_next_read = false;
static render_settings::Settings test_reader(const std::wstring& path) {
    if (delete_on_next_read) { delete_on_next_read = false; assert(DeleteFileW(path.c_str())); }
    return read_render_settings(path);
}
static std::string ascii(const std::wstring& w) {
    std::string s; for (wchar_t c : w) { assert(c > 0 && c < 128); s.push_back(static_cast<char>(c)); } return s;
}
int wmain(int argc, wchar_t** argv) {
    for (int i = 1; i < argc; ++i) {
        const std::wstring dir = std::wstring(argv[i]) + L"\\";
        Ctx ctx; ctx.external = dir + L"external.bin";
        if (FILE* f = _wfopen((dir + L"fault.txt").c_str(), L"rb")) {
            char buf[64] = {}; ctx.fault.assign(buf, std::fread(buf, 1, sizeof buf - 1, f)); std::fclose(f);
        }
        const std::wstring target = dir + L"target\\NIER_RENDER.ini";
        delete_on_next_read = ctx.fault == "delete_before_reader";
        const auto shown = menu_settings_io::observe(target, test_reader);  // what the menu showed
        assert(!delete_on_next_read);
        const auto report = menu_settings_io::save(target, shown, render_settings::Mode::Native, test_reader, hook, &ctx);
        const auto& r = report.detail;
        FILE* states = _wfopen((dir + L"states.txt").c_str(), L"wb");
        assert(states);
        std::fprintf(states, "%d %d %d %d\n", static_cast<int>(shown.file), static_cast<int>(report.outcome),
                     static_cast<int>(report.after.file), static_cast<int>(report.after.next_launch));
        std::fclose(states);
        FILE* out = _wfopen((dir + L"result.txt").c_str(), L"wb");
        assert(out);
        std::fprintf(out, "%d\n%d\n%lu\n%s\n", static_cast<int>(r.outcome), static_cast<int>(r.step),
                     static_cast<unsigned long>(r.error), ascii(ctx.backup).c_str());
        for (const auto& p : r.recovery_paths) std::fprintf(out, "%s\n", ascii(p).c_str());
        std::fclose(out);
    }
    std::puts("settings writer harness finished");
    return 0;
}
'''

OUTCOMES = ['PreCommitFailure', 'Committed', 'RecoveryRequired']
FILES = ['Valid', 'Missing', 'Invalid', 'Unreadable']
MENU_OUTCOMES = ['Committed', 'NotSaved', 'RecoveryRequired']
MODES = ['Native', 'Custom75']
# Menu adapter: (file shown before, menu outcome, file re-read after, next-launch mode re-read after).
STATES = {
    'existing_success': ('Valid', 'Committed', 'Valid', 'Native'),
    'missing_success': ('Missing', 'Committed', 'Valid', 'Native'),
    'snapshot_stale_before_save': ('Valid', 'NotSaved', 'Valid', 'Native'),
    'snapshot_stale_after_stage': ('Valid', 'NotSaved', 'Valid', 'Native'),
    'stage_write_failure': ('Valid', 'NotSaved', 'Valid', 'Custom75'),
    'stage_flush_failure': ('Valid', 'NotSaved', 'Valid', 'Custom75'),
    'stage_close_failure': ('Valid', 'NotSaved', 'Valid', 'Custom75'),
    'stage_security_failure': ('Valid', 'NotSaved', 'Valid', 'Custom75'),
    'stage_reader_rejects': ('Valid', 'NotSaved', 'Valid', 'Custom75'),
    'replacement_rejected_without_move': ('Valid', 'NotSaved', 'Valid', 'Custom75'),
    'replacement_failed_original_moved': ('Valid', 'RecoveryRequired', 'Missing', 'Custom75'),
    'published_but_final_observation_failed': ('Valid', 'RecoveryRequired', 'Valid', 'Native'),
    'missing_target_created_concurrently': ('Missing', 'NotSaved', 'Valid', 'Native'),
    'invalid_preset_repair': ('Invalid', 'Committed', 'Valid', 'Native'),
    'utf16_preserved': ('Valid', 'Committed', 'Valid', 'Native'),
    'unsupported_encoding_refused': ('Unreadable', 'NotSaved', 'Unreadable', 'Native'),
    'directory_target_refused': ('Unreadable', 'NotSaved', 'Unreadable', 'Native'),
    'missing_then_created_before_save': ('Missing', 'NotSaved', 'Valid', 'Native'),
    'identical_bytes_different_file': ('Valid', 'NotSaved', 'Valid', 'Custom75'),
    'deleted_between_snapshot_and_reader': ('Missing', 'Committed', 'Valid', 'Native'),
}


def win(path):
    return 'Z:' + str(path).replace('/', '\\')


def linux(path):
    assert path.startswith('Z:'), path
    return pathlib.Path(path[2:].replace('\\', '/'))


def contents(path):
    if path.is_dir():
        return 'DIR'
    return path.read_bytes() if path.is_file() else None


def setup(root, case):
    d = root / case['name']
    (d / 'target').mkdir(parents=True)
    target = d / 'target' / 'NIER_RENDER.ini'
    if case['initial'] == 'DIR':
        target.mkdir()
    elif case['initial'] is not None:
        target.write_bytes(case['initial'])
    for name, data in FOREIGN.items():
        (d / 'target' / name).write_bytes(data)
    (d / 'fault.txt').write_text(case['fault'] or '')
    if 'external_bytes' in case:
        (d / 'external.bin').write_bytes(case['external_bytes'])
    return d


def check(d, case):
    lines = (d / 'result.txt').read_text().splitlines()
    outcome, step, error = OUTCOMES[int(lines[0])], int(lines[1]), int(lines[2])
    backup = linux(lines[3]) if lines[3] else None
    recovery = [linux(p) for p in lines[4:]]
    target_dir = d / 'target'
    stage = backup and pathlib.Path(str(backup).replace('.backup-', '.save-'))
    observed = {
        'outcome': outcome,
        'target_bytes': contents(target_dir / 'NIER_RENDER.ini'),
        'backup_bytes': contents(backup) if backup else None,
        'stage_contains_original': bool(stage and stage.is_file() and stage.read_bytes() == case['initial']),
        'can_claim_saved': outcome == 'Committed',  # UI rule: only Committed acknowledges a save
        'foreign_files_unchanged': all((target_dir / n).read_bytes() == b for n, b in FOREIGN.items()),
        'recovery_paths': [str(p) for p in recovery],
    }
    assert_observation(case, observed)
    f0, o, f1, m = map(int, (d / 'states.txt').read_text().split())
    states = (FILES[f0], MENU_OUTCOMES[o], FILES[f1], MODES[m])
    assert states == STATES[case['name']], (case['name'], states)
    # Owned temporary files: every leftover must be reported for recovery; none otherwise.
    owned = sorted(p for p in target_dir.iterdir() if p.name not in FOREIGN and p.name != 'NIER_RENDER.ini')
    if outcome == 'RecoveryRequired':
        assert all(p.exists() for p in recovery), case['name']
        assert set(owned) <= set(recovery), (case['name'], owned)
    else:
        assert not owned, (case['name'], owned)
        assert not recovery, case['name']
    return {'name': case['name'], 'outcome': outcome, 'step': step, 'error': error,
            'leftover_recovery_files': [p.name for p in owned]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ('home', 'cache'):
        (OUT / name).mkdir(exist_ok=True)
    cpp, exe = OUT / 'save_probe.cpp', OUT / 'save_probe.exe'
    cpp.write_text(HARNESS + function('read_render_settings') + MAIN)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-municode',
                    '-static', '-static-libgcc', '-static-libstdc++', '-I', str(C), str(cpp), '-o', str(exe)], check=True)
    root = pathlib.Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    cases = CASES + EXTRA
    dirs = [setup(root, c) for c in cases]
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree=d;mshtml=d;winemenubuilder.exe=d', DISPLAY='', WAYLAND_DISPLAY='')
    subprocess.run(['wine', str(exe), *map(win, dirs)], env=env, cwd=OUT, check=True, timeout=300)
    results = [check(d, c) for d, c in zip(dirs, cases)]
    receipt = {'passed': True, 'oracle_cases': len(CASES), 'extra_cases': len(EXTRA), 'fixtures': str(root),
               'writer_executed': True, 'platform': 'Wine (not native Windows/ARM64)', 'results': results}
    (OUT / 'validation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: receipt[k] for k in ('passed', 'oracle_cases', 'extra_cases', 'platform')}))
    for r in results:
        print(r)


if __name__ == '__main__':
    sys.exit(main())

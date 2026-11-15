#!/usr/bin/env python3
"""Frozen gate for P1 settings persistence (checks/upscaler_settings.h).

Native C++17 + std::filesystem only. Pins: default when absent, round trip, invalid value falls back and is
reported, atomic replace leaves the previous file intact on failure, and the render-preset file is never touched.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent

HARNESS = r'''
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <sys/resource.h>
#include <csignal>
#include "upscaler_settings.h"

namespace fs = std::filesystem;
static int failures = 0;
static void check(const char* what, bool ok) { if (!ok) { ++failures; std::printf("FAIL %s\n", what); } }

int main(int, char** argv) {
    const fs::path dir = argv[1];
    const fs::path ini = dir / "NIER_REMIX.ini";
    std::string err;
    using upscaler::Mode;

    // Absent file: today's behaviour, no error.
    check("absent file -> Config", upscaler::load_mode(ini, &err) == Mode::Config && err.empty());

    // Round trip for every named mode.
    for (const char* name : {"config", "ultra-performance", "performance", "balanced", "quality"}) {
        Mode want = Mode::Config;
        check("name valid", upscaler::parse_mode(name, want));
        check("save ok", upscaler::save_mode(ini, want, &err));
        check("reload matches", upscaler::load_mode(ini, &err) == want);
    }

    // Unknown value in the file: fall back to Config and report, never guess.
    { std::ofstream(ini) << "upscaler = ultra-super\n"; }
    err.clear();
    check("invalid value -> Config", upscaler::load_mode(ini, &err) == Mode::Config);
    check("invalid value reported", !err.empty());

    // A file with other keys keeps them; only the upscaler key is ours.
    { std::ofstream(ini) << "# comment\nsomething = else\nupscaler = balanced\n"; }
    err.clear();
    const Mode kept = upscaler::load_mode(ini, &err);
    check("other keys tolerated", kept == Mode::Balanced && err.empty());
    check("save preserves foreign keys", upscaler::save_mode(ini, Mode::Quality, &err));
    { std::ifstream in(ini); std::string body((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
      check("foreign key survived save", body.find("something = else") != std::string::npos);
      check("upscaler rewritten", body.find("upscaler = quality") != std::string::npos); }

    // Atomic replace: a failure path must leave the previous contents readable, never a truncated file.
    err.clear();
    check("save into an unwritable path fails", !upscaler::save_mode(dir / "missing" / "deep" / "x.ini", Mode::Quality, &err));
    check("failure reported", !err.empty());
    { std::ifstream in(ini); std::string body((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
      check("previous contents intact after failed save", body.find("upscaler = quality") != std::string::npos); }

    // Atomic replace is observable: a successful save must replace the directory entry (new inode), not rewrite in
    // place, and must leave no .tmp sibling behind.
    struct stat before_st {};
    check("target exists before atomic check", ::stat(ini.c_str(), &before_st) == 0);
    check("save ok", upscaler::save_mode(ini, Mode::Balanced, &err));
    struct stat after_st {};
    check("target exists after atomic check", ::stat(ini.c_str(), &after_st) == 0);
    check("save replaced the file (rename, not in-place write)", before_st.st_ino != after_st.st_ino);
    check("no .tmp left behind", !fs::exists(ini.string() + ".tmp"));

    // Review 25271ddb finding 1: an unreadable target must not be replaced by a file holding only our key.
    if (::geteuid() != 0) {  // root reads mode-000 files, so the case is meaningless there
        { std::ofstream(ini) << "foo = 1\nupscaler = balanced\n"; }
        fs::permissions(ini, fs::perms::none);
        err.clear();
        check("save over an unreadable file fails", !upscaler::save_mode(ini, Mode::Quality, &err));
        check("unreadable file reported", !err.empty());
        fs::permissions(ini, fs::perms::owner_read | fs::perms::owner_write);
        std::ifstream in(ini); std::string body((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
        check("foreign key survived the refused save", body.find("foo = 1") != std::string::npos);
        check("no .tmp left after refused save", !fs::exists(ini.string() + ".tmp"));

        // Finding 2: an unsearchable parent must be an error, never an exception (it would disable the Remix host).
        const fs::path locked = dir / "locked";
        fs::create_directories(locked);
        { std::ofstream(locked / "NIER_REMIX.ini") << "upscaler = quality\n"; }
        fs::permissions(locked, fs::perms::none);
        bool threw = false;
        Mode got = Mode::Quality;
        err.clear();
        try { got = upscaler::load_mode(locked / "NIER_REMIX.ini", &err); } catch (...) { threw = true; }
        check("load in unsearchable dir does not throw", !threw);
        check("load in unsearchable dir -> Config with error", !threw && got == Mode::Config && !err.empty());
        threw = false; err.clear();
        bool saved = true;
        try { saved = upscaler::save_mode(locked / "NIER_REMIX.ini", Mode::Balanced, &err); } catch (...) { threw = true; }
        check("save in unsearchable dir does not throw", !threw);
        check("save in unsearchable dir fails with error", !threw && !saved && !err.empty());
        fs::permissions(locked, fs::perms::owner_all);
    }

    // Never follow or overwrite a pre-existing temp file, including a symlink.
    const fs::path foreign = dir / "foreign.txt";
    { std::ofstream(foreign) << "not ours\n"; }
    fs::create_symlink(foreign, ini.string() + ".tmp");
    err.clear();
    check("pre-existing temp sibling refused", !upscaler::save_mode(ini, Mode::Quality, &err) && !err.empty());
    { std::ifstream in(foreign); std::string body((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
      check("temp symlink target untouched", body == "not ours\n"); }
    check("foreign temp symlink retained", fs::is_symlink(ini.string() + ".tmp"));
    fs::remove(ini.string() + ".tmp");  // fixture only

    // A real write failure (file-size limit) must keep the target and discard only our temp file.
    struct rlimit original_limit {};
    check("get file-size limit", ::getrlimit(RLIMIT_FSIZE, &original_limit) == 0);
    struct rlimit short_limit = original_limit;
    short_limit.rlim_cur = 1;
    ::signal(SIGXFSZ, SIG_IGN);
    check("set test file-size limit", ::setrlimit(RLIMIT_FSIZE, &short_limit) == 0);
    err.clear();
    const bool short_save = upscaler::save_mode(ini, Mode::Quality, &err);
    ::setrlimit(RLIMIT_FSIZE, &original_limit);
    check("short write fails with error", !short_save && !err.empty());
    check("no temp left after short write", !fs::exists(ini.string() + ".tmp"));
    { std::ifstream in(ini); std::string body((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
      check("file intact after short write", body.find("upscaler = quality") == std::string::npos); }

    // The render preset file is a different contract and must not be written here.
    const fs::path render = dir / "NIER_RENDER.ini";
    { std::ofstream(render) << "[Rendering]\r\nPreset=Native\r\n"; }
    std::string render_before, render_after;
    { std::ifstream in(render); render_before.assign((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>()); }
    upscaler::save_mode(ini, Mode::Balanced, &err);
    { std::ifstream in(render); render_after.assign((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>()); }
    check("NIER_RENDER.ini untouched", !render_before.empty() && render_before == render_after);
    return failures ? 1 : 0;
}
'''

if __name__ == '__main__':
    try:
        base = C.parent / 'runtime/p1-settings-gate'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            w = Path(tmp)
            (w / 'test.cpp').write_text(HARNESS)
            build = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(C),
                                    str(w / 'test.cpp'), '-o', str(w / 'test')], capture_output=True, text=True)
            assert build.returncode == 0, 'compile failed: ' + build.stderr[-1500:]
            run = subprocess.run([str(w / 'test'), str(w)], capture_output=True, text=True)
            assert run.returncode == 0, (run.stdout + run.stderr)[-1500:]
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)

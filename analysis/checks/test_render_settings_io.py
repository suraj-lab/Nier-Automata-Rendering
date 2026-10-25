#!/usr/bin/env python3
"""Run the real startup INI reader with Win32 APIs under an isolated Wine prefix.
Requires wine + x86_64-w64-mingw32-g++; doesn't load the NieR proxy or start the game.
All generated files/prefix state stay below analysis/runtime/settings-io/.
"""
import os
import pathlib
import subprocess

from test_startup_settings import function

C = pathlib.Path(__file__).resolve().parent
OUT = C.parent / "runtime" / "settings-io"

PREAMBLE = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cassert>
#include <cstdio>
#include <string>
#include "render_settings.h"
static std::wstring module_dir;
'''

TEST = r'''
int main() {
    wchar_t temp[512];
    assert(GetTempPathW(512,temp)>0);
    module_dir=std::wstring(temp)+L"NierSettingsProbe-"+std::to_wstring(GetCurrentProcessId())+L"\\";
    assert(CreateDirectoryW(module_dir.c_str(),nullptr));
    const auto path=module_dir+L"NIER_RENDER.ini";
    const auto put=[&](const std::wstring& text) {
        HANDLE f=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
        assert(f!=INVALID_HANDLE_VALUE);
        DWORD written=0;
        assert(WriteFile(f,text.data(),static_cast<DWORD>(text.size()*sizeof(wchar_t)),&written,nullptr));
        assert(written==text.size()*sizeof(wchar_t));
        assert(CloseHandle(f));
        // Evict profile API cache between fixtures; production reads once per new process.
        WritePrivateProfileStringW(nullptr,nullptr,nullptr,path.c_str());
    };
    const auto expect=[&](render_settings::Mode mode,bool valid,bool defaulted) {
        const auto s=load_render_settings();
        assert(s.mode==mode && s.valid==valid && s.defaulted==defaulted);
    };
    using render_settings::Mode;
    expect(Mode::Custom75,true,true);  // missing file only
    put(L"\ufeff[Rendering]\r\nPreset=Native\r\n"); expect(Mode::Native,true,false);
    put(L"\ufeff[Rendering]\r\nPreset= cUsToM75 \r\n"); expect(Mode::Custom75,true,false);
    put(L"\ufeff[Rendering]\r\nPreset=Quality\r\n"); expect(Mode::Native,false,false);
    put(L"\ufeff[Other]\r\nPreset=Custom75\r\n"); expect(Mode::Native,false,false);
    put(L"\ufeff[Rendering]\r\nPreset=\r\n"); expect(Mode::Native,false,false);
    put(L""); expect(Mode::Native,false,false);
    put(L"\ufeff[Rendering]\r\nPreset="+std::wstring(5000,L'x')); expect(Mode::Native,false,false);
    put(L"\ufeff[Rendering]\r\nPreset=Custom75\r\n");
    HANDLE lock=CreateFileW(path.c_str(),GENERIC_READ,0,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    assert(lock!=INVALID_HANDLE_VALUE); expect(Mode::Native,false,false); assert(CloseHandle(lock));
    assert(DeleteFileW(path.c_str()));
    WritePrivateProfileStringW(nullptr,nullptr,nullptr,path.c_str());
    assert(CreateDirectoryW(path.c_str(),nullptr)); expect(Mode::Native,false,false);
    assert(RemoveDirectoryW(path.c_str()));
    module_dir+=L"NoParent\\"; expect(Mode::Native,false,false); // broken directory isn't a missing file
    module_dir.resize(module_dir.size()-9);
    assert(RemoveDirectoryW(module_dir.c_str()));
    std::puts("real Win32 INI reader: 11 cases passed (Wine, no game loaded)");
}
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("home", "cache"):
        (OUT / name).mkdir(exist_ok=True)
    cpp, exe = OUT / "probe.cpp", OUT / "probe.exe"
    cpp.write_text(PREAMBLE + function("read_render_settings") + function("load_render_settings") + TEST)
    subprocess.run(["x86_64-w64-mingw32-g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-static", "-static-libgcc", "-static-libstdc++", "-I", str(C), str(cpp), "-o", str(exe)], check=True)
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT / "prefix"), HOME=str(OUT / "home"), XDG_CACHE_HOME=str(OUT / "cache"),
               WINEDEBUG="-all", WINEDLLOVERRIDES="winemenubuilder.exe=d", DISPLAY="", WAYLAND_DISPLAY="")
    subprocess.run(["wine", str(exe)], env=env, cwd=OUT, check=True, timeout=180)


if __name__ == "__main__":
    main()

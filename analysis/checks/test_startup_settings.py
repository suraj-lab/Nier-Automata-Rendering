#!/usr/bin/env python3
"""Exercise actual setter function bodies with native Win32 mocks; never load a DLL/game.
Complements MinGW ABI/build and pure logic tests. Mock OS calls don't prove live hotpatch safety.
"""
import pathlib
import subprocess
import tempfile
import unittest

C = pathlib.Path(__file__).resolve().parent


def function(name):
    src = (C / "d3d11_scale_setter.cpp").read_text()
    # Use the exact declaration; named functions have no brace literals in their signatures.
    import re
    m = re.search(r"static [^;{}\n]+\b" + name + r"\([^;{}]*\)\s*\{", src)
    if not m:
        raise AssertionError(f"missing function {name}")
    end, depth = m.end(), 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[end], 0)
        end += 1
    return src[m.start():end]


COMMON = r'''
#include "proxy_patch.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <cwchar>
#include <map>
#include <string>
#include <vector>
using DWORD = std::uint32_t;
#define WINAPI
struct IMAGE_DOS_HEADER { std::int32_t e_lfanew; };
struct IMAGE_NT_HEADERS64 { struct { std::size_t SizeOfImage; } OptionalHeader; };
static std::vector<std::string> logs;
static void logf_line(const char* fmt, ...) {
    char line[1024]; va_list a; va_start(a,fmt); vsnprintf(line,sizeof line,fmt,a); va_end(a);
    logs.emplace_back(line);
}
'''

PROXY = r'''
struct ID3D11DeviceContext {};
static void on_dispatch_exit(ID3D11DeviceContext*) {}
constexpr DWORD PAGE_EXECUTE_READ=0x20, PAGE_EXECUTE_READWRITE=0x40, MEM_RELEASE=0x8000;
static constexpr std::size_t count=sizeof(proxy_patch::kSites)/sizeof(proxy_patch::kSites[0]);
static std::vector<unsigned char> image(0x1b000), original;
alignas(16) static unsigned char cave[proxy_patch::kCaveSize];
static void* proxy_module=image.data();
static std::uint8_t* proxy_cave=nullptr;
static std::map<std::size_t,DWORD> pages, old_pages;
static int fail_prepare=-1, prepare_calls=0, flush_calls=0, fail_flush=-1, freed=0;
static bool cleanup=false, fail_restore_once=false;
static void* alloc_cave_near(const void*,std::size_t n) { assert(n==sizeof cave); return cave; }
static void* GetCurrentProcess() { return nullptr; }
static DWORD GetLastError() { return 5; }
static bool VirtualFree(void* p,std::size_t n,DWORD f) { assert(p==cave && n==0 && f==MEM_RELEASE); ++freed; return true; }
static bool VirtualProtect(void* address,std::size_t len,DWORD mode,DWORD* old) {
    const auto rva=static_cast<unsigned char*>(address)-image.data();
    assert(rva>=0 && len>0 && static_cast<std::size_t>(rva)+len<=image.size());
    const auto page=static_cast<std::size_t>(rva)/4096;
    // Every real patch site lies in one page. Simulate page-granularity permissions (some overlap).
    assert(page==(static_cast<std::size_t>(rva)+len-1)/4096);
    if (!cleanup && mode==PAGE_EXECUTE_READWRITE) {
        if (prepare_calls++==fail_prepare) { cleanup=true; return false; }
        if (prepare_calls==static_cast<int>(count)) cleanup=true;
    } else if (cleanup && fail_restore_once && mode!=PAGE_EXECUTE_READWRITE) {
        fail_restore_once=false; return false;
    }
    *old=pages[page]; pages[page]=mode; return true;
}
static bool FlushInstructionCache(void*,const void*,std::size_t) { return flush_calls++ != fail_flush; }
static void reset() {
    std::fill(image.begin(),image.end(),0xcc);
    reinterpret_cast<IMAGE_DOS_HEADER*>(image.data())->e_lfanew=64;
    reinterpret_cast<IMAGE_NT_HEADERS64*>(image.data()+64)->OptionalHeader.SizeOfImage=image.size();
#define SIG(site, sig) std::memcpy(image.data()+proxy_patch::site,proxy_patch::sig,sizeof(proxy_patch::sig))
    SIG(kOutWidthPatchRva,kOutWidthSig); SIG(kOutHeightPatchRva,kOutHeightSig); SIG(kOutputPatchRva,kOutputSig);
    SIG(kExitPatchRva,kExitSig); SIG(kCopyBackPatchRva,kCopyBackSig); SIG(kGatePatchRva,kGateSig);
    SIG(kDepthGatePatchRva,kDepthGateSig);
#undef SIG
    pages.clear(); for (const auto& s:proxy_patch::kSites) pages[s.rva/4096]=PAGE_EXECUTE_READ;
    old_pages=pages; original=image; proxy_cave=nullptr; fail_prepare=-1; prepare_calls=flush_calls=freed=0;
    fail_flush=-1; cleanup=false; fail_restore_once=false; logs.clear();
}
'''

PROXY_MAIN = r'''
int main() {
    // Every preparation failure must leave all bytes untouched, including failures after the copy-skip site.
    for (std::size_t i=0;i<count;++i) {
        reset(); fail_prepare=static_cast<int>(i);
        assert(apply_proxy_patch()!=proxy_patch::Result::Applied);
        assert(image==original && pages==old_pages && proxy_cave==nullptr);
        // Failed preparation plus a one-off cleanup failure must also leave permissions intact.
        reset(); fail_prepare=static_cast<int>(i); fail_restore_once=true;
        assert(apply_proxy_patch()!=proxy_patch::Result::Applied);
        assert(image==original && pages==old_pages && proxy_cave==nullptr);
    }
    reset();
    assert(apply_proxy_patch()==proxy_patch::Result::Applied && proxy_cave==cave && pages==old_pages);
    for (const auto& s:proxy_patch::kSites) {
        std::uint8_t expected[10]; std::memset(expected,0x90,sizeof expected);
        proxy_patch::emit_jump(expected,reinterpret_cast<std::uintptr_t>(image.data())+s.rva,
                               reinterpret_cast<std::uintptr_t>(cave)+s.cave_off);
        assert(std::memcmp(expected,image.data()+s.rva,s.len)==0);
    }
    // Flush failure on the new cave must not publish any jump; failure after publication must roll back.
    for (int i=0;i<=static_cast<int>(count);++i) {
        reset(); fail_flush=i;
        assert(apply_proxy_patch()!=proxy_patch::Result::Applied);
        assert(image==original && pages==old_pages && proxy_cave==nullptr);
    }
    // A one-off protection restore failure is reported, rolls bytes back, and restores page permissions.
    reset(); fail_restore_once=true;
    assert(apply_proxy_patch()!=proxy_patch::Result::Applied);
    assert(image==original && pages==old_pages && proxy_cave==nullptr);
    // Changed signature is rejected before touching page permissions.
    reset(); image[proxy_patch::kExitPatchRva]^=1; original=image;
    assert(apply_proxy_patch()==proxy_patch::Result::SigMismatch);
    assert(image==original && prepare_calls==0);
    std::puts("proxy install failure tests: all passed");
}
'''

STARTUP = r'''
#include "render_settings.h"
#include "startup_status.h"
#include "depth_patch.h"
#include <new>
static startup_status::Publication startup_observation;
using LONG=long;
static volatile LONG setter_started=0;
static bool thread_create_ok=true;
static int thread_calls=0;
static LONG InterlockedCompareExchange(volatile LONG* p,LONG value,LONG expected) {
    const LONG old=*p;if(old==expected)*p=value;return old;
}
static std::wstring module_dir=L"Z:\\test\\";
static constexpr int kPollMs=250,kPollTries=2;
constexpr DWORD INVALID_FILE_ATTRIBUTES=0xffffffffu, FILE_ATTRIBUTE_DIRECTORY=0x10;
constexpr DWORD ERROR_FILE_NOT_FOUND=2, ERROR_PATH_NOT_FOUND=3, GENERIC_READ=0x80000000u;
constexpr DWORD FILE_SHARE_READ=1,FILE_SHARE_WRITE=2,FILE_SHARE_DELETE=4,OPEN_EXISTING=3,FILE_ATTRIBUTE_NORMAL=0x80;
using HANDLE=void*;
#define INVALID_HANDLE_VALUE reinterpret_cast<HANDLE>(-1)
static DWORD attrs=FILE_ATTRIBUTE_NORMAL,error=0;
static std::wstring ini_value=L"Custom75", seen_path;
static bool open_ok=true;
static int handles=0,depth_calls=0,proxy_calls=0,scale_calls=0,exe_calls=0;
static std::vector<unsigned char> exe(256);
alignas(16) static std::uint8_t cave[proxy_patch::kCaveSize];
static std::uint8_t* proxy_cave=cave;
static depth_patch::Result depth_result=depth_patch::Result::Applied;
static proxy_patch::Result proxy_result=proxy_patch::Result::Applied;
static DWORD GetFileAttributesW(const wchar_t* path) { seen_path=path; return attrs; }
static DWORD GetLastError() { return error; }
static HANDLE CreateFileW(const wchar_t*,DWORD access,DWORD share,void*,DWORD disposition,DWORD,void*) {
    assert(access==GENERIC_READ && share==(FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE) && disposition==OPEN_EXISTING);
    if (!open_ok) return INVALID_HANDLE_VALUE;
    ++handles; return reinterpret_cast<HANDLE>(1);
}
static bool CloseHandle(HANDLE) { --handles; return true; }
static HANDLE CreateThread(void*,std::size_t,DWORD(*entry)(void*),void* arg,DWORD,DWORD*) {
    ++thread_calls;if(!thread_create_ok){error=8;return nullptr;}
    ++handles;entry(arg);return reinterpret_cast<HANDLE>(2);
}
static DWORD GetPrivateProfileStringW(const wchar_t* section,const wchar_t* key,const wchar_t*,
                                      wchar_t* out,DWORD cap,const wchar_t* path) {
    assert(std::wstring(section)==L"Rendering" && std::wstring(key)==L"Preset" && std::wstring(path)==seen_path);
    const auto n=std::min(ini_value.size(),static_cast<std::size_t>(cap-1));
    std::copy_n(ini_value.data(),n,out); out[n]=0; return static_cast<DWORD>(n);
}
static void* GetModuleHandleW(const wchar_t*) { ++exe_calls; return exe.data(); }
static void Sleep(int) {}
static bool readable(const void*,std::size_t) { return true; }
static depth_patch::Result apply_depth_patch(unsigned char*,std::size_t) { ++depth_calls; return depth_result; }
static proxy_patch::Result apply_proxy_patch() { ++proxy_calls; return proxy_result; }
namespace scale_patch {
    enum class Result { Applied,NoRenderer,NotDefault };
    struct Info { std::uint32_t width=3440,height=1440; float before=1.0f; void* renderer=nullptr; };
    static Result result=Result::Applied;
    static Result try_apply(unsigned char*,std::size_t,float s,bool(*)(const void*,std::size_t),Info*) {
        assert(s==0.75f); ++scale_calls; return result;
    }
    static bool retryable(Result r) { return r==Result::NoRenderer; }
    static const char* name(Result) { return "mock"; }
}
static void reset() {
    startup_observation.~Publication();new (&startup_observation) startup_status::Publication();
    setter_started=0;thread_create_ok=true;thread_calls=0;proxy_cave=cave;
    attrs=FILE_ATTRIBUTE_NORMAL; error=0; ini_value=L"Custom75"; open_ok=true;
    handles=depth_calls=proxy_calls=scale_calls=exe_calls=0; logs.clear();
    depth_result=depth_patch::Result::Applied; proxy_result=proxy_patch::Result::Applied;
    scale_patch::result=scale_patch::Result::Applied;
    const float one=1; std::memcpy(cave+proxy_patch::kScaleOff,&one,4);
    reinterpret_cast<IMAGE_DOS_HEADER*>(exe.data())->e_lfanew=64;
    reinterpret_cast<IMAGE_NT_HEADERS64*>(exe.data()+64)->OptionalHeader.SizeOfImage=exe.size();
}
static float slot() { float f; std::memcpy(&f,cave+proxy_patch::kScaleOff,4); return f; }
'''

STARTUP_MAIN = r'''
int main() {
    reset(); attrs=INVALID_FILE_ATTRIBUTES; error=ERROR_FILE_NOT_FOUND;
    assert(setter_thread(nullptr)==0 && depth_calls==1 && proxy_calls==1 && scale_calls==1 && slot()==0.75f);
    assert(seen_path==module_dir+L"NIER_RENDER.ini" && handles==0);
    reset(); assert(setter_thread(nullptr)==0 && scale_calls==1 && slot()==0.75f && handles==0);
    for (const auto text: {L"Native", L"native", L"Quality", L"", L"bad"}) {
        reset(); ini_value=text; assert(setter_thread(nullptr)==0);
        assert(exe_calls==0 && depth_calls==0 && proxy_calls==0 && scale_calls==0 && slot()==1 && handles==0);
    }
    reset(); attrs=INVALID_FILE_ATTRIBUTES; error=5; setter_thread(nullptr);
    assert(depth_calls==0 && proxy_calls==0 && scale_calls==0);
    reset(); attrs=FILE_ATTRIBUTE_DIRECTORY; setter_thread(nullptr); assert(depth_calls==0);
    reset(); open_ok=false; setter_thread(nullptr); assert(depth_calls==0 && handles==0);
    reset(); ini_value=std::wstring(5000,L'x'); setter_thread(nullptr); assert(depth_calls==0 && handles==0);
    reset(); proxy_result=proxy_patch::Result::NoMemory; setter_thread(nullptr);
    assert(depth_calls==1 && proxy_calls==1 && scale_calls==0 && slot()==1);
    reset(); depth_result=depth_patch::Result::NoMemory; setter_thread(nullptr);
    assert(depth_calls==1 && proxy_calls==0 && scale_calls==0 && slot()==1);
    reset(); scale_patch::result=scale_patch::Result::NotDefault; setter_thread(nullptr);
    assert(scale_calls==1 && slot()==1);
    using startup_status::Outcome;using startup_status::Failure;
    startup_status::Snapshot observed;
    assert(startup_observation.read(observed) && observed.outcome==Outcome::NotApplied && observed.failure==Failure::Renderer);
    reset();assert(!startup_observation.read(observed));ini_value=L"Native";setter_thread(nullptr);
    assert(startup_observation.read(observed) && observed.outcome==Outcome::NativeBypass && observed.failure==Failure::None);
    assert(observed.settings_observed && observed.settings.valid && !observed.settings.defaulted && observed.settings.mode==render_settings::Mode::Native);
    reset();ini_value=L"invalid";setter_thread(nullptr);
    assert(startup_observation.read(observed) && observed.outcome==Outcome::NativeBypass && observed.failure==Failure::InvalidConfig);
    assert(observed.settings_observed && !observed.settings.valid && !observed.settings.defaulted);
    reset();attrs=INVALID_FILE_ATTRIBUTES;error=ERROR_FILE_NOT_FOUND;setter_thread(nullptr);
    assert(startup_observation.read(observed) && observed.outcome==Outcome::Custom75Applied && observed.failure==Failure::None);
    assert(observed.settings.valid && observed.settings.defaulted && observed.settings.mode==render_settings::Mode::Custom75);
    reset();depth_result=depth_patch::Result::NoMemory;setter_thread(nullptr);
    assert(startup_observation.read(observed) && observed.outcome==Outcome::NotApplied && observed.failure==Failure::Depth);
    assert(observed.detail==static_cast<std::int32_t>(depth_result) && scale_calls==0);
    reset();proxy_result=proxy_patch::Result::NoMemory;setter_thread(nullptr);
    assert(startup_observation.read(observed) && observed.outcome==Outcome::NotApplied && observed.failure==Failure::Proxy);
    assert(observed.detail==static_cast<std::int32_t>(proxy_result) && scale_calls==0);
    reset();scale_patch::result=scale_patch::Result::NoRenderer;setter_thread(nullptr);
    assert(startup_observation.read(observed) && observed.outcome==Outcome::NotApplied && observed.failure==Failure::Renderer && scale_calls==kPollTries);
    reset();proxy_cave=nullptr;setter_thread(nullptr);
    assert(startup_observation.read(observed) && observed.outcome==Outcome::Incomplete && observed.failure==Failure::MissingGate);
    reset();ini_value=L"Native";start_setter_once();start_setter_once();
    assert(thread_calls==1 && handles==0 && startup_observation.read(observed) && observed.outcome==Outcome::NativeBypass);
    reset();thread_create_ok=false;start_setter_once();start_setter_once();
    assert(thread_calls==1 && handles==0 && startup_observation.read(observed));
    assert(observed.outcome==Outcome::NotStarted && observed.failure==Failure::ThreadCreation && !observed.settings_observed && observed.detail==8);
    std::puts("startup settings integration tests: all passed");
}
'''


class StartupTests(unittest.TestCase):
    def run_cpp(self, source):
        with tempfile.TemporaryDirectory() as td:
            cpp, exe = pathlib.Path(td) / "test.cpp", pathlib.Path(td) / "test"
            cpp.write_text(source)
            p = subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                                "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-I", str(C),
                                str(cpp), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            p = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("all passed", p.stdout)

    def test_proxy_install_failures(self):
        self.run_cpp(COMMON + PROXY + function("apply_proxy_patch") + PROXY_MAIN)

    def test_startup_settings(self):
        self.run_cpp(COMMON + STARTUP + function("read_render_settings") + function("load_render_settings") + function("setter_thread") + function("start_setter_once") + STARTUP_MAIN)


if __name__ == "__main__":
    unittest.main()

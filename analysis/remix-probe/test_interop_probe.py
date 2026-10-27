#!/usr/bin/env python3
"""Frozen gate for interop_probe.h: can an API-only Remix client get the final colour out as pixels?

Usage: test_interop_probe.py <interop_probe.h>

The header holds the interop sequence (`run_interop`) written against a table of calls (`InteropOps`), so a
CPU harness can drive every step with stubs and never touch Remix, a GPU or Wine. This gate compiles that
harness with sanitizers and asserts the properties we rely on when the same sequence is wired to the real
runtime: the call order, which step a failure is attributed to, and that a black frame is never reported as
success. Prints {"passed": true, "checks": [...]}.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HARNESS = r'''
#include <cstdio>
#include <string>
#include <vector>
#include <cstdint>
#include "interop_probe.h"

namespace {
std::vector<std::string> log_;
int calls = 0;
int calls_of(const char* name) { int n = 0; for (auto& s : log_) if (s.rfind(name, 0) == 0) ++n; return n; }
void reset() { log_.clear(); calls = 0; }
int failures = 0;
void check(bool cond, const char* name, const char* detail = "") {
    if (cond) { std::printf("PASS %s\n", name); return; }
    ++failures; std::printf("FAIL %s %s\n", name, detail);
}

// Stub table: every step succeeds unless `fail_at` names it. `vk_handle` is what get_vk_image reports.
struct Stub {
    const char* fail_at = "";
    std::uint64_t vk_handle = 0xCAFE;
    unsigned char* image = nullptr;   // 4-byte BGRA per pixel, filled by the test
    bool missing_readback = false;
};

Stub* g = nullptr;
bool must_fail(const char* step) { return std::string(g->fail_at) == step; }

int s_create_d3d9(void** out) {
    log_.push_back("create_d3d9"); ++calls;
    if (must_fail("create_d3d9")) return 1;
    *out = reinterpret_cast<void*>(0x1000); return 0;
}
int s_create_device(void* d3d9, void** out) {
    (void)d3d9;
    log_.push_back("create_device"); ++calls;
    if (must_fail("create_device")) return 1;
    *out = reinterpret_cast<void*>(0x2000); return 0;
}
int s_create_rt(void* device, unsigned w, unsigned h, void** out) {
    (void)device;
    char buf[64]; std::snprintf(buf, sizeof buf, "create_render_target %u %u", w, h);
    log_.push_back(buf); ++calls;
    if (must_fail("create_render_target")) return 1;
    *out = reinterpret_cast<void*>(0x3000); return 0;
}
int s_create_rb(void* device, unsigned w, unsigned h, void** out) {
    (void)device; (void)w; (void)h;
    log_.push_back("create_readback"); ++calls;
    if (must_fail("create_readback")) return 1;
    *out = reinterpret_cast<void*>(0x4000); return 0;
}
int s_copy(void* surface, int type) {
    (void)surface;
    char buf[64]; std::snprintf(buf, sizeof buf, "copy_output type=%d", type);
    log_.push_back(buf); ++calls;
    if (must_fail("copy_output")) return 1;
    return 0;
}
int s_vk(void* surface, std::uint64_t* out) {
    (void)surface;
    log_.push_back("get_vk_image"); ++calls;
    if (must_fail("get_vk_image")) return 1;
    *out = g->vk_handle; return 0;
}
int s_read(void* rb, unsigned char* dst, unsigned w, unsigned h) {
    (void)rb;
    log_.push_back("read_pixels"); ++calls;
    if (must_fail("read_pixels")) return 1;
    for (unsigned i = 0; i < w * h * 4; ++i) dst[i] = g->image[i];
    return 0;
}

InteropOps ops() {
    InteropOps o{};
    o.create_d3d9 = s_create_d3d9; o.create_device = s_create_device;
    o.create_render_target = s_create_rt; o.create_readback = g->missing_readback ? nullptr : s_create_rb;
    o.copy_output = s_copy; o.get_vk_image = s_vk; o.read_pixels = s_read;
    return o;
}
}  // namespace

int main() {
    const unsigned W = 2, H = 2;
    unsigned char pixels[W * H * 4] = {};
    // One opaque white pixel, three black: nonblack 0.25, mean luma 0.25.
    for (int c = 0; c < 4; ++c) pixels[c] = 255;
    Stub stub; stub.image = pixels; g = &stub;

    // 1. Happy path: order, arguments forwarded, statistics computed.
    reset();
    InteropReport r = run_interop(ops(), W, H, pixels);
    check(r.ok && !r.failed_stage, "happy path succeeds");
    check(log_.size() == 7, "happy path makes exactly seven calls");
    check(!log_.empty() && log_[0] == "create_d3d9", "first call is dxvk_CreateD3D9");
    check(calls_of("create_render_target 2 2") == 1, "render target created at the probe's size");
    check(calls_of("copy_output type=0") == 1, "copy is FINAL_COLOR (0)");
    check(log_.size() > 5 && log_[5] == "get_vk_image", "VkImage is queried after the copy");
    check(r.vk_image == 0xCAFE, "VkImage handle is reported");
    check(r.nonblack_fraction > 0.24 && r.nonblack_fraction < 0.26, "nonblack fraction is 0.25");
    check(r.mean_luma > 0.24 && r.mean_luma < 0.26, "mean luma is 0.25 for one white pixel in four");

    // 2. BGRA order: a pure blue pixel weighs 0.0722, a pure red one 0.2126.
    unsigned char blue[4] = {255, 0, 0, 255};    // B,G,R,A
    stub.image = blue;
    r = run_interop(ops(), 1, 1, blue);
    check(r.ok && r.mean_luma > 0.071 && r.mean_luma < 0.073, "byte order is BGRA (blue weighs 0.0722)");

    // 3. Each step's failure is attributed to that step and stops the sequence.
    const char* stages[] = {"create_d3d9", "create_device", "create_render_target", "create_readback", "copy_output"};
    const char* names[] = {"dxvk_CreateD3D9", "CreateDeviceEx", "CreateRenderTarget",
                           "CreateOffscreenPlainSurface", "dxvk_CopyRenderingOutput(FINAL_COLOR)"};
    for (int i = 0; i < 5; ++i) {
        reset(); stub.image = pixels; stub.fail_at = stages[i];
        r = run_interop(ops(), W, H, pixels);
        char label[96]; std::snprintf(label, sizeof label, "failure at %s is attributed to %s", stages[i], names[i]);
        check(!r.ok && r.failed_stage && std::string(r.failed_stage) == names[i], label, r.failed_stage ? r.failed_stage : "null");
        check(calls == i + 1, "no call happens after the failing step");
    }
    stub.fail_at = "";

    // 4. Readback failure is its own stage, after the copy.
    reset(); stub.fail_at = "read_pixels";
    r = run_interop(ops(), W, H, pixels);
    check(!r.ok && r.failed_stage && std::string(r.failed_stage) == "GetRenderTargetData+LockRect", "readback failure is attributed");
    stub.fail_at = "";

    // 5. A zero VkImage is a finding, not a failure.
    reset(); stub.vk_handle = 0;
    r = run_interop(ops(), W, H, pixels);
    check(r.ok && r.vk_image == 0, "a missing VkImage does not fail the run");
    stub.vk_handle = 0xCAFE;

    // 6. A black copy is a failure: the whole point is to prove pixels came out.
    unsigned char black[W * H * 4] = {};
    reset(); stub.image = black;
    r = run_interop(ops(), W, H, black);
    check(!r.ok && r.nonblack_fraction == 0, "an all-black copy is reported as a failure");

    // 7. An older runtime that zeroes a member must be refused, not crashed on.
    reset(); stub.image = pixels; stub.missing_readback = true;
    r = run_interop(ops(), W, H, pixels);
    check(!r.ok && r.failed_stage && std::string(r.failed_stage) == "CreateOffscreenPlainSurface",
          "a null function pointer is refused cleanly");
    stub.missing_readback = false;

    std::printf("%s\n", failures ? "HARNESS FAILED" : "HARNESS OK");
    return failures ? 1 : 0;
}
'''


def main():
    header = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp(prefix='interop-gate-'))
    checks = []
    try:
        assert header.name == 'interop_probe.h', f'expected interop_probe.h, got {header.name}'
        assert header.exists(), f'{header} does not exist'
        src = work / 'harness.cpp'
        src.write_text(HARNESS)
        exe = work / 'harness'
        build = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                                '-I', str(header.parent), str(src), '-o', str(exe)],
                               capture_output=True, text=True, timeout=600)
        assert build.returncode == 0, f'harness did not compile: {build.stderr[-800:]}'
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        failed = [ln for ln in run.stdout.splitlines() if ln.startswith('FAIL')]
        assert run.returncode == 0 and not failed, 'harness failures: ' + '; '.join(failed or [run.stderr[-400:]])
        assert 'HARNESS OK' in run.stdout, f'harness did not finish: {run.stdout[-400:]}'
        checks = [ln[5:] for ln in run.stdout.splitlines() if ln.startswith('PASS')]
        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()

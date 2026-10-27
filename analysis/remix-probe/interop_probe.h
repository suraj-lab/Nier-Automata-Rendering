// Can an API-only Remix client get the final colour image out as pixels? This is the sequence that
// answers it, written against a table of calls so a CPU gate (test_interop_probe.py) can drive every
// step with stubs. triangle.cpp fills the same table with Remix's dxvk_* members and the D3D9 device
// the runtime hands back; nothing here is Windows- or GPU-specific on purpose.
#pragma once
#include <cstdint>

// Each function returns 0 on success (HRESULT==S_OK in the real build). copy_type is a
// remixapi_dxvk_CopyRenderingOutputType; 0 is FINAL_COLOR, the post-composite image.
struct InteropOps {
    int (*create_d3d9)(void** out_d3d9);
    int (*create_device)(void* d3d9, void** out_device);
    int (*create_render_target)(void* device, unsigned w, unsigned h, void** out_surface);
    int (*create_readback)(void* device, unsigned w, unsigned h, void** out_surface);
    int (*copy_output)(void* surface, int copy_type);
    int (*get_vk_image)(void* surface, std::uint64_t* out_vk_image);
    int (*read_pixels)(void* readback, unsigned char* bgra, unsigned w, unsigned h);
};

struct InteropReport {
    bool ok = false;
    const char* failed_stage = nullptr;  // null when ok; otherwise the step that refused
    std::uint64_t vk_image = 0;          // 0: the runtime exposed no VkImage for our surface
    double mean_luma = 0;
    double nonblack_fraction = 0;
};

// Below this the copy produced no image, and a black frame must never be reported as success.
constexpr double interop_min_nonblack = 0.001;

// `bgra` must hold w*h*4 bytes: the readback surface is D3DFMT_A8R8G8B8, so bytes are B,G,R,A.
inline InteropReport run_interop(const InteropOps& ops, unsigned w, unsigned h, unsigned char* bgra) {
    InteropReport r;
    void* d3d9 = nullptr;
    void* device = nullptr;
    void* target = nullptr;
    void* readback = nullptr;
    if (!ops.create_d3d9 || ops.create_d3d9(&d3d9) || !d3d9) { r.failed_stage = "dxvk_CreateD3D9"; return r; }
    if (!ops.create_device || ops.create_device(d3d9, &device) || !device) { r.failed_stage = "CreateDeviceEx"; return r; }
    if (!ops.create_render_target || ops.create_render_target(device, w, h, &target) || !target) {
        r.failed_stage = "CreateRenderTarget";
        return r;
    }
    if (!ops.create_readback || ops.create_readback(device, w, h, &readback) || !readback) {
        r.failed_stage = "CreateOffscreenPlainSurface";
        return r;
    }
    if (!ops.copy_output || ops.copy_output(target, 0)) { r.failed_stage = "dxvk_CopyRenderingOutput(FINAL_COLOR)"; return r; }
    // A zero handle is a valid finding (the runtime exposed no VkImage), so this step does not fail the run.
    if (ops.get_vk_image) {
        std::uint64_t vk = 0;
        if (!ops.get_vk_image(target, &vk)) r.vk_image = vk;
    }
    if (!ops.read_pixels || ops.read_pixels(readback, bgra, w, h)) { r.failed_stage = "GetRenderTargetData+LockRect"; return r; }
    double sum = 0;
    unsigned long nonblack = 0;
    const unsigned long total = static_cast<unsigned long>(w) * h;
    for (unsigned long i = 0; i < total; ++i) {
        const unsigned char* p = bgra + i * 4;  // B,G,R,A
        const double y = (0.0722 * p[0] + 0.7152 * p[1] + 0.2126 * p[2]) / 255.0;
        sum += y;
        if (y > 1.0 / 255.0) ++nonblack;
    }
    r.mean_luma = total ? sum / static_cast<double>(total) : 0;
    r.nonblack_fraction = total ? static_cast<double>(nonblack) / static_cast<double>(total) : 0;
    if (r.nonblack_fraction < interop_min_nonblack) { r.failed_stage = "copied image is black"; return r; }
    r.ok = true;
    return r;
}

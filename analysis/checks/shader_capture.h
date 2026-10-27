// Hook ID3D11Device::CreatePixelShader so each pixel shader's bytecode can be written out with a capture.
//
// Why: deciding whether a draw is a cutout (foliage, hair, grilles) needs the shader's `discard`, and the
// only authority for that is the code itself. Parsing DXBC opcodes by hand was tried and abandoned on
// 2026-10-27 (see analysis/checks/test_dxbc_discard.py, which pins the vendor disassembler instead), so
// this stores the raw blob and lets analysis/checks/dxbc_disasm.exe answer the question offline.
//
// The blob is filed as `ps_<id>.dxbc`, where id is the pointer identity that draw_capture.h already
// records as `ps_hash` (shader_id() is the pointer value), so an offline tool can join shader to draws
// without any extra index.
//
// Writes only when NIER_SHADER_DIR is set, so a normal game run never litters the game directory.
#include <d3d11.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>
#include "vtable_hook.h"

namespace shader_capture {
using CreatePixelShaderFn = HRESULT (STDMETHODCALLTYPE*)(ID3D11Device*, const void*, SIZE_T,
                                                         const D3D11_CLASS_INSTANCE_DESC*,
                                                         ID3D11PixelShader**);

// ID3D11Device vtable: 0..2 IUnknown, 3..10 the buffer/texture/view creators, 11 CreateInputLayout,
// 12 CreateVertexShader, 13 CreateGeometryShader, 14 CreateGeometryShaderWithStreamOutput,
// 15 CreatePixelShader.
constexpr std::size_t kCreatePixelShader = 15;

inline std::atomic<void*>& next() { static std::atomic<void*> n{nullptr}; return n; }
inline std::mutex& mutex() { static std::mutex m; return m; }
inline std::vector<std::pair<ID3D11PixelShader*, std::vector<unsigned char>>>& store() {
    static std::vector<std::pair<ID3D11PixelShader*, std::vector<unsigned char>>> s;
    return s;
}

inline std::string& dir() { static std::string d; return d; }

inline void ensure_dir() {
    // Default to a directory next to the captures, so a normal launch records bytecode without any launch
    // options. The 2026-10-27 game capture produced 3185 draws but zero blobs because NIER_SHADER_DIR never
    // reached the process; relying on the environment was the mistake, not the hook. NIER_SHADER_DIR still
    // overrides, and setting it to "off" disables the hook entirely.
    std::lock_guard<std::mutex> lock(mutex());
    if (!dir().empty()) return;
    const char* env = std::getenv("NIER_SHADER_DIR");
    if (env && !std::strcmp(env, "off")) return;  // explicitly disabled
    if (env && *env) { dir() = env; }
    else {
        char exe[MAX_PATH]{};
        const DWORD n = GetModuleFileNameA(nullptr, exe, MAX_PATH);
        dir() = std::string(exe, (n && n < MAX_PATH) ? n : 0);
        const std::size_t slash = dir().rfind('\\');
        dir().resize(slash == std::string::npos ? 0 : slash);
        dir() += "\\NIER_CAPTURE\\shaders";
    }
    // create both levels: CreateDirectoryA is not recursive
    const std::size_t cut = dir().find("\\NIER_CAPTURE");
    if (cut != std::string::npos) CreateDirectoryA(dir().substr(0, cut + 13).c_str(), nullptr);
    CreateDirectoryA(dir().c_str(), nullptr);   // exists is fine
}

inline void write_blob(ID3D11PixelShader* ps, const void* bytecode, SIZE_T length) {
    if (dir().empty() || !ps || !bytecode || length < 4) return;
    const auto id = static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(ps));
    char path[MAX_PATH];
    std::snprintf(path, sizeof path, "%s\\ps_%llu.dxbc", dir().c_str(), id);
    if (FILE* f = std::fopen(path, "wb")) {
        std::fwrite(bytecode, 1, length, f);
        std::fclose(f);
    }
}

inline HRESULT STDMETHODCALLTYPE hooked_create_pixel_shader(ID3D11Device* self, const void* bytecode,
                                                            SIZE_T length,
                                                            const D3D11_CLASS_INSTANCE_DESC* inst,
                                                            ID3D11PixelShader** out) {
    const auto fn = reinterpret_cast<CreatePixelShaderFn>(next().load(std::memory_order_acquire));
    const HRESULT hr = fn(self, bytecode, length, inst, out);
    if (SUCCEEDED(hr) && out && *out && bytecode && length) {
        write_blob(*out, bytecode, length);
        std::lock_guard<std::mutex> lock(mutex());
        store().emplace_back(*out, std::vector<unsigned char>(
            static_cast<const unsigned char*>(bytecode), static_cast<const unsigned char*>(bytecode) + length));
    }
    return hr;
}

inline bool protect(void* address, std::size_t size, unsigned long flags, unsigned long* old) {
    DWORD previous = 0;
    const bool ok = VirtualProtect(address, size, static_cast<DWORD>(flags), &previous) != 0;
    if (old) *old = previous;
    return ok;
}

inline bool lookup(ID3D11PixelShader* ps, std::vector<unsigned char>& out) {
    if (!ps) return false;
    std::lock_guard<std::mutex> lock(mutex());
    for (auto& [k, v] : store()) {
        if (k == ps) { out = v; return true; }
    }
    return false;
}

// Install once. Returns true if the hook is chainable (mirrors input_layout_hook::install).
inline bool install(ID3D11Device* device) {
    static bool done = false;
    if (!device || done) return done;
    done = true;
    ensure_dir();
    void** table = *reinterpret_cast<void***>(device);
    const auto r = vtable_hook::hook(table, kCreatePixelShader,
                                     reinterpret_cast<void*>(&hooked_create_pixel_shader), next(), protect);
    return r == vtable_hook::Result::Hooked || r == vtable_hook::Result::AlreadyHooked ||
           r == vtable_hook::Result::RestoreFailed;
}
}  // namespace shader_capture

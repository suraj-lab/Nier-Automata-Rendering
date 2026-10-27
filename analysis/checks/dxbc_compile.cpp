// Compile a few pixel shaders and write their DXBC blobs, so the discard scanner can be tested against
// real compiler output instead of an opcode number taken on faith.
// usage: dxbc_compile.exe <out_dir>
#include <cstdio>
#include <cstring>
#include <windows.h>
#include <d3dcompiler.h>

struct Src { const char* name; const char* code; };

static const Src kShaders[] = {
    {"opaque", "Texture2D t : register(t0); SamplerState s : register(s0);"
               "float4 main(float2 uv : TEXCOORD0) : SV_Target { return t.Sample(s, uv); }"},
    {"cutout", "Texture2D t : register(t0); SamplerState s : register(s0);"
               "float4 main(float2 uv : TEXCOORD0) : SV_Target { float4 c = t.Sample(s, uv);"
               " if (c.a < 0.5) discard; return c; }"},
    // Same shape, but the branch is data-dependent in a different way: two discards in two branches.
    {"cutout2", "Texture2D t : register(t0); SamplerState s : register(s0);"
                "float4 main(float2 uv : TEXCOORD0) : SV_Target { float4 c = t.Sample(s, uv);"
                " if (c.a < 0.25) discard; if (c.a > 0.9) discard; return c; }"},
};

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: dxbc_compile <out_dir>\n"); return 2; }
    CreateDirectoryA(argv[1], nullptr);
    using CompileFn = HRESULT (WINAPI*)(LPCVOID, SIZE_T, LPCSTR, const D3D_SHADER_MACRO*, ID3DInclude*,
                                       LPCSTR, LPCSTR, UINT, UINT, ID3DBlob**, ID3DBlob**);
    HMODULE compiler = LoadLibraryW(L"d3dcompiler_47.dll");
    if (!compiler) { std::fprintf(stderr, "no d3dcompiler_47.dll\n"); return 3; }
    CompileFn compile = nullptr;
    FARPROC proc = GetProcAddress(compiler, "D3DCompile");
    std::memcpy(&compile, &proc, sizeof compile);
    if (!compile) { std::fprintf(stderr, "no D3DCompile\n"); return 3; }
    int written = 0;
    for (const auto& s : kShaders) {
        ID3DBlob* blob = nullptr;
        ID3DBlob* err = nullptr;
        const HRESULT hr = compile(s.code, std::strlen(s.code), nullptr, nullptr, nullptr, "main", "ps_5_0",
                                   D3DCOMPILE_OPTIMIZATION_LEVEL0, 0, &blob, &err);
        if (FAILED(hr) || !blob) {
            std::fprintf(stderr, "compile %s failed: %s\n", s.name,
                         err ? static_cast<const char*>(err->GetBufferPointer()) : "?");
            return 4;
        }
        char path[MAX_PATH];
        std::snprintf(path, sizeof path, "%s\\%s.dxbc", argv[1], s.name);
        FILE* f = std::fopen(path, "wb");
        if (!f) { std::fprintf(stderr, "cannot write %s\n", path); return 5; }
        std::fwrite(blob->GetBufferPointer(), 1, blob->GetBufferSize(), f);
        std::fclose(f);
        std::printf("WROTE %s %zu\n", s.name, static_cast<size_t>(blob->GetBufferSize()));
        ++written;
        blob->Release();
        if (err) err->Release();
    }
    std::printf("OK %d\n", written);
    return 0;
}

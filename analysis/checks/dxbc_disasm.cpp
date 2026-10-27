// Disassemble DXBC blobs with the vendor's own disassembler (d3dcompiler_47!D3DDisassemble) and report
// whether each shader contains a discard.
//
// Why not parse the token stream ourselves: the opcode-length field is not a length for declaration
// opcodes, and a plain token scan matches five different opcode values on the same fixtures (2026-10-27),
// so a hand-written walk would be guesswork. D3DDisassemble is the authoritative decoder and costs one
// CPU-only Wine run per batch.
//
// usage: dxbc_disasm.exe <dir>      -> writes <name>.asm and prints "DISCARD <name> <0|1>"
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <windows.h>
#include <d3dcompiler.h>

using DisasmFn = HRESULT (WINAPI*)(LPCVOID, SIZE_T, UINT, LPCSTR, ID3DBlob**);

static bool read_file(const char* path, std::vector<unsigned char>& out) {
    FILE* f = std::fopen(path, "rb");
    if (!f) return false;
    std::fseek(f, 0, SEEK_END);
    const long n = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    if (n <= 0) { std::fclose(f); return false; }
    out.resize(static_cast<size_t>(n));
    const size_t got = std::fread(out.data(), 1, out.size(), f);
    std::fclose(f);
    return got == out.size();
}

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: dxbc_disasm <dir>\n"); return 2; }
    HMODULE compiler = LoadLibraryW(L"d3dcompiler_47.dll");
    if (!compiler) { std::fprintf(stderr, "no d3dcompiler_47.dll\n"); return 3; }
    FARPROC proc = GetProcAddress(compiler, "D3DDisassemble");
    DisasmFn disassemble = nullptr;
    std::memcpy(&disassemble, &proc, sizeof disassemble);
    if (!disassemble) { std::fprintf(stderr, "no D3DDisassemble\n"); return 3; }

    char pattern[MAX_PATH];
    std::snprintf(pattern, sizeof pattern, "%s\\*.dxbc", argv[1]);
    WIN32_FIND_DATAA fd;
    HANDLE find = FindFirstFileA(pattern, &fd);
    if (find == INVALID_HANDLE_VALUE) { std::fprintf(stderr, "no .dxbc in %s\n", argv[1]); return 4; }
    int examined = 0;
    int with_discard = 0;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        char path[MAX_PATH];
        std::snprintf(path, sizeof path, "%s\\%s", argv[1], fd.cFileName);
        std::vector<unsigned char> blob;
        if (!read_file(path, blob)) { std::fprintf(stderr, "cannot read %s\n", path); return 5; }
        ID3DBlob* text = nullptr;
        if (FAILED(disassemble(blob.data(), blob.size(), 0, nullptr, &text)) || !text) {
            std::fprintf(stderr, "disassemble failed: %s\n", fd.cFileName);
            return 6;
        }
        const char* asm_text = static_cast<const char*>(text->GetBufferPointer());
        const size_t asm_len = text->GetBufferSize();
        std::string name(fd.cFileName);
        const size_t dot = name.rfind('.');
        if (dot != std::string::npos) name.resize(dot);
        char out_path[MAX_PATH];
        std::snprintf(out_path, sizeof out_path, "%s\\%s.asm", argv[1], name.c_str());
        FILE* out = std::fopen(out_path, "wb");
        if (out) { std::fwrite(asm_text, 1, asm_len, out); std::fclose(out); }
        // Match the instruction, not the comment: a shader that never discards can still mention it.
        const bool discards = std::strstr(asm_text, "discard") != nullptr;
        std::printf("DISCARD %s %d\n", name.c_str(), discards ? 1 : 0);
        ++examined;
        with_discard += discards ? 1 : 0;
        text->Release();
    } while (FindNextFileA(find, &fd));
    FindClose(find);
    std::printf("OK examined=%d with_discard=%d\n", examined, with_discard);
    return 0;
}

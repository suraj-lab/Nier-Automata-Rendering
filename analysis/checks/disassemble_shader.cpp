// CPU-only DXBC inspection; no device creation or shader execution.
#include <windows.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <fstream>
#include <vector>

int main(int argc, char** argv)
{
    if (argc != 3) {
        std::fprintf(stderr, "usage: disassemble_shader INPUT.dxbc NEW_OUTPUT.asm\n");
        return 2;
    }
    std::ifstream input(argv[1], std::ios::binary | std::ios::ate);
    const auto size = input.tellg();
    if (!input || size < 32 || size > 16 * 1024 * 1024) {
        std::fprintf(stderr, "invalid or oversized shader input\n");
        return 2;
    }
    std::vector<char> bytes(static_cast<size_t>(size));
    input.seekg(0);
    if (!input.read(bytes.data(), size)) return 2;
    ID3DBlob* text = nullptr;
    const HRESULT hr = D3DDisassemble(bytes.data(), bytes.size(), 0, nullptr, &text);
    if (FAILED(hr) || !text) {
        if (text) text->Release();
        std::fprintf(stderr, "D3DDisassemble failed: 0x%08lX\n", static_cast<unsigned long>(hr));
        return 3;
    }
    const SIZE_T length = text->GetBufferSize();
    if (length > MAXDWORD) { text->Release(); return 3; }
    HANDLE output = CreateFileA(argv[2], GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (output == INVALID_HANDLE_VALUE) {
        std::fprintf(stderr, "cannot create new output: %lu\n", static_cast<unsigned long>(GetLastError()));
        text->Release();
        return 4;
    }
    DWORD written = 0;
    const bool ok = WriteFile(output, text->GetBufferPointer(), static_cast<DWORD>(length), &written, nullptr)
        && written == length;
    const bool closed = CloseHandle(output) != 0;
    text->Release();
    if (!ok || !closed) { std::fprintf(stderr, "output write failed\n"); return 4; }
    std::printf("Disassembled %zu bytes without executing shader\n", bytes.size());
    return 0;
}

// x64 Windows loader-only probe: no D3D device, API initialization, window, or renderer.
#include <windows.h>
#include <cstdio>
#include <cwchar>
#include <cstddef>

static_assert(sizeof(void*) == 8, "this probe must run as x64");
static_assert(offsetof(IMAGE_LOAD_CONFIG_DIRECTORY64, CHPEMetadataPointer) == 200, "SDK load-config layout");

int wmain(int argc, wchar_t** argv) {
    if (argc == 2 && !std::wcscmp(argv[1], L"--self-check")) {
        return GetModuleHandleW(nullptr) && GetModuleHandleW(L"kernel32.dll") ? 0 : 1;
    }
    if (argc != 3 || std::wcscmp(argv[1], L"--load") || std::wcslen(argv[2]) < 3 ||
        argv[2][1] != L':' || (argv[2][2] != L'\\' && argv[2][2] != L'/')) {
        std::fputs("usage: runtime-loader --load C:\\absolute\\d3d9.dll | --self-check\n", stderr);
        return 2;
    }
    const HMODULE dll = LoadLibraryExW(argv[2], nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    const DWORD error = dll ? ERROR_SUCCESS : GetLastError();
    std::printf("loaded=%d win32_error=%lu initialize_export=%d\n", dll ? 1 : 0,
        static_cast<unsigned long>(error), dll && GetProcAddress(dll, "remixapi_InitializeLibrary") ? 1 : 0);
    if (dll) FreeLibrary(dll);
    return dll ? 0 : 1;
}

#define DIRECTINPUT_VERSION 0x0800
#define main fsr_probe_main
#include "fsr_inference_probe.cpp"
#undef main
#include <dinput.h>

int main()
{
    FILE* result = fopen("lod-loader-results.txt", "w");
    if (!result) return 2;
    HMODULE lod = LoadLibraryW(L"dinput8.dll");
    if (!lod)
    {
        fprintf(result, "LOAD FAIL error=%lu\n", GetLastError());
        fclose(result);
        return 1;
    }
    using Create = HRESULT(WINAPI*)(HINSTANCE, DWORD, REFIID, void**, IUnknown*);
    auto create = reinterpret_cast<Create>(GetProcAddress(lod, "DirectInput8Create"));
    if (!create)
    {
        fputs("MISSING DirectInput8Create\n", result);
        fclose(result);
        return 1;
    }
    IDirectInput8W* input = nullptr;
    const HRESULT hr = create(GetModuleHandleW(nullptr), DIRECTINPUT_VERSION,
                              IID_IDirectInput8W, reinterpret_cast<void**>(&input), nullptr);
    fprintf(result, "DirectInput8Create HRESULT=0x%08lX object=%s\n",
            (unsigned long)hr, input ? "present" : "missing");
    if (input) input->Release();
    if (fclose(result) != 0) return 2;
    if (FAILED(hr) || !input) return 1;
    // The non-game executable intentionally does not activate LodMod/FAR game patches.
    return fsr_probe_main();
}

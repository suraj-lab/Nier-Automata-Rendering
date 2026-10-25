#pragma once
// Block the game's mouse input while the in-game panel is open, so the OS cursor is free to reach the
// panel and the game's mouselook stops. Two mechanisms, both gated by `enabled`:
//   1. a WndProc subclass that consumes mouse + WM_INPUT (raw input) messages, and
//   2. an IAT patch of user32.SetCursorPos so the game's per-frame re-centering is a no-op, and
//   3. DirectInput8 GetDeviceState/GetDeviceData vtable hooks (slots 9/10, verified against mingw
//      dinput.h) that zero mouse-device results. NieR reads its camera mouse through DINPUT8, which
//      bypasses window messages, so (1) alone does not stop mouselook.
#ifndef DIRECTINPUT_VERSION
#define DIRECTINPUT_VERSION 0x0800
#endif
#include <windows.h>
#include <dinput.h>
#include <atomic>
#include <cstdint>
#include <cstring>
#include "vtable_hook.h"

namespace input_capture {
inline WNDPROC prev_wndproc = nullptr;
inline bool enabled = false;

using SetCursorPosFn = BOOL (WINAPI*)(int, int);
inline SetCursorPosFn real_set_cursor_pos = nullptr;

inline BOOL WINAPI blocked_set_cursor_pos(int x, int y) {
    if (enabled) return TRUE;  // swallow the game's re-centering while the panel is open
    return real_set_cursor_pos ? real_set_cursor_pos(x, y) : SetCursorPos(x, y);
}

inline LRESULT CALLBACK wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (enabled) {
        switch (msg) {
        case WM_INPUT:      // raw mouse deltas (also keyboard/gamepad, fine to block while the panel is up)
        case WM_MOUSEMOVE:
        case WM_MOUSEWHEEL:
        case WM_MOUSEHWHEEL:
        case WM_LBUTTONDOWN: case WM_LBUTTONUP: case WM_LBUTTONDBLCLK:
        case WM_RBUTTONDOWN: case WM_RBUTTONUP: case WM_RBUTTONDBLCLK:
        case WM_MBUTTONDOWN: case WM_MBUTTONUP: case WM_MBUTTONDBLCLK:
        case WM_XBUTTONDOWN: case WM_XBUTTONUP: case WM_XBUTTONDBLCLK:
        case WM_MOUSEACTIVATE:
            return 0;  // consume: the game never sees it
        }
    }
    return prev_wndproc ? CallWindowProcW(prev_wndproc, hwnd, msg, wp, lp) : DefWindowProcW(hwnd, msg, wp, lp);
}

inline bool protect(void* address, std::size_t size, unsigned long flags, unsigned long* old) {
    DWORD previous = 0;
    const bool ok = VirtualProtect(address, size, static_cast<DWORD>(flags), &previous) != 0;
    if (old) *old = previous;
    return ok;
}

// Patch every loaded module's import of user32.SetCursorPos (by import name) to blocked_set_cursor_pos.
inline bool hook_set_cursor_pos() {
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (!user32) return false;
    FARPROC real = GetProcAddress(user32, "SetCursorPos");
    if (!real) return false;
    std::memcpy(&real_set_cursor_pos, &real, sizeof(real));  // avoid cast-function-type warning
    const std::uintptr_t replacement = reinterpret_cast<std::uintptr_t>(&blocked_set_cursor_pos);

    // PEB -> Ldr -> InLoadOrderModuleList.
    const auto* teb = reinterpret_cast<const unsigned char*>(NtCurrentTeb());
    const auto* peb = *reinterpret_cast<const unsigned char* const*>(teb + 0x60);
    if (!peb) return false;
    const auto* ldr = *reinterpret_cast<const unsigned char* const*>(peb + 0x18);
    if (!ldr) return false;
    const auto* head = reinterpret_cast<const std::uintptr_t*>(ldr + 0x10);  // InLoadOrderModuleList head

    bool patched = false;
    for (auto* link = reinterpret_cast<const std::uintptr_t*>(*head); link != head;
         link = reinterpret_cast<const std::uintptr_t*>(*link)) {
        const auto* entry = reinterpret_cast<const unsigned char*>(link);
        const auto base = *reinterpret_cast<const std::uintptr_t*>(entry + 0x30);  // DllBase
        if (!base) continue;
        const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
        if (dos->e_magic != IMAGE_DOS_SIGNATURE) continue;
        const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
        if (nt->Signature != IMAGE_NT_SIGNATURE) continue;
        const DWORD rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
        if (!rva) continue;
        for (auto* desc = reinterpret_cast<const IMAGE_IMPORT_DESCRIPTOR*>(base + rva); desc->Name; ++desc) {
            const char* dll = reinterpret_cast<const char*>(base + desc->Name);
            if (_stricmp(dll, "user32.dll")) continue;
            auto* iat = reinterpret_cast<std::uintptr_t*>(base + desc->FirstThunk);
            const auto* int_ = reinterpret_cast<const std::uintptr_t*>(
                base + (desc->OriginalFirstThunk ? desc->OriginalFirstThunk : desc->FirstThunk));
            for (unsigned i = 0; iat[i]; ++i) {
                if (int_[i] & IMAGE_ORDINAL_FLAG64) continue;  // imported by ordinal, not name
                const auto* ibn = reinterpret_cast<const IMAGE_IMPORT_BY_NAME*>(base + (int_[i] & ~IMAGE_ORDINAL_FLAG64));
                if (!std::strcmp(ibn->Name, "SetCursorPos") && iat[i] != replacement) {
                    unsigned long old = 0;
                    if (protect(&iat[i], sizeof(std::uintptr_t), PAGE_READWRITE, &old)) {
                        iat[i] = replacement;
                        protect(&iat[i], sizeof(std::uintptr_t), old, &old);
                        patched = true;
                    }
                }
            }
        }
    }
    return patched;
}

// DirectInput: the device vtable lives in dinput8.dll and is shared by every device object of that
// class, so hooking it through a throwaway mouse device also covers the game's existing device.
// Only mouse-type devices are blanked; keyboard and gamepad still reach the game.
inline bool is_mouse(void* device) {
    DIDEVCAPS caps{}; caps.dwSize = sizeof caps;
    using GetCapsFn = HRESULT (STDMETHODCALLTYPE*)(void*, DIDEVCAPS*);
    const auto get_caps = reinterpret_cast<GetCapsFn>((*static_cast<void***>(device))[3]);  // GetCapabilities
    return SUCCEEDED(get_caps(device, &caps)) && GET_DIDEVICE_TYPE(caps.dwDevType) == DI8DEVTYPE_MOUSE;
}

template <int N> struct DiHook {  // one instance per hooked vtable (A and W may differ)
    static inline std::atomic<void*> next_state{nullptr}, next_data{nullptr};
    static HRESULT STDMETHODCALLTYPE get_state(void* self, DWORD size, void* data) {
        using Fn = HRESULT (STDMETHODCALLTYPE*)(void*, DWORD, void*);
        const HRESULT hr = reinterpret_cast<Fn>(next_state.load(std::memory_order_acquire))(self, size, data);
        if (enabled && data && is_mouse(self)) std::memset(data, 0, size);  // no deltas, no buttons
        return hr;
    }
    static HRESULT STDMETHODCALLTYPE get_data(void* self, DWORD object_size, DIDEVICEOBJECTDATA* events,
                                              DWORD* in_out, DWORD flags) {
        using Fn = HRESULT (STDMETHODCALLTYPE*)(void*, DWORD, DIDEVICEOBJECTDATA*, DWORD*, DWORD);
        const HRESULT hr = reinterpret_cast<Fn>(next_data.load(std::memory_order_acquire))(self, object_size, events, in_out, flags);
        if (enabled && in_out && is_mouse(self)) *in_out = 0;  // buffer drained by the real call; report no events
        return hr;
    }
};

template <int N> inline bool hook_dinput_vtable(REFIID iid) {
    HMODULE dinput = LoadLibraryW(L"dinput8.dll");  // kept loaded: the patched vtable lives in it
    if (!dinput) return false;
    using CreateFn = HRESULT (WINAPI*)(HINSTANCE, DWORD, REFIID, void**, IUnknown*);
    CreateFn create = nullptr;
    FARPROC proc = GetProcAddress(dinput, "DirectInput8Create");
    if (!proc) return false;
    std::memcpy(&create, &proc, sizeof proc);
    void* di = nullptr;
    if (FAILED(create(GetModuleHandleW(nullptr), DIRECTINPUT_VERSION, iid, &di, nullptr)) || !di) return false;
    using CreateDeviceFn = HRESULT (STDMETHODCALLTYPE*)(void*, REFGUID, void**, IUnknown*);
    using ReleaseFn = ULONG (STDMETHODCALLTYPE*)(void*);
    void* device = nullptr;
    const bool created = SUCCEEDED(reinterpret_cast<CreateDeviceFn>((*static_cast<void***>(di))[3])(di, GUID_SysMouse, &device, nullptr)) && device;
    bool ok = false;
    if (created) {
        void** vt = *static_cast<void***>(device);
        const auto a = vtable_hook::hook(vt, 9, reinterpret_cast<void*>(&DiHook<N>::get_state), DiHook<N>::next_state, &protect);
        const auto b = vtable_hook::hook(vt, 10, reinterpret_cast<void*>(&DiHook<N>::get_data), DiHook<N>::next_data, &protect);
        ok = (a == vtable_hook::Result::Hooked || a == vtable_hook::Result::AlreadyHooked) &&
             (b == vtable_hook::Result::Hooked || b == vtable_hook::Result::AlreadyHooked);
        reinterpret_cast<ReleaseFn>((*static_cast<void***>(device))[2])(device);
    }
    reinterpret_cast<ReleaseFn>((*static_cast<void***>(di))[2])(di);
    return ok;
}

inline bool hook_dinput() {
    const bool w = hook_dinput_vtable<0>(IID_IDirectInput8W);
    const bool a = hook_dinput_vtable<1>(IID_IDirectInput8A);
    return w || a;
}

// Install the WndProc subclass (call AFTER the ImGui backend has initialized, so it chains to ImGui).
inline bool install(HWND window) {  // returns whether the DirectInput mouse hook is in place
    if (!window || prev_wndproc) return false;
    prev_wndproc = reinterpret_cast<WNDPROC>(SetWindowLongPtrW(window, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(&wndproc)));
    hook_set_cursor_pos();
    return hook_dinput();
}
}  // namespace input_capture

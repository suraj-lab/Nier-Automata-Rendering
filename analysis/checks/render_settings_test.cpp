// Frozen gate for render_settings.h. Pure startup selection; no Win32 IO or live patches.
// Build: g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined
//        -fno-sanitize-recover=all render_settings_test.cpp -o render_settings_test
#include "render_settings.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <string_view>

int main()
{
    using namespace render_settings;
    // Missing file preserves the deployed v4 behaviour; missing key is NOT a missing file.
    const auto def = select(ReadState::Missing, L"");
    assert(def.mode == Mode::Custom75 && def.valid && def.defaulted);
    assert(scale(def.mode) == 0.75f);
    assert(name(def.mode) == std::wstring_view(L"Custom75"));

    for (const auto text : {L"Custom75", L"custom75", L"CUSTOM75", L" \tCustom75\r\n"}) {
        const auto s = select(ReadState::Value, text);
        assert(s.mode == Mode::Custom75 && s.valid && !s.defaulted && scale(s.mode) == 0.75f);
    }
    for (const auto text : {L"Native", L"native", L"NATIVE", L"\r\nNative \t"}) {
        const auto s = select(ReadState::Value, text);
        assert(s.mode == Mode::Native && s.valid && !s.defaulted && scale(s.mode) == 1.0f);
        assert(name(s.mode) == std::wstring_view(L"Native"));
    }
    // No unvalidated presets, arbitrary floats, inline comments, prefixes or embedded NUL suffixes.
    for (const auto text : {L"", L" \t\r\n", L"Quality", L"Balanced", L"Performance", L"UltraPerformance",
                            L"0.75", L"75%", L"NaN", L"inf", L"-1", L"NativeExtra", L"Custom750",
                            L"Custom75;comment", L"Custom75 # comment", L"\uFF2Eative"}) {
        const auto s = select(ReadState::Value, text);
        assert(s.mode == Mode::Native && !s.valid && !s.defaulted);
    }
    constexpr wchar_t nul_value[] = L"Native\0Custom75";
    const auto nul = select(ReadState::Value, std::wstring_view(nul_value, sizeof(nul_value) / sizeof(wchar_t) - 1));
    assert(nul.mode == Mode::Native && !nul.valid);
    // File-open/IO/truncation errors -> Native, not the missing-file compatibility default.
    const auto err = select(ReadState::Unreadable, L"Custom75");
    assert(err.mode == Mode::Native && !err.valid && !err.defaulted);

    // Platform-independent scales are finite and only Native skips the reduced-scale path.
    for (const auto m : {Mode::Native, Mode::Custom75}) {
        assert(std::isfinite(scale(m)) && scale(m) > 0.25f && scale(m) <= 1.0f);
    }
    std::puts("render_settings_test: all passed");
}

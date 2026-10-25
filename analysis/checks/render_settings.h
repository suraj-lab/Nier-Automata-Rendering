// Pure render-settings selection; no Win32 IO, no allocations.
// Frozen contract: analysis/checks/render_settings_test.cpp.
#pragma once
#include <cstddef>
#include <string_view>

namespace render_settings {

enum class Mode { Native, Custom75 };
enum class ReadState { Missing, Value, Unreadable };

struct Settings {
    Mode mode;
    bool valid;
    bool defaulted;
};

inline Settings select(ReadState state, std::wstring_view value)
{
    // Missing file preserves the deployed v4 (0.75) install; IO errors never fall back to it.
    if (state == ReadState::Missing) return {Mode::Custom75, true, true};
    if (state != ReadState::Value) return {Mode::Native, false, false};

    auto is_ws = [](wchar_t c) { return c == L' ' || c == L'\t' || c == L'\r' || c == L'\n'; };
    std::size_t b = 0, e = value.size();
    while (b < e && is_ws(value[b])) ++b;
    while (e > b && is_ws(value[e - 1])) --e;

    // ASCII case-insensitive exact match; Unicode lookalikes and embedded NUL suffixes fail.
    auto matches = [&](const wchar_t* target) {
        const std::size_t n = e - b;
        if (n != std::char_traits<wchar_t>::length(target)) return false;
        for (std::size_t i = 0; i < n; ++i) {
            wchar_t c = value[b + i];
            if (c >= L'A' && c <= L'Z') c = static_cast<wchar_t>(c + (L'a' - L'A'));
            if (c != target[i]) return false;
        }
        return true;
    };
    if (matches(L"native")) return {Mode::Native, true, false};
    if (matches(L"custom75")) return {Mode::Custom75, true, false};
    return {Mode::Native, false, false};
}

inline float scale(Mode mode) { return mode == Mode::Native ? 1.0f : 0.75f; }

inline std::wstring_view name(Mode mode) { return mode == Mode::Native ? L"Native" : L"Custom75"; }

}  // namespace render_settings

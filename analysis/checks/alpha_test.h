#pragma once
// Alpha test from a pixel shader's own disassembly.
//
// NieR draws foliage, grass cards, decals and grilles with an alpha TEST (the pixel shader discards; blending is off),
// so the blend-state rule (ALPHA_BLEND_TO_CUTOUT) never sees them and Remix renders the whole card: fields of vertical
// streaks (2026-10-29 capture frame_23275488: 123 of 553 scene draws, 11 of 23 pixel shaders). In every case read, the
// test is on the alpha of the slot-0 texture, i.e. the albedo Remix already samples:
//     sample_indexable(texture2d) r0.x, r0.xyxx, t0.wxyz, s0  /  lt r0.x, r0.x, l(8.00000012e-01)  /  discard_nz r0.x
// The comparison and threshold are taken from the shader, then expressed as Remix's AlphaTestType (the condition under
// which the texel is KEPT) and an 8-bit reference. The text is d3dcompiler_47!D3DDisassemble's: the vendor decoder is the
// authority (hand-parsing DXBC tokens was tried and abandoned, see test_dxbc_discard.py).
// Gate: test_alpha_test_parse.py.
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

namespace alpha_test {

// Remix AlphaTestType (rtx_materials.h): the condition under which a texel is kept.
enum Op : int { kNever = 0, kLess = 1, kEqual = 2, kLessOrEqual = 3, kGreater = 4, kNotEqual = 5, kGreaterOrEqual = 6, kAlways = 7 };

struct Result {
    bool discards = false;   // the shader contains a discard
    bool parsed = false;     // the comparison feeding it was understood; false -> default cutout below
    int op = kAlways;        // Remix AlphaTestType: keep the texel when alpha <op> reference
    std::uint8_t reference = 0;
};

namespace detail {
inline std::string trim(const std::string& s) {
    const auto a = s.find_first_not_of(" \t\r");
    const auto b = s.find_last_not_of(" \t\r");
    return a == std::string::npos ? std::string() : s.substr(a, b - a + 1);
}
inline std::vector<std::string> split_operands(const std::string& s) {  // commas inside l(...) are not separators
    std::vector<std::string> out;
    std::string cur;
    int depth = 0;
    for (char c : s) {
        if (c == '(') ++depth;
        if (c == ')') --depth;
        if (c == ',' && depth == 0) { out.push_back(trim(cur)); cur.clear(); continue; }
        cur += c;
    }
    if (!trim(cur).empty()) out.push_back(trim(cur));
    return out;
}
inline bool literal(const std::string& operand, float& value) {  // "l(8.00000012e-01)" (one component)
    if (operand.rfind("l(", 0) != 0 || operand.find(',') != std::string::npos) return false;
    char* end = nullptr;
    value = std::strtof(operand.c_str() + 2, &end);
    return end && *end == ')';
}
}  // namespace detail

// Default when a discard exists but its comparison is not understood: keep alpha > 0.5, the common cutout.
inline Result fallback() { Result r; r.discards = true; r.op = kGreater; r.reference = 127; return r; }

inline Result parse(const std::string& text) {
    std::vector<std::string> lines;
    for (std::size_t start = 0; start < text.size();) {
        std::size_t end = text.find('\n', start);
        if (end == std::string::npos) end = text.size();
        lines.push_back(detail::trim(text.substr(start, end - start)));
        start = end + 1;
    }
    // The last discard decides (NieR's shaders have one; several would all have to agree for a single material).
    int at = -1;
    for (int i = static_cast<int>(lines.size()) - 1; i >= 0 && at < 0; --i)
        if (lines[i].rfind("discard_nz ", 0) == 0 || lines[i].rfind("discard_z ", 0) == 0) at = i;
    Result r;
    if (at < 0) return r;  // opaque
    bool when_nonzero = lines[at].rfind("discard_nz ", 0) == 0;
    std::string reg = detail::trim(lines[at].substr(when_nonzero ? 11 : 10));  // e.g. "r0.x"
    if (reg.rfind("l(", 0) == 0) {
        // Unconditional discard inside "if_nz rN.c" / "if_z rN.c" (real: eq r3.x, r1.w, l(0) / if_nz r3.x /
        // discard_nz l(4294967295)): the if's register and polarity are the test.
        int cond_line = -1;
        for (int i = at - 1; i >= 0 && cond_line < 0; --i)
            if (lines[i].rfind("if_nz ", 0) == 0 || lines[i].rfind("if_z ", 0) == 0) cond_line = i;
        if (cond_line < 0) return fallback();
        when_nonzero = lines[cond_line].rfind("if_nz ", 0) == 0;
        reg = detail::trim(lines[cond_line].substr(when_nonzero ? 6 : 5));
        at = cond_line;
    }
    for (int i = at - 1; i >= 0; --i) {
        const std::string& l = lines[i];
        const auto space = l.find(' ');
        if (space == std::string::npos) continue;
        const std::vector<std::string> ops = detail::split_operands(l.substr(space + 1));
        if (ops.empty() || ops[0] != reg) continue;  // the instruction that last wrote the tested register
        const std::string name = l.substr(0, space);
        if ((name != "lt" && name != "ge" && name != "eq" && name != "ne") || ops.size() != 3) return fallback();
        float t = 0.f;
        bool literal_first = false;
        if (detail::literal(ops[2], t)) literal_first = false;
        else if (detail::literal(ops[1], t)) literal_first = true;
        else return fallback();
        // cond = (x < y) for lt, (x >= y) for ge; alpha is the non-literal operand.
        // "alpha < t" | "t < alpha" (= alpha > t) | "alpha >= t" | "t >= alpha" (= alpha <= t)
        int cond;
        if (name == "lt") cond = literal_first ? kGreater : kLess;
        else if (name == "ge") cond = literal_first ? kLessOrEqual : kGreaterOrEqual;
        else cond = name == "eq" ? kEqual : kNotEqual;  // symmetric: operand order does not matter
        // discard_nz discards when cond holds, so the kept texels satisfy its negation; discard_z keeps cond.
        int keep = cond;
        if (when_nonzero) {
            switch (cond) {
                case kLess: keep = kGreaterOrEqual; break;
                case kGreater: keep = kLessOrEqual; break;
                case kGreaterOrEqual: keep = kLess; break;
                case kLessOrEqual: keep = kGreater; break;
                case kEqual: keep = kNotEqual; break;
                case kNotEqual: keep = kEqual; break;
            }
        }
        r.discards = true;
        r.parsed = true;
        r.op = keep;
        const float scaled = std::round(std::fmin(std::fmax(t, 0.f), 1.f) * 255.f);
        r.reference = static_cast<std::uint8_t>(scaled);
        return r;
    }
    return fallback();
}

}  // namespace alpha_test

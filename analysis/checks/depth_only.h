// Is a pixel shader a depth pass rather than a surface? (item L7, PLAN_2026-11-13)
//
// NieR draws many objects a second time into the scene target with a shader that writes linear depth: it divides the
// interpolated clip z by w, linearises with the projection constants and writes that scalar to o0, sampling a texture at
// most for an alpha cut (runtime/l5-disasm/in/ps_1539331920.asm, ps_1539331648.asm). Submitted, such a draw is a second
// shell over the real surface with no material of its own (10.2% of the camp's surface triangles). Every one of them has
// a full surface twin in the same frame on every capture (test_depth_only.py checks that on the real captures).
//
// The signature, read from the disassembly (the same text alpha_test.h and material_roles.h read):
//   1. no texture sample reaches any output (component-level taint through the instruction stream), and
//   2. the shader divides an interpolated z by the same register's w: div[_sat] rX.c, vN.z, vN.w.
// (2) is what keeps flat-colour unlit surfaces (no sample, constant or vertex colour) out of this class.
#pragma once
#include <array>
#include <cctype>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace depth_only {
namespace detail {

// Split operands at top-level commas: l(1.0, 2.0, ...) keeps its commas.
inline std::vector<std::string> operands(const std::string& rest) {
    std::vector<std::string> out;
    std::string cur;
    int depth = 0;
    for (const char c : rest) {
        if (c == '(' || c == '[') ++depth;
        if (c == ')' || c == ']') --depth;
        if (c == ',' && depth == 0) { out.push_back(cur); cur.clear(); continue; }
        cur += c;
    }
    out.push_back(cur);
    for (auto& o : out) {
        std::size_t a = 0, b = o.size();
        while (a < b && std::isspace(static_cast<unsigned char>(o[a]))) ++a;
        while (b > a && std::isspace(static_cast<unsigned char>(o[b - 1]))) --b;
        o = o.substr(a, b - a);
    }
    return out;
}

// "-|r0.xy|" -> register "r0", components "xy" ("" = all four). Literals, constant buffers, resources: register "".
struct Ref { std::string reg; std::string comps; };
inline Ref ref_of(std::string o) {
    while (!o.empty() && (o[0] == '-' || o[0] == '|')) o.erase(0, 1);
    while (!o.empty() && o.back() == '|') o.pop_back();
    if (o.empty() || !(o[0] == 'r' || o[0] == 'o' || o[0] == 'v' || o[0] == 'x')) return {};
    std::size_t i = 1;
    while (i < o.size() && std::isdigit(static_cast<unsigned char>(o[i]))) ++i;
    if (i == 1) return {};   // "ret" and friends never reach here, but a bare letter is not a register
    Ref r{o.substr(0, i), ""};
    if (o[0] == 'x') {       // x0[r1.x + 2].xy: indexable temp, the index does not matter for taint
        const std::size_t close = o.find(']');
        if (close != std::string::npos) i = close + 1;
    }
    if (i < o.size() && o[i] == '.') r.comps = o.substr(i + 1);
    return r;
}

inline int lane(char c) { return c == 'x' ? 0 : c == 'y' ? 1 : c == 'z' ? 2 : c == 'w' ? 3 : -1; }

}  // namespace detail

inline bool writes_depth_only(const std::string& asm_text) {
    using namespace detail;
    // Two taints per register component: `sampled` (derived from a texture sample) and `zw` (derived from vN.z / vN.w).
    // A depth pass writes zw-derived values and nothing sampled; the zw value must reach the output (review F1).
    std::map<std::string, std::array<bool, 4>> sampled, zw;
    std::vector<bool> branch_sampled;   // if/else nesting: is the condition sample-derived? (review F2)
    bool output_sampled = false, output_zw = false, output_written = false;
    const auto any = [](const std::map<std::string, std::array<bool, 4>>& taint, const Ref& r) {
        const auto it = taint.find(r.reg);
        if (it == taint.end()) return false;
        const std::string comps = r.comps.empty() ? "xyzw" : r.comps;
        for (const char c : comps) if (lane(c) >= 0 && it->second[static_cast<std::size_t>(lane(c))]) return true;
        return false;
    };
    std::istringstream lines(asm_text);
    std::string line;
    while (std::getline(lines, line)) {
        std::size_t a = 0;
        while (a < line.size() && std::isspace(static_cast<unsigned char>(line[a]))) ++a;
        line = line.substr(a);
        while (!line.empty() && (line.back() == '\r' || line.back() == '\0' || std::isspace(static_cast<unsigned char>(line.back()))))
            line.pop_back();
        if (line.empty() || line.rfind("//", 0) == 0 || line.rfind("dcl_", 0) == 0 || line.rfind("ps_", 0) == 0) continue;
        std::size_t space = 0;
        int depth = 0;
        for (; space < line.size(); ++space) {
            if (line[space] == '(') ++depth;
            if (line[space] == ')') --depth;
            if (depth == 0 && std::isspace(static_cast<unsigned char>(line[space]))) break;
        }
        const std::string op = line.substr(0, space);
        if (op == "endif") { if (!branch_sampled.empty()) branch_sampled.pop_back(); continue; }
        if (space >= line.size()) continue;   // ret, else, loop...: no operands
        const std::vector<std::string> ops = operands(line.substr(space + 1));
        if (op.rfind("if", 0) == 0) {   // if_nz / if_z: a sample-derived condition taints everything it guards
            branch_sampled.push_back(!ops.empty() && any(sampled, ref_of(ops[0])));
            continue;
        }
        const bool no_dst = op.rfind("discard", 0) == 0 || op.rfind("break", 0) == 0 || op.rfind("continue", 0) == 0 ||
                            op.rfind("ret", 0) == 0 || op.rfind("switch", 0) == 0 || op.rfind("case", 0) == 0 ||
                            op.rfind("call", 0) == 0;
        if (no_dst || ops.empty()) continue;
        const std::string base = op.substr(0, op.find('('));
        const std::size_t dsts = (base == "sincos" || base == "udiv" || base == "imul" || base == "umul") ? 2 : 1;
        if (ops.size() <= dsts) continue;
        const bool sample = base.rfind("sample", 0) == 0 || base.rfind("ld", 0) == 0 || base.rfind("gather", 0) == 0;
        bool src_sampled = sample;
        for (const bool b : branch_sampled) src_sampled = src_sampled || b;
        bool src_zw = false;
        for (std::size_t k = dsts; k < ops.size(); ++k) {
            const Ref r = ref_of(ops[k]);
            if (r.reg.empty() || r.reg[0] == 'v') continue;
            src_sampled = src_sampled || any(sampled, r);
            src_zw = src_zw || any(zw, r);
        }
        if ((base == "div" || base == "div_sat") && ops.size() == 3) {
            const Ref num = ref_of(ops[1]), den = ref_of(ops[2]);
            if (!num.reg.empty() && num.reg[0] == 'v' && num.reg == den.reg && num.comps == "z" && den.comps == "w")
                src_zw = true;
        }
        for (std::size_t k = 0; k < dsts; ++k) {
            const Ref d = ref_of(ops[k]);
            if (d.reg.empty()) continue;
            if (d.reg[0] == 'o') {
                output_written = true;
                output_sampled = output_sampled || src_sampled;
                output_zw = output_zw || src_zw;
                continue;
            }
            // An indexable temp x#[...] may be written at an index we cannot resolve: merge, never overwrite (F3).
            const bool weak = d.reg[0] == 'x';
            auto& ts = sampled[d.reg];
            auto& tz = zw[d.reg];
            const std::string comps = d.comps.empty() ? "xyzw" : d.comps;
            for (const char c : comps) {
                const int l = lane(c);
                if (l < 0) continue;
                const auto i = static_cast<std::size_t>(l);
                ts[i] = weak ? (ts[i] || src_sampled) : src_sampled;
                tz[i] = weak ? (tz[i] || src_zw) : src_zw;
            }
        }
    }
    return output_written && !output_sampled && output_zw;
}

}  // namespace depth_only

#pragma once

// C++17 port of analysis/checks/pbr_trace.py roles(): which texture channel is albedo, metalness, gloss, normal and
// detail normal, read from one pixel shader's D3DDisassemble text. Keep the two in step.

#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace material_roles {

struct Channel { int slot = -1; std::string channels; bool invert = false; };  // slot -1: role not found
struct Roles { Channel albedo, metal, gloss, normal, detail_normal; };

namespace detail {

inline const std::string kLanes = "xyzw";

// Python str.strip() whitespace.
inline bool is_space(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f' || (c >= '\x1c' && c <= '\x1f');
}

// The separators str.splitlines() breaks on.
inline bool is_line_break(char c) {
    return c == '\n' || c == '\r' || c == '\v' || c == '\f' || c == '\x1c' || c == '\x1d' || c == '\x1e';
}

inline std::string strip(const std::string& s) {
    std::size_t b = 0, e = s.size();
    while (b < e && is_space(s[b])) ++b;
    while (e > b && is_space(s[e - 1])) --e;
    return s.substr(b, e - b);
}

inline bool starts_with(const std::string& s, const std::string& prefix) {
    return s.compare(0, prefix.size(), prefix) == 0;
}

inline bool is_digit(char c) { return c >= '0' && c <= '9'; }

inline bool is_lane(char c) { return kLanes.find(c) != std::string::npos; }

// Register numbers and texture slots compare as integers, so "r07" and "r7" are the same register.
inline std::string strip_zeros(const std::string& digits) {
    const std::size_t k = digits.find_first_not_of('0');
    return k == std::string::npos ? "0" : digits.substr(k);
}

inline char lower_char(char c) {
    return c >= 'A' && c <= 'Z' ? static_cast<char>(c - 'A' + 'a') : c;
}

inline std::string lower(std::string s) {
    for (char& c : s) c = lower_char(c);
    return s;
}

// Python str.split(',') at parenthesis depth 0, each piece stripped; a trailing empty piece is dropped.
inline std::vector<std::string> split_operands(const std::string& text) {
    std::vector<std::string> out;
    int depth = 0;
    std::string cur;
    for (const char ch : text) {
        if (ch == '(') ++depth;
        else if (ch == ')') --depth;
        if (ch == ',' && depth == 0) {
            out.push_back(strip(cur));
            cur.clear();
        } else {
            cur += ch;
        }
    }
    if (!strip(cur).empty()) out.push_back(strip(cur));
    return out;
}

struct Instruction {
    std::string op;
    std::vector<std::string> operands;
};

inline std::vector<Instruction> instructions(const std::string& disassembly) {
    std::vector<Instruction> out;
    std::size_t begin = 0;
    while (begin <= disassembly.size()) {
        std::size_t end = begin;
        while (end < disassembly.size() && !is_line_break(disassembly[end])) ++end;
        std::string line = disassembly.substr(begin, end - begin);
        begin = end + 1;

        const std::size_t comment = line.find("//");
        if (comment != std::string::npos) line.erase(comment);
        line = strip(line);
        if (line.empty() || starts_with(line, "dcl_") || starts_with(line, "ps_") || starts_with(line, "vs_") ||
            line == "ret") {
            continue;
        }
        std::size_t word_end = 0;
        while (word_end < line.size() && !is_space(line[word_end])) ++word_end;
        const std::string word = line.substr(0, word_end);
        const std::size_t paren = word.find('(');  // sample_indexable(texture2d) -> sample_indexable
        out.push_back(Instruction{word.substr(0, paren), split_operands(strip(line.substr(word_end)))});
    }
    return out;
}

inline bool is_open(const std::string& op) {
    static const std::set<std::string> ops = {"if_nz", "if_z", "loop", "switch"};
    return ops.count(op) != 0;
}

inline bool is_close(const std::string& op) {
    static const std::set<std::string> ops = {"endif", "endloop", "endswitch"};
    return ops.count(op) != 0;
}

inline bool is_no_dest(const std::string& op) {
    static const std::set<std::string> ops = {
        "if_nz", "if_z", "loop", "switch", "endif", "endloop", "endswitch", "else", "discard_nz", "discard_z",
        "breakc_nz", "breakc_z", "break", "continue", "continuec_nz", "continuec_z", "case", "default", "retc_nz",
        "retc_z"};
    return ops.count(op) != 0;
}

// ^(-?)(\|?)([rvo])(\d+)\.([xyzw]+)\|?$
struct Register {
    char kind = 'r';
    std::string number;
    std::string swizzle;
};

inline bool parse_register(const std::string& s, Register& out) {
    std::size_t i = 0;
    const std::size_t n = s.size();
    if (i < n && s[i] == '-') ++i;
    if (i < n && s[i] == '|') ++i;
    if (i >= n || (s[i] != 'r' && s[i] != 'v' && s[i] != 'o')) return false;
    out.kind = s[i++];
    const std::size_t number_begin = i;
    while (i < n && is_digit(s[i])) ++i;
    if (i == number_begin || i >= n || s[i] != '.') return false;
    out.number = strip_zeros(s.substr(number_begin, i - number_begin));
    ++i;
    const std::size_t lanes_begin = i;
    while (i < n && is_lane(s[i])) ++i;
    if (i == lanes_begin) return false;
    out.swizzle = s.substr(lanes_begin, i - lanes_begin);
    if (i < n && s[i] == '|') ++i;
    return i == n;
}

// ^t(\d+)\.([xyzw]{4})$ ; slot is -1 when the texture is not one of the material slots 0..7.
struct TextureOperand {
    int slot = -1;
    std::string swizzle;
};

inline bool parse_texture(const std::string& s, TextureOperand& out) {
    if (s.size() < 7 || s[0] != 't') return false;
    std::size_t i = 1;
    while (i < s.size() && is_digit(s[i])) ++i;
    if (i == 1 || i >= s.size() || s[i] != '.') return false;
    const std::string swizzle = s.substr(i + 1);
    if (swizzle.size() != 4) return false;
    for (const char c : swizzle) {
        if (!is_lane(c)) return false;
    }
    const std::string number = strip_zeros(s.substr(1, i - 1));
    out.slot = (number.size() == 1 && number[0] >= '0' && number[0] <= '7') ? number[0] - '0' : -1;
    out.swizzle = swizzle;
    return true;
}

// Python float(text) for the literal forms in disassembly; empty where Python raises ValueError.
inline std::optional<double> py_float(const std::string& text) {
    const std::size_t sign = (!text.empty() && (text[0] == '+' || text[0] == '-')) ? 1 : 0;
    const std::string word = lower(text.substr(sign));
    if (word == "inf" || word == "infinity") {
        const double inf = std::numeric_limits<double>::infinity();
        return sign == 1 && text[0] == '-' ? -inf : inf;
    }
    if (word == "nan") return std::numeric_limits<double>::quiet_NaN();

    std::size_t j = sign, mantissa = 0;
    while (j < text.size() && is_digit(text[j])) { ++j; ++mantissa; }
    if (j < text.size() && text[j] == '.') {
        ++j;
        while (j < text.size() && is_digit(text[j])) { ++j; ++mantissa; }
    }
    if (mantissa == 0) return std::nullopt;
    if (j < text.size() && (text[j] == 'e' || text[j] == 'E')) {
        ++j;
        if (j < text.size() && (text[j] == '+' || text[j] == '-')) ++j;
        std::size_t exponent = 0;
        while (j < text.size() && is_digit(text[j])) { ++j; ++exponent; }
        if (exponent == 0) return std::nullopt;
    }
    if (j != text.size()) return std::nullopt;
    return std::strtod(text.c_str(), nullptr);
}

// Python int(text, 0) for 0x / 0o / 0b literals, which float() rejects (e.g. l(0x80000000)).
inline std::optional<double> py_prefixed_int(const std::string& text) {
    const std::size_t sign = (!text.empty() && (text[0] == '+' || text[0] == '-')) ? 1 : 0;
    if (text.size() < sign + 3 || text[sign] != '0') return std::nullopt;
    const char prefix = lower_char(text[sign + 1]);
    int base = 0;
    if (prefix == 'x') base = 16;
    else if (prefix == 'o') base = 8;
    else if (prefix == 'b') base = 2;
    if (base == 0) return std::nullopt;
    double value = 0;
    for (std::size_t j = sign + 2; j < text.size(); ++j) {
        const char c = lower_char(text[j]);
        int digit = -1;
        if (is_digit(c)) digit = c - '0';
        else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
        if (digit < 0 || digit >= base) return std::nullopt;
        value = value * base + digit;
    }
    return sign == 1 && text[0] == '-' ? -value : value;
}

// l(a, b, ...) with each item a float or prefixed integer; empty when the operand is not a literal.
inline std::optional<std::vector<double>> literal(const std::string& text) {
    if (text.size() < 3 || text.compare(0, 2, "l(") != 0 || text.back() != ')') return std::nullopt;
    const std::string body = text.substr(2, text.size() - 3);
    std::vector<double> out;
    std::size_t start = 0;
    while (true) {
        const std::size_t comma = body.find(',', start);
        const std::string item =
            strip(body.substr(start, comma == std::string::npos ? std::string::npos : comma - start));
        std::optional<double> value = py_float(item);
        if (!value) value = py_prefixed_int(item);
        if (!value) return std::nullopt;
        out.push_back(*value);
        if (comma == std::string::npos) return out;
        start = comma + 1;
    }
}

using Literal = std::optional<std::vector<double>>;

inline bool has_values(const Literal& l) { return l && !l->empty(); }

using SlotChannel = std::pair<int, char>;
using Provenance = std::set<SlotChannel>;  // the (texture slot, channel) pairs a component was computed from
using RegisterLane = std::tuple<char, std::string, char>;  // register kind, register number, lane

inline void merge(Provenance& into, const Provenance& from) { into.insert(from.begin(), from.end()); }

struct Found {
    std::set<Provenance> metal, albedo, gloss, normal, detail, cutout;
};

class Tracer {
public:
    Found found;

    void run(const std::string& disassembly);

private:
    std::map<RegisterLane, Provenance> prov_;

    Provenance sources(const std::string& operand, const std::string& lanes) const;
};

// Provenance of each lane a source operand feeds into the destination lanes.
inline Provenance Tracer::sources(const std::string& operand, const std::string& lanes) const {
    Register reg;
    Provenance out;
    if (!parse_register(operand, reg)) return out;
    for (const char lane : lanes) {
        const std::size_t index = kLanes.find(lane);
        const char source_lane = reg.swizzle[index < reg.swizzle.size() ? index : reg.swizzle.size() - 1];
        const auto it = prov_.find(RegisterLane{reg.kind, reg.number, source_lane});
        if (it != prov_.end()) merge(out, it->second);
    }
    return out;
}

inline bool is_metal_f0(const std::vector<double>& values) {
    for (std::size_t k = 0; k < values.size() && k < 3; ++k) {
        if (std::fabs(values[k] - 0.03) < 1e-6 || std::fabs(values[k] - 0.08) < 1e-6) return true;
    }
    return false;
}

inline void Tracer::run(const std::string& disassembly) {
    int depth = 0;
    for (const Instruction& ins : instructions(disassembly)) {
        const std::string& op = ins.op;
        const std::vector<std::string>& ops = ins.operands;
        if (is_open(op)) ++depth;
        else if (is_close(op)) depth = depth > 0 ? depth - 1 : 0;
        Register dst;
        if (is_no_dest(op) || ops.empty() || !parse_register(ops[0], dst)) continue;

        const std::vector<std::string> srcs(ops.begin() + 1, ops.end());
        const std::size_t n = srcs.size();

        // Value each destination lane takes, from the provenance before this write.
        std::map<char, Provenance> fresh;
        if (op.compare(0, 6, "sample") == 0 || op.compare(0, 2, "ld") == 0) {
            TextureOperand tex;
            bool has_tex = false;
            for (const std::string& s : srcs) {
                if (parse_texture(s, tex)) {
                    has_tex = true;
                    break;
                }
            }
            for (const char lane : dst.swizzle) {
                if (has_tex && tex.slot >= 0) {
                    fresh[lane] = Provenance{SlotChannel{tex.slot, tex.swizzle[kLanes.find(lane)]}};
                } else {
                    fresh[lane] = Provenance{};
                }
            }
        } else if (op == "dp2" || op == "dp3" || op == "dp4") {
            const std::string lanes = kLanes.substr(0, static_cast<std::size_t>(op[2] - '0'));
            Provenance all;
            for (const std::string& s : srcs) merge(all, sources(s, lanes));
            for (const char lane : dst.swizzle) fresh[lane] = all;
        } else {
            for (const char lane : dst.swizzle) {
                Provenance p;
                for (const std::string& s : srcs) merge(p, sources(s, std::string(1, lane)));
                fresh[lane] = p;
            }
        }

        std::vector<Literal> lits;
        for (const std::string& s : srcs) lits.push_back(literal(s));

        // Role patterns, evaluated with the provenance before this write.
        Register reg;
        if (op == "mad" && n == 3 && has_values(lits[2]) && is_metal_f0(*lits[2])) {
            if (parse_register(srcs[0], reg) && reg.swizzle.size() == 1) {
                found.metal.insert(sources(srcs[0], "x"));
                found.albedo.insert(sources(srcs[1], "xyz"));
            }
        }
        if (op == "max" && n == 2 && has_values(lits[1]) && std::fabs((*lits[1])[0] - 1.00000005e-03) < 1e-9) {
            found.gloss.insert(sources(srcs[0], dst.swizzle));
        }
        // alpha test: lt x, src.w, l(threshold) feeding a discard -> the albedo texture's alpha
        if (op == "lt" && n == 2 && has_values(lits[1]) && parse_register(srcs[0], reg)) {
            found.cutout.insert(sources(srcs[0], "x"));
        }
        if (op == "add" && n == 2 && has_values(lits[1]) && lits[1]->size() >= 3 && (*lits[1])[0] == -0.5 &&
            (*lits[1])[1] == -0.5 && (*lits[1])[2] == -0.5) {
            found.normal.insert(sources(srcs[0], "xyz"));
        }
        if (op == "mad" && n == 3 && has_values(lits[1]) && has_values(lits[2])) {
            std::vector<std::size_t> two;
            for (std::size_t k = 0; k < lits[1]->size(); ++k) {
                if ((*lits[1])[k] == 2.0) two.push_back(k);
            }
            bool detail = two.size() == 2;
            for (const std::size_t k : two) {
                detail = detail && k < 4 && k < lits[2]->size() && (*lits[2])[k] == -1.0;
            }
            if (detail) {
                std::string lanes;
                for (const std::size_t k : two) lanes += kLanes[k];
                found.detail.insert(sources(srcs[0], lanes));
            }
        }

        for (const auto& [lane, values] : fresh) {
            Provenance& slot = prov_[RegisterLane{dst.kind, dst.number, lane}];
            // A write inside a branch may not happen: keep what the register held before as well.
            if (depth > 0) merge(slot, values);
            else slot = values;
        }
    }
}

inline std::set<Provenance> nonempty(const std::set<Provenance>& sets) {
    std::set<Provenance> out;
    for (const Provenance& s : sets) {
        if (!s.empty()) out.insert(s);
    }
    return out;
}

struct Pick {
    int slot = -1;
    std::string channels;
};

// The one texture (slot, channels) every occurrence agrees on, or nothing.
inline std::optional<Pick> single(const std::set<Provenance>& sets, std::size_t width) {
    const std::set<Provenance> texsets = nonempty(sets);
    if (texsets.size() != 1) return std::nullopt;
    const Provenance& s = *texsets.begin();
    std::set<int> slots;
    std::set<char> channels;
    for (const SlotChannel& sc : s) {
        slots.insert(sc.first);
        channels.insert(sc.second);
    }
    if (slots.size() != 1 || s.size() != width) return std::nullopt;
    return Pick{*slots.begin(), std::string(channels.begin(), channels.end())};
}

// The one slot supplying `width` channels to every occurrence (others may mix in), or the preferred slot on a tie.
inline std::optional<Pick> one_slot(const std::set<Provenance>& sets, std::size_t width,
                                    const std::set<int>& prefer) {
    std::set<std::pair<int, std::string>> picks;
    for (const Provenance& s : nonempty(sets)) {
        std::map<int, std::set<char>> by_slot;
        for (const SlotChannel& sc : s) by_slot[sc.first].insert(sc.second);
        std::set<int> full;
        for (const auto& [slot, channels] : by_slot) {
            if (channels.size() >= width) full.insert(slot);
        }
        if (full.size() > 1) {
            std::set<int> preferred;
            for (const int slot : full) {
                if (prefer.count(slot) != 0) preferred.insert(slot);
            }
            if (!preferred.empty()) full = preferred;
        }
        if (full.size() != 1) return std::nullopt;
        const int slot = *full.begin();
        const std::set<char>& channels = by_slot[slot];
        picks.insert({slot, std::string(channels.begin(), channels.end())});
    }
    if (picks.size() != 1) return std::nullopt;
    const auto& [slot, channels] = *picks.begin();
    return Pick{slot, width < 3 ? channels : std::string("xyz")};
}

inline Channel to_channel(const std::optional<Pick>& pick, bool invert) {
    Channel c;
    if (pick) {
        c.slot = pick->slot;
        c.channels = pick->channels;
        c.invert = invert;
    }
    return c;
}

}  // namespace detail

inline Roles parse(const std::string& disassembly) {
    detail::Tracer tracer;
    tracer.run(disassembly);
    const detail::Found& f = tracer.found;

    const std::optional<detail::Pick> metal = detail::single(f.metal, 1);
    std::set<int> cutout;
    for (const detail::Provenance& s : f.cutout) {
        for (const detail::SlotChannel& sc : s) {
            if (sc.second == 'w') cutout.insert(sc.first);
        }
    }
    const std::optional<detail::Pick> albedo = detail::one_slot(f.albedo, 3, cutout);

    // alpha = (1 - g)^2: the gloss channel is the one texture channel alpha derives from, minus the metal channel
    std::set<detail::Provenance> gloss_candidates;
    for (detail::Provenance s : f.gloss) {
        if (metal) s.erase(detail::SlotChannel{metal->slot, metal->channels[0]});
        gloss_candidates.insert(s);
    }
    const std::optional<detail::Pick> gloss = detail::single(gloss_candidates, 1);
    const std::optional<detail::Pick> normal = detail::single(f.normal, 3);
    const std::optional<detail::Pick> detail_normal = detail::one_slot(f.detail, 2, {});

    Roles out;
    out.albedo = detail::to_channel(albedo, false);
    out.metal = detail::to_channel(metal, false);
    out.gloss = detail::to_channel(gloss, true);
    out.normal = detail::to_channel(normal, false);
    out.detail_normal = detail::to_channel(detail_normal, false);
    return out;
}

}  // namespace material_roles

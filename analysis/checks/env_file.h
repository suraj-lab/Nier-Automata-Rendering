#pragma once
// NIER_ENV.ini beside the proxy: NIER_* settings for launches that cannot set environment variables (a Windows Steam
// launch). One KEY=VALUE per line, UTF-8, '#' or ';' starts a comment line. Only keys of the form NIER_[A-Z0-9_]+ are
// accepted; the caller lets a variable already set in the environment win. Pure: no Windows calls, unit-tested.
#include <string>
#include <utility>
#include <vector>

namespace env_file {

constexpr std::size_t kMaxBytes = 64 * 1024;  // a settings file, not a data channel: larger files are ignored

inline std::string trim(const std::string& s) {
    const auto first = s.find_first_not_of(" \t\r");
    if (first == std::string::npos) return {};
    return s.substr(first, s.find_last_not_of(" \t\r") - first + 1);
}

inline bool valid_key(const std::string& key) {
    if (key.size() <= 5 || key.compare(0, 5, "NIER_") != 0) return false;
    for (const char c : key)
        if (!((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')) return false;
    return true;
}

inline std::vector<std::pair<std::string, std::string>> parse(std::string text) {
    std::vector<std::pair<std::string, std::string>> out;
    if (text.size() > kMaxBytes) return out;
    if (text.compare(0, 3, "\xEF\xBB\xBF") == 0) text.erase(0, 3);  // UTF-8 BOM (Notepad)
    std::size_t start = 0;
    while (start < text.size()) {
        std::size_t end = text.find('\n', start);
        if (end == std::string::npos) end = text.size();
        const std::string line = trim(text.substr(start, end - start));
        start = end + 1;
        if (line.empty() || line[0] == '#' || line[0] == ';') continue;
        const std::size_t eq = line.find('=');
        if (eq == std::string::npos) continue;
        const std::string key = trim(line.substr(0, eq));
        if (!valid_key(key)) continue;
        out.emplace_back(key, trim(line.substr(eq + 1)));
    }
    return out;
}

}  // namespace env_file

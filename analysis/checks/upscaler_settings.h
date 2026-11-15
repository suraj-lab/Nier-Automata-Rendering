#ifndef UPSCALER_SETTINGS_H
#define UPSCALER_SETTINGS_H

#include "upscaler_modes.h"
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <algorithm>
#include <cstdio>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <io.h>
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace upscaler {

inline std::string mode_to_string(Mode mode) {
    switch (mode) {
        case Mode::UltraPerformance: return "ultra-performance";
        case Mode::Performance:      return "performance";
        case Mode::Balanced:         return "balanced";
        case Mode::Quality:          return "quality";
        case Mode::Config:           return "";
        default:                     return "";
    }
}

inline std::string trim(const std::string& s) {
    auto start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    auto end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

inline Mode load_mode(const std::filesystem::path& ini, std::string* error) {
    std::error_code ec;  // non-throwing: a throw here would disable the whole Remix host (review 25271ddb)
    if (!std::filesystem::exists(ini, ec)) {
        if (ec && error) *error = "Could not inspect settings file: " + ec.message();
        return Mode::Config;
    }

    std::ifstream file(ini);
    if (!file) {
        if (error) *error = "Could not open file";
        return Mode::Config;
    }

    std::string line;
    Mode result = Mode::Config;

    while (std::getline(file, line)) {
        std::string trimmed = trim(line);
        if (trimmed.empty() || trimmed[0] == '#') continue;

        auto eq_pos = trimmed.find('=');
        if (eq_pos == std::string::npos) continue;

        std::string key = trim(trimmed.substr(0, eq_pos));
        if (key == "upscaler") {
            std::string value = trim(trimmed.substr(eq_pos + 1));
            Mode m;
            if (parse_mode(value, m)) {
                result = m;
            } else {
                if (error) *error = "Invalid upscaler value: " + value;
                return Mode::Config;
            }
        }
    }

    if (file.bad()) {
        if (error) *error = "Could not read settings file";
        return Mode::Config;
    }
    return result;
}

inline bool save_mode(const std::filesystem::path& ini, Mode mode, std::string* error) {
    std::vector<std::string> lines;
    bool found = false;

    std::error_code ec;
    const bool present = std::filesystem::exists(ini, ec);
    if (ec) {
        if (error) *error = "Could not inspect settings file: " + ec.message();
        return false;
    }
    if (present) {
        // Never replace a file we could not read: its other lines would be lost.
        std::ifstream file(ini);
        if (!file) {
            if (error) *error = "Could not read existing settings file";
            return false;
        }
        std::string line;
        while (std::getline(file, line)) {
            std::string trimmed = trim(line);
            if (!trimmed.empty() && trimmed[0] != '#') {
                auto eq_pos = trimmed.find('=');
                if (eq_pos != std::string::npos && trim(trimmed.substr(0, eq_pos)) == "upscaler") {
                    lines.push_back("upscaler = " + mode_to_string(mode));
                    found = true;
                    continue;
                }
            }
            lines.push_back(line);
        }
        if (file.bad()) {
            if (error) *error = "Could not read existing settings file";
            return false;
        }
    }

    if (!found) {
        lines.push_back("upscaler = " + mode_to_string(mode));
    }

    std::filesystem::path temp_path = ini;
    temp_path += ".tmp";
    // Exclusive create: a pre-existing sibling is not ours (in particular, never follow a symlink).
#ifdef _WIN32
    const int fd = _wopen(temp_path.c_str(), _O_CREAT | _O_EXCL | _O_WRONLY | _O_BINARY, _S_IREAD | _S_IWRITE);
#else
    const int fd = ::open(temp_path.c_str(), O_CREAT | O_EXCL | O_WRONLY, 0600);
#endif
    if (fd < 0) {
        if (error) *error = "Could not exclusively create temp file";
        return false;
    }
#ifdef _WIN32
    FILE* temp_file = _fdopen(fd, "wb");
#else
    FILE* temp_file = ::fdopen(fd, "wb");
#endif
    if (!temp_file) {
#ifdef _WIN32
        _close(fd);
#else
        ::close(fd);
#endif
        if (error) *error = "Could not open temp stream";
        std::filesystem::remove(temp_path, ec);
        return false;
    }
    bool written = true;
    for (const auto& line : lines) {
        if (std::fwrite(line.data(), 1, line.size(), temp_file) != line.size() || std::fputc('\n', temp_file) == EOF) {
            written = false;
            break;
        }
    }
    // fclose can be the first failure for buffered output (e.g. disk full).
    if (std::fclose(temp_file) != 0) written = false;
    if (!written) {
        if (error) *error = "Could not write temp file";
        std::filesystem::remove(temp_path, ec);
        return false;
    }
#ifdef _WIN32
    if (!MoveFileExW(temp_path.c_str(), ini.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        ec = std::error_code(static_cast<int>(GetLastError()), std::system_category());
#else
    std::filesystem::rename(temp_path, ini, ec);  // atomic replace
#endif
    if (ec) {
        if (error) *error = "Could not replace settings file: " + ec.message();
        std::error_code ignored;
        std::filesystem::remove(temp_path, ignored);
        return false;
    }
    return true;
}

} // namespace upscaler

#endif

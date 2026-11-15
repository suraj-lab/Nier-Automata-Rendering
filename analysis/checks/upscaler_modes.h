#ifndef UPSCALER_MODES_H
#define UPSCALER_MODES_H

#include <string>
#include <vector>

namespace upscaler {
    enum class Mode { Config, UltraPerformance, Performance, Balanced, Quality };
    struct Write { const char* key; const char* value; };

    inline std::vector<Write> writes_for(Mode mode) {
        if (mode == Mode::Config) return {};
        
        const char* val = nullptr;
        switch (mode) {
            case Mode::UltraPerformance: val = "0"; break;
            case Mode::Performance:      val = "1"; break;
            case Mode::Balanced:         val = "2"; break;
            case Mode::Quality:          val = "3"; break;
            default: break;
        }
        // Custom preset (2) first to avoid override by other presets.
        return {
            {"rtx.dlssPreset", "2"},
            {"rtx.qualityDLSS", val},
            {"rtx.xess.preset", val}
        };
    }

    inline bool parse_mode(const std::string& s, Mode& mode) {
        if (s.empty()) {
            mode = Mode::Config;
            return true;
        }
        if (s == "config")            { mode = Mode::Config; return true; }
        if (s == "ultra-performance") { mode = Mode::UltraPerformance; return true; }
        if (s == "performance")       { mode = Mode::Performance; return true; }
        if (s == "balanced")          { mode = Mode::Balanced; return true; }
        if (s == "quality")           { mode = Mode::Quality; return true; }
        return false;
    }
}

#endif

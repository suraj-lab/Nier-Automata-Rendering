#pragma once
#include "render_settings.h"
#include <string>
#include <string_view>
#include <vector>

namespace render_settings_file {
enum class EditResult { Updated, InvalidMode, UnsupportedEncoding, Malformed, Ambiguous, TooLarge };

inline EditResult rewrite(const std::vector<unsigned char>& original, render_settings::Mode mode,
                          std::vector<unsigned char>& updated) {
    constexpr std::size_t limit = 65536;
    if (mode != render_settings::Mode::Native && mode != render_settings::Mode::Custom75)
        return EditResult::InvalidMode;
    if (original.size() > limit) return EditResult::TooLarge;
    std::size_t bom = 0, unit = 1;
    if (original.size() >= 4 &&
        ((original[0]==0xff && original[1]==0xfe && original[2]==0 && original[3]==0) ||
         (original[0]==0 && original[1]==0 && original[2]==0xfe && original[3]==0xff)))
        return EditResult::UnsupportedEncoding;
    if (original.size() >= 2 && original[0]==0xfe && original[1]==0xff)
        return EditResult::UnsupportedEncoding;
    if (original.size() >= 2 && original[0]==0xff && original[1]==0xfe) {
        if (original.size()%2) return EditResult::Malformed;
        bom=2;unit=2;
    } else if (original.size() >= 3 && original[0]==0xef && original[1]==0xbb && original[2]==0xbf) {
        bom=3;
    }
    std::u16string text;
    text.reserve((original.size()-bom)/unit);
    for (std::size_t i=bom;i<original.size();i+=unit) {
        char16_t c=original[i];
        if (unit==2) c=static_cast<char16_t>(c | (static_cast<unsigned>(original[i+1])<<8));
        if (!c) return EditResult::Malformed;
        text.push_back(c);
    }
    auto space=[](char16_t c) { return c==u' ' || c==u'\t'; };
    auto trim=[&](std::u16string_view s) {
        while (!s.empty() && space(s.front())) s.remove_prefix(1);
        while (!s.empty() && space(s.back())) s.remove_suffix(1);
        return s;
    };
    auto equal=[&](std::u16string_view a,std::u16string_view b) {
        a=trim(a);
        if (a.size()!=b.size()) return false;
        for (std::size_t i=0;i<a.size();++i) {
            char16_t c=a[i];
            if (c>=u'A' && c<=u'Z') c=static_cast<char16_t>(c+u'a'-u'A');
            if (c!=b[i]) return false;
        }
        return true;
    };
    const auto none=std::u16string::npos;
    std::size_t value_start=none,value_end=none,section_end=text.size();
    bool in_rendering=false,seen_rendering=false;
    std::u16string newline;
    for (std::size_t pos=0;pos<text.size();) {
        std::size_t end=pos;
        while (end<text.size() && text[end]!=u'\r' && text[end]!=u'\n') ++end;
        std::size_t next=end;
        if (next<text.size()) {
            ++next;
            if (text[end]==u'\r' && next<text.size() && text[next]==u'\n') ++next;
            if (newline.empty()) newline=text.substr(end,next-end);
        }
        const std::u16string_view raw(text.data()+pos,end-pos);
        const auto line=trim(raw);
        if (!line.empty() && line[0]!=u';' && line[0]!=u'#') {
            if (line[0]==u'[') {
                const auto close=line.find(u']');
                if (close==none) return EditResult::Malformed;
                const bool target=equal(line.substr(1,close-1),u"rendering");
                const auto tail=trim(line.substr(close+1));
                if (target && !tail.empty() && tail[0]!=u';' && tail[0]!=u'#') return EditResult::Malformed;
                if (in_rendering && !target) section_end=pos;
                if (target && seen_rendering) return EditResult::Ambiguous;
                if (target) seen_rendering=true;
                in_rendering=target;
            } else if (in_rendering) {
                const auto eq=raw.find(u'=');
                if (eq==none) {
                    if (equal(line,u"preset")) return EditResult::Malformed;
                } else if (equal(raw.substr(0,eq),u"preset")) {
                    if (value_start!=none) return EditResult::Ambiguous;
                    value_start=pos+eq+1;value_end=end;
                }
            }
        }
        pos=next;
    }
    const std::u16string value=mode==render_settings::Mode::Native ? u"Native" : u"Custom75";
    if (value_start!=none) {
        text.replace(value_start,value_end-value_start,value);
    } else {
        if (newline.empty()) newline=u"\r\n";
        const std::size_t pos=seen_rendering ? section_end : text.size();
        std::u16string addition;
        if (pos && text[pos-1]!=u'\r' && text[pos-1]!=u'\n') addition+=newline;
        if (!seen_rendering) addition+=u"[Rendering]"+newline;
        addition+=u"Preset="+value+newline;
        text.insert(pos,addition);
    }
    if (text.size()>(limit-bom)/unit) return EditResult::TooLarge;
    std::vector<unsigned char> result(original.begin(),original.begin()+bom);
    result.reserve(bom+text.size()*unit);
    for (char16_t c:text) {
        result.push_back(static_cast<unsigned char>(c));
        if (unit==2) result.push_back(static_cast<unsigned char>(c>>8));
    }
    updated.swap(result);
    return EditResult::Updated;
}
} // namespace render_settings_file

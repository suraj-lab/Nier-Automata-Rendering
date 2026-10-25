#include "candidate.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

using render_settings::Mode;
using render_settings_file::EditResult;
using Bytes = std::vector<unsigned char>;
static unsigned checks = 0;
static Bytes bytes(const std::string& s) { return Bytes(s.begin(),s.end()); }
static Bytes utf16(const std::u16string& s) {
    Bytes result{0xff,0xfe};
    for (char16_t c : s) { result.push_back(static_cast<unsigned char>(c));result.push_back(static_cast<unsigned char>(c>>8)); }
    return result;
}
static void ok(const Bytes& input, Mode mode, const Bytes& expected) {
    Bytes output{1,2,3};const auto original=input;
    assert(render_settings_file::rewrite(input,mode,output)==EditResult::Updated);
    assert(input==original && output==expected);++checks;
}
static void bad(const Bytes& input, Mode mode, EditResult expected) {
    const Bytes sentinel{1,2,3};Bytes output=sentinel;const auto original=input;
    assert(render_settings_file::rewrite(input,mode,output)==expected);
    assert(input==original && output==sentinel);++checks;
}
int main() {
    ok({},Mode::Native,bytes("[Rendering]\r\nPreset=Native\r\n"));
    ok({},Mode::Custom75,bytes("[Rendering]\r\nPreset=Custom75\r\n"));
    ok(bytes("[Rendering]\r\nPreset=Custom75\r\n"),Mode::Native,bytes("[Rendering]\r\nPreset=Native\r\n"));
    ok(bytes("[Rendering]\nPreset=Native"),Mode::Custom75,bytes("[Rendering]\nPreset=Custom75"));
    ok(bytes("[Rendering]\rPreset=Native\r"),Mode::Custom75,bytes("[Rendering]\rPreset=Custom75\r"));
    ok(bytes("[Rendering]\nPreset=Broken\r\nOther=keep\n"),Mode::Native,bytes("[Rendering]\nPreset=Native\r\nOther=keep\n"));
    ok(bytes(" \t[rEnDeRiNg] \t\r\n \tPrEsEt \t= 'Custom75'  \r\n"),Mode::Native,
       bytes(" \t[rEnDeRiNg] \t\r\n \tPrEsEt \t=Native\r\n"));
    ok(bytes("[Rendering] ; comment\nPreset=Native\n"),Mode::Custom75,bytes("[Rendering] ; comment\nPreset=Custom75\n"));
    ok(bytes("[Rendering]\nPreset=\n"),Mode::Native,bytes("[Rendering]\nPreset=Native\n"));
    ok(bytes("; do not drop\n[Other]\nPreset=keep\n"),Mode::Native,
       bytes("; do not drop\n[Other]\nPreset=keep\n[Rendering]\nPreset=Native\n"));
    ok(bytes("[Other]\r\nX=1"),Mode::Native,bytes("[Other]\r\nX=1\r\n[Rendering]\r\nPreset=Native\r\n"));
    ok(bytes("[Rendering]"),Mode::Native,bytes("[Rendering]\r\nPreset=Native\r\n"));
    ok(bytes("[Rendering]\n; section comment\n[Other]\nX=1\n"),Mode::Native,
       bytes("[Rendering]\n; section comment\nPreset=Native\n[Other]\nX=1\n"));
    ok(bytes("[Rendering]\nPreset=Native\n"),Mode::Native,bytes("[Rendering]\nPreset=Native\n"));
    ok(bytes("[Other]\nPreset=a\nPreset=b\n[Rendering]\nPreset=Native\n"),Mode::Custom75,
       bytes("[Other]\nPreset=a\nPreset=b\n[Rendering]\nPreset=Custom75\n"));
    ok(bytes("\xef\xbb\xbf; café\n[Rendering]\nPreset=Wrong\n"),Mode::Native,
       bytes("\xef\xbb\xbf; café\n[Rendering]\nPreset=Native\n"));
    ok(Bytes{0xef,0xbb,0xbf},Mode::Native,bytes("\xef\xbb\xbf[Rendering]\r\nPreset=Native\r\n"));
    ok(utf16(u"; café Ω\r\n[Rendering]\r\nPreset=Custom75\r\n[Other]\r\nUnicode=保持\r\n"),Mode::Native,
       utf16(u"; café Ω\r\n[Rendering]\r\nPreset=Native\r\n[Other]\r\nUnicode=保持\r\n"));
    ok(utf16(u"[Rendering]\nPreset=Nаtive\n"),Mode::Native,utf16(u"[Rendering]\nPreset=Native\n"));
    ok(Bytes{0xff,0xfe},Mode::Native,utf16(u"[Rendering]\r\nPreset=Native\r\n"));
    ok(utf16(u"[Rendering]\nＰreset=untouched\n"),Mode::Native,
       utf16(u"[Rendering]\nＰreset=untouched\nPreset=Native\n"));
    std::string ansi="; opaque byte ";ansi.push_back(static_cast<char>(0xe9));
    ok(bytes(ansi+"\n[Rendering]\nPreset=Native\n"),Mode::Custom75,bytes(ansi+"\n[Rendering]\nPreset=Custom75\n"));
    bad({},static_cast<Mode>(99),EditResult::InvalidMode);
    bad(bytes("[Rendering]\nPreset=Native\nPreset=Custom75\n"),Mode::Native,EditResult::Ambiguous);
    bad(bytes("[Rendering]\nPreset=Native\n[rEnDeRiNg]\n"),Mode::Native,EditResult::Ambiguous);
    bad(utf16(u"[Rendering]\nPreset=Native\npReSeT=Custom75\n"),Mode::Native,EditResult::Ambiguous);
    bad(bytes("[Rendering\nPreset=Native\n"),Mode::Native,EditResult::Malformed);
    bad(bytes("[Rendering]junk\nPreset=Native\n"),Mode::Native,EditResult::Malformed);
    bad(bytes("[Rendering]\nPreset\n"),Mode::Native,EditResult::Malformed);
    bad(Bytes{0,1,2},Mode::Native,EditResult::Malformed);
    bad(Bytes{0xff,0xfe,1},Mode::Native,EditResult::Malformed);
    bad(Bytes{0xfe,0xff,0,0x41},Mode::Native,EditResult::UnsupportedEncoding);
    bad(Bytes{0xff,0xfe,0,0},Mode::Native,EditResult::UnsupportedEncoding);
    bad(Bytes{0,0,0xfe,0xff},Mode::Native,EditResult::UnsupportedEncoding);
    bad(Bytes(65537,'x'),Mode::Native,EditResult::TooLarge);
    bad(Bytes(65536,'x'),Mode::Native,EditResult::TooLarge); // Insertion must not exceed the cap either.
    std::string at_limit="[Rendering]\nPreset=Native\n;";at_limit.resize(65536,'x');
    ok(bytes(at_limit),Mode::Native,bytes(at_limit));
    std::uint32_t seed=1;
    for (unsigned i=0;i<400;++i) {
        std::string comment="; ";
        for (unsigned j=0;j<i%113;++j) { seed=seed*1664525u+1013904223u;comment+=static_cast<char>(32+seed%95); }
        const std::string prefix=comment+"\n[Other]\nKey=keep\n[Rendering]\n";
        const std::string suffix="\n"+comment+"\n[Last]\nKeep=all\n";
        ok(bytes(prefix+"Preset=Custom75"+suffix),Mode::Native,bytes(prefix+"Preset=Native"+suffix));
    }
    std::printf("{\"passed\":true,\"checks\":%u}\n",checks);
}

# Frozen pure preset-edit contract

This component edits bytes only. It performs NO filesystem/Win32 IO, registry, profile API calls,
logging, environment access or game work. Atomic persistence is a separate lead-owned layer.

Header API (C++17; reuse `render_settings.h`):

```cpp
namespace render_settings_file {
enum class EditResult { Updated, InvalidMode, UnsupportedEncoding, Malformed, Ambiguous, TooLarge };
inline EditResult rewrite(const std::vector<unsigned char>& original,
                         render_settings::Mode mode,
                         std::vector<unsigned char>& updated);
}
```

All header definitions must be inline/ODR-safe. Public gate links two translation units.

- Accept only Native / Custom75. Replace only the value of the single Rendering/Preset key.
- Preserve every other byte, including comments/unknown sections, opaque 8-bit text, UTF-8 BOM,
  UTF-16LE BOM/code units, key spelling and prefix through `=`. Discard the old preset value
  including quotes/leading/trailing value whitespace; the new value is the exact ASCII mode name.
- Match ASCII section/key spelling case-insensitively; trim ASCII spaces/tabs around names.
  Recognize CRLF, LF and CR as line endings; preserve existing endings and EOF-newline state on
  replacement. Insertion uses the first observed line ending, default CRLF if none exists.
- If Rendering exists but Preset is absent, insert at the end of that section before any following
  section. If Rendering is absent, append it, adding a line break first only when needed.
- Preserve unknown settings and comments rather than round-tripping the entire file through an INI
  parser. Empty files/BOM-only files are valid starting inputs. The file-size limit is 65536 bytes
  for BOTH input and output, not a truncation limit. An unchanged file exactly at the cap is valid.
- Reject duplicate Rendering sections or Preset keys inside Rendering as Ambiguous; duplicates in
  unrelated sections do not matter. Reject embedded NUL code units, odd UTF-16LE lengths,
  unterminated section syntax, junk after a Rendering header (a trailing `;`/`#` comment is allowed),
  and a bare `Preset` line without `=` as Malformed. Do not silently repair ambiguous structures.
- Reject UTF-16BE / UTF-32 BOMs as UnsupportedEncoding; don't misread UTF-32LE as UTF-16LE.
  Non-BOM 8-bit bytes are opaque/ANSI-compatible; do not reencode them as UTF-8. Non-ASCII identifiers
  are not ASCII lookalikes. Unknown Unicode/opaque value/comment bytes remain unchanged.
- On EVERY failure, leave both input and the caller's previous output unchanged. On success return
  Updated and replace output with complete edited bytes. Input/output are distinct caller buffers.
- Keep the implementation bounded and minimal. Allocation failures may propagate; the future IO
  layer must catch them before publishing a file. No generalized INI library or new dependency.

Frozen tests: `preset_rewrite_test.cpp`; executable gate: `test_preset_rewrite.py --candidate PATH`.
The no-op negative control compiles and fails behavior assertions. The gate also cross-builds x64
Windows without claiming native Windows execution. Parent reruns the gate and reviews before import.

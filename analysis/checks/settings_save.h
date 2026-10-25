#pragma once
// Save NIER_RENDER.ini for the NEXT launch: snapshot, stage, verify, publish, observe.
// Contract and limits: SAVE_COMMIT_CONTRACT.md. Single cooperating writer; final rechecks are not
// a compare-and-swap against other programs, and flushing is not a power-loss guarantee.
#include <windows.h>
#include <string>
#include <vector>
#include "preset_rewrite.h"
#include "render_settings.h"

namespace settings_save {
enum class Presence { Missing, Present, Unreadable };
struct Snapshot {
    Presence presence = Presence::Unreadable;
    std::vector<unsigned char> bytes;
    DWORD error = 0;
    DWORD volume = 0, index_high = 0, index_low = 0;  // file identity: a same-bytes swap is a change
};

enum class Outcome { PreCommitFailure, Committed, RecoveryRequired };
enum class Step { Snapshot, Stale, Rewrite, Stage, StageWrite, StageFlush, StageClose, StageValidation, Publish, FinalObservation, Done };
struct Result {
    Outcome outcome = Outcome::PreCommitFailure;
    Step step = Step::Snapshot;
    DWORD error = 0;
    std::vector<std::wstring> recovery_paths;  // only for RecoveryRequired; never deleted by us
};

// Test seam. Returning true injects a failure of the named step instead of calling the OS.
enum class Point { BeforePrepare, StageCreated, StageWrite, StageFlush, StageClose, StageValidation,
                   BeforePublishRecheck, Publish, FinalObservation };
struct Attempt { std::wstring target, stage, backup; };
using Hook = bool (*)(void* context, Point, const Attempt&);
using Reader = render_settings::Settings (*)(const std::wstring&);

inline Snapshot observe(const std::wstring& path) {
    Snapshot s;
    HANDLE f = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                           OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, nullptr);
    if (f == INVALID_HANDLE_VALUE) {
        s.error = GetLastError();
        // Only a missing FILE is missing; a missing directory is broken, as in the startup reader.
        if (s.error == ERROR_FILE_NOT_FOUND) s.presence = Presence::Missing;
        return s;
    }
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(f, &info)) s.error = GetLastError();
    else if (info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) s.error = ERROR_INVALID_FUNCTION;
    else {
        s.volume = info.dwVolumeSerialNumber;
        s.index_high = info.nFileIndexHigh;
        s.index_low = info.nFileIndexLow;
        s.bytes.resize(65537);  // one past the codec limit detects oversize without truncation
        DWORD total = 0, got = 0;
        BOOL ok = TRUE;  // a failed ReadFile also reports zero bytes; don't mistake it for EOF
        while (total < s.bytes.size() &&
               (ok = ReadFile(f, s.bytes.data() + total, static_cast<DWORD>(s.bytes.size() - total), &got, nullptr)) && got)
            total += got;
        if (!ok) s.error = GetLastError();
        else if (total == s.bytes.size()) s.error = ERROR_FILE_TOO_LARGE;
        else { s.bytes.resize(total); s.presence = Presence::Present; }
    }
    CloseHandle(f);
    if (s.presence != Presence::Present) s.bytes.clear();
    return s;
}

inline bool same(const Snapshot& a, const Snapshot& b) {
    return a.presence == b.presence && a.presence != Presence::Unreadable && a.bytes == b.bytes &&
           a.volume == b.volume && a.index_high == b.index_high && a.index_low == b.index_low;
}

inline bool exists(const std::wstring& path) {
    return GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES || GetLastError() != ERROR_FILE_NOT_FOUND;
}

// expected: the snapshot the menu showed. Repairs a readable invalid preset; refuses unreadable files.
inline Result save(const std::wstring& target, const Snapshot& expected, render_settings::Mode mode,
                   Reader reader, Hook hook = nullptr, void* context = nullptr) {
    static volatile LONG counter = 0;
    Result r;
    const auto fault = [&](Point p, const Attempt& a) { return hook && hook(context, p, a); };
    const auto fail = [&](Step step, DWORD error) { r.step = step; r.error = error; return r; };
    const std::wstring suffix = std::to_wstring(GetCurrentProcessId()) + L"-" +
                                std::to_wstring(InterlockedIncrement(&counter)) + L"-" + std::to_wstring(GetTickCount64());
    const Attempt attempt{target, target + L".save-" + suffix + L".tmp", target + L".backup-" + suffix + L".tmp"};

    if (expected.presence == Presence::Unreadable) return fail(Step::Snapshot, expected.error);
    fault(Point::BeforePrepare, attempt);
    const Snapshot current = observe(target);
    if (!same(current, expected)) return fail(Step::Stale, current.error);
    std::vector<unsigned char> updated;
    if (render_settings_file::rewrite(current.bytes, mode, updated) != render_settings_file::EditResult::Updated)
        return fail(Step::Rewrite, 0);
    if (exists(attempt.stage) || exists(attempt.backup)) return fail(Step::Stage, ERROR_FILE_EXISTS);

    // Never-existing sibling with the directory's inherited security; never the original file.
    HANDLE f = CreateFileW(attempt.stage.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return fail(Step::Stage, GetLastError());
    const auto discard = [&](Step step, DWORD error) { DeleteFileW(attempt.stage.c_str()); return fail(step, error); };
    DWORD written = 0;
    if (fault(Point::StageCreated, attempt)) { CloseHandle(f); return discard(Step::Stage, ERROR_ACCESS_DENIED); }
    if (fault(Point::StageWrite, attempt) ||
        !WriteFile(f, updated.data(), static_cast<DWORD>(updated.size()), &written, nullptr) || written != updated.size()) {
        const DWORD e = GetLastError(); CloseHandle(f); return discard(Step::StageWrite, e);
    }
    if (fault(Point::StageFlush, attempt) || !FlushFileBuffers(f)) {
        const DWORD e = GetLastError(); CloseHandle(f); return discard(Step::StageFlush, e);
    }
    const bool closed = CloseHandle(f) != 0;
    if (fault(Point::StageClose, attempt) || !closed) return discard(Step::StageClose, GetLastError());
    const auto staged = reader(attempt.stage);
    if (fault(Point::StageValidation, attempt) || !staged.valid || staged.defaulted || staged.mode != mode)
        return discard(Step::StageValidation, 0);

    fault(Point::BeforePublishRecheck, attempt);
    if (!same(observe(target), expected)) return discard(Step::Stale, 0);

    const bool missing = expected.presence == Presence::Missing;
    BOOL published = FALSE;
    if (!fault(Point::Publish, attempt))
        published = missing
            // No REPLACE_EXISTING: a file created meanwhile by someone else wins and is kept.
            ? MoveFileExW(attempt.stage.c_str(), target.c_str(), MOVEFILE_WRITE_THROUGH)
            : ReplaceFileW(target.c_str(), attempt.stage.c_str(), attempt.backup.c_str(), 0, nullptr, nullptr);
    const DWORD publish_error = published ? 0 : GetLastError();
    const auto recovery = [&](Step step, DWORD error) {
        r.outcome = Outcome::RecoveryRequired;
        for (const auto* p : {&attempt.target, &attempt.backup, &attempt.stage})
            if (exists(*p)) r.recovery_paths.push_back(*p);
        return fail(step, error);
    };
    if (!published) {
        // Win32 documents partial ReplaceFile failures; classify by what is actually on disk.
        const Snapshot after = observe(target);
        const bool untouched = missing ? exists(attempt.stage)
                                       : same(after, expected) && !exists(attempt.backup);
        if (untouched) return discard(Step::Publish, publish_error);
        return recovery(Step::Publish, publish_error);
    }
    const Snapshot final_state = fault(Point::FinalObservation, attempt) ? Snapshot{} : observe(target);
    if (final_state.presence != Presence::Present || final_state.bytes != updated)
        return recovery(Step::FinalObservation, final_state.error);
    if (!missing) DeleteFileW(attempt.backup.c_str());  // owned; a leftover copy is harmless
    r.outcome = Outcome::Committed;
    r.step = Step::Done;
    return r;
}
}  // namespace settings_save

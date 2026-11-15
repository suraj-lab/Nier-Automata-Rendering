// C2.1: start one child, wait for THAT process only (never a job or detached grandchildren),
// mirror its exit code, and write <report> exclusively as key=value lines (done=1 last).
//   exit_monitor.exe <report> <child.exe> [args...]
// Launch failure -> "error=launch\ndone=1\n" and nonzero exit. An existing report is never touched.
#include <windows.h>
#include <string>

static bool write_all(HANDLE handle, const char* data) {
    size_t len = std::char_traits<char>::length(data), offset = 0;
    while (offset < len) {
        DWORD written = 0;
        if (!WriteFile(handle, data + offset, static_cast<DWORD>(len - offset), &written, nullptr) || !written)
            return false;
        offset += written;
    }
    return true;
}

// Windows argv rules: backslashes double only before a quote or the closing quote; quotes become \".
static std::wstring quote(const wchar_t* arg) {
    std::wstring out(L"\"");
    for (const wchar_t* p = arg;; ++p) {
        std::size_t slashes = 0;
        for (; *p == L'\\'; ++p) ++slashes;
        if (!*p) { out.append(slashes * 2, L'\\'); break; }
        if (*p == L'"') { out.append(slashes * 2 + 1, L'\\'); out += L'"'; }
        else { out.append(slashes, L'\\'); out += *p; }
    }
    return out + L'"';
}

int main() {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv || argc < 3) return 2;   // usage
    const wchar_t* report = argv[1];
    HANDLE handle = CreateFileW(report, GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (handle == INVALID_HANDLE_VALUE) return 3;   // report already exists: never overwrite
    std::wstring cmd = quote(argv[2]);
    for (int i = 3; i < argc; ++i) {
        cmd += L' ';
        cmd += quote(argv[i]);
    }
    ULONGLONG started = GetTickCount64();
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    if (!CreateProcessW(argv[2], cmd.data(), nullptr, nullptr, FALSE, 0, nullptr, nullptr, &si, &pi)) {
        write_all(handle, "error=launch\ndone=1\n");
        FlushFileBuffers(handle);
        CloseHandle(handle);
        return 127;
    }
    CloseHandle(pi.hThread);
    write_all(handle, ("pid=" + std::to_string(pi.dwProcessId) + "\n").c_str());
    FlushFileBuffers(handle);
    WaitForSingleObject(pi.hProcess, INFINITE);   // the target only; detached grandchildren are not waited on
    DWORD exit_code = 0;
    GetExitCodeProcess(pi.hProcess, &exit_code);
    std::string tail = "exit_code=" + std::to_string(exit_code) + "\nelapsed_ms=" +
                       std::to_string(GetTickCount64() - started) + "\ndone=1\n";
    write_all(handle, tail.c_str());
    FlushFileBuffers(handle);
    CloseHandle(handle);
    CloseHandle(pi.hProcess);
    return static_cast<int>(exit_code);
}

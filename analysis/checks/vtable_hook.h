#pragma once
#include <atomic>
#include <cstddef>
namespace vtable_hook {
using Protect = bool (*)(void* address, std::size_t size, unsigned long new_protect, unsigned long* old_protect);
constexpr unsigned long kReadWrite = 0x04;
enum class Result { Hooked, AlreadyHooked, NullArgument, ProtectFailed, RestoreFailed };
inline Result hook(void** vtable, std::size_t index, void* replacement, std::atomic<void*>& original, Protect protect) {
    if (!vtable || !replacement || !protect) return Result::NullArgument;
    void** slot = vtable + index;
    unsigned long old = 0;
    if (!protect(&vtable[index], sizeof(void*), kReadWrite, &old)) return Result::ProtectFailed;
    Result result = Result::Hooked;
    while (true) {
        void* current = __atomic_load_n(slot, __ATOMIC_ACQUIRE);
        if (current == replacement) {
            result = Result::AlreadyHooked;
            break;
        }
        original.store(current, std::memory_order_release);
        if (__atomic_compare_exchange_n(slot, &current, replacement, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            result = Result::Hooked;
            break;
        }
    }
    unsigned long ignored = 0;
    if (!protect(&vtable[index], sizeof(void*), old, &ignored)) return Result::RestoreFailed;
    return result;
}
}  // namespace vtable_hook

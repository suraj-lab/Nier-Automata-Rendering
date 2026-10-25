// FROZEN gate for vtable_hook.h. Do not edit to make a candidate pass.
// Contract (header-only C++17, namespace vtable_hook, includes only <atomic>/<cstddef>):
//   using Protect = bool (*)(void* address, std::size_t size, unsigned long new_protect, unsigned long* old_protect);
//   constexpr unsigned long kReadWrite = 0x04;  // PAGE_READWRITE
//   enum class Result { Hooked, AlreadyHooked, NullArgument, ProtectFailed, RestoreFailed };
//   Result hook(void** vtable, std::size_t index, void* replacement, std::atomic<void*>& original, Protect protect);
// Rules:
//  1. vtable, replacement or protect null -> NullArgument; no protect call, nothing written.
//  2. protect(&vtable[index], sizeof(void*), kReadWrite, &old) false -> ProtectFailed; slot and original unchanged.
//  3. If the slot already holds `replacement` -> AlreadyHooked; original unchanged; protection restored.
//  4. Otherwise: store the CURRENT slot value into `original` BEFORE the slot points at `replacement`
//     (another thread may call through the slot at any moment), then compare-and-swap the slot from that
//     value to `replacement`; if the slot changed meanwhile, repeat with the new value. -> Hooked.
//  5. Always restore with protect(&vtable[index], sizeof(void*), old, &ignored) after a successful first
//     protect call. If that restore fails, return RestoreFailed (the hook stays installed).
//  6. Exactly two protect calls whenever the first one succeeds; both target &vtable[index], size 8.
#include "vtable_hook.h"
#include <atomic>
#include <cassert>
#include <cstdio>
#include <thread>
#include <vector>

using vtable_hook::Result;
static_assert(vtable_hook::kReadWrite == 0x04);

struct Call { void* address; std::size_t size; unsigned long protect; };
static std::vector<Call> calls;
static int fail_call = -1;           // 0: first protect fails, 1: restore fails
static unsigned long page = 0x20;    // PAGE_EXECUTE_READ-like starting protection
static bool fake_protect(void* address, std::size_t size, unsigned long new_protect, unsigned long* old) {
    const int index = static_cast<int>(calls.size());
    calls.push_back({address, size, new_protect});
    if (index == fail_call) return false;
    if (!old) return false;
    *old = page;
    page = new_protect;
    return true;
}
static void reset(int fail = -1) { calls.clear(); fail_call = fail; page = 0x20; }

static int a() { return 1; }
static int b() { return 2; }
static int c() { return 3; }
static void* fn(int (*f)()) { return reinterpret_cast<void*>(f); }

int main() {
    unsigned checks = 0;
    void* table[4] = {fn(a), fn(a), fn(b), fn(a)};
    std::atomic<void*> original{nullptr};

    reset();
    assert(vtable_hook::hook(nullptr, 2, fn(c), original, fake_protect) == Result::NullArgument);
    assert(vtable_hook::hook(table, 2, nullptr, original, fake_protect) == Result::NullArgument);
    assert(vtable_hook::hook(table, 2, fn(c), original, nullptr) == Result::NullArgument);
    assert(calls.empty() && table[2] == fn(b) && original.load() == nullptr); ++checks;

    reset(0);
    assert(vtable_hook::hook(table, 2, fn(c), original, fake_protect) == Result::ProtectFailed);
    assert(calls.size() == 1 && table[2] == fn(b) && original.load() == nullptr); ++checks;

    reset();
    assert(vtable_hook::hook(table, 2, fn(c), original, fake_protect) == Result::Hooked);
    assert(table[2] == fn(c) && original.load() == fn(b));
    assert(table[0] == fn(a) && table[1] == fn(a) && table[3] == fn(a));
    assert(calls.size() == 2);
    assert(calls[0].address == &table[2] && calls[0].size == sizeof(void*) && calls[0].protect == 0x04);
    assert(calls[1].address == &table[2] && calls[1].size == sizeof(void*) && calls[1].protect == 0x20);
    assert(page == 0x20); ++checks;

    reset();
    assert(vtable_hook::hook(table, 2, fn(c), original, fake_protect) == Result::AlreadyHooked);
    assert(table[2] == fn(c) && original.load() == fn(b) && calls.size() == 2 && page == 0x20); ++checks;

    reset(1);
    std::atomic<void*> second{nullptr};
    assert(vtable_hook::hook(table, 0, fn(c), second, fake_protect) == Result::RestoreFailed);
    assert(table[0] == fn(c) && second.load() == fn(a) && calls.size() == 2); ++checks;

    // Chaining: a later hook on the same slot sees the earlier hook as its original.
    reset();
    std::atomic<void*> later{nullptr};
    assert(vtable_hook::hook(table, 2, fn(a), later, fake_protect) == Result::Hooked);
    assert(later.load() == fn(c) && table[2] == fn(a)); ++checks;

    // Concurrency: readers that observe the replacement must also observe a non-null original.
    for (int round = 0; round < 2000; ++round) {
        void* slots[1] = {fn(a)};
        std::atomic<void*> orig{nullptr};
        std::atomic<bool> stop{false};
        std::atomic<unsigned> bad{0};
        std::thread reader([&] {
            auto* slot = reinterpret_cast<std::atomic<void*>*>(&slots[0]);
            while (!stop.load(std::memory_order_acquire))
                if (slot->load(std::memory_order_acquire) == fn(c) && orig.load(std::memory_order_acquire) != fn(a))
                    bad.fetch_add(1);
        });
        reset();
        assert(vtable_hook::hook(slots, 0, fn(c), orig, fake_protect) == Result::Hooked);
        stop.store(true, std::memory_order_release);
        reader.join();
        assert(bad.load() == 0 && slots[0] == fn(c) && orig.load() == fn(a));
    }
    ++checks;
    std::printf("{\"passed\":true,\"checks\":%u}\n", checks);
}

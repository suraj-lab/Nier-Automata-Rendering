#include "d3d11_hook_registry.h"
#include <cassert>
#include <atomic>
#include <thread>
#include <cstdio>

int main()
{
    D3D11HookRegistry registry;
    int first, second, callback, other;
    void* a = &first;
    void* b = &second;
    int patches = 0;
    const auto patch = [&](void** slot, void* expected, void* hook) {
        ++patches;
        if (*slot != expected) return false;
        *slot = hook;
        return true;
    };
    assert(registry.original(&a) == nullptr);
    assert(registry.install(&a, &callback, patch));
    assert(registry.original(&a) == &first);
    assert(registry.install(&a, &callback, patch));
    assert(patches == 1);
    assert(registry.install(&b, &callback, patch));
    assert(registry.original(&b) == &second);
    assert(patches == 2);

    void* failed = &first;
    assert(!registry.install(&failed, &callback, [](void**, void*, void*) { return false; }));
    assert(failed == &first && registry.original(&failed) == nullptr);
    assert(registry.install(&failed, &callback, patch));
    assert(registry.original(&failed) == &first);

    void* unknown_hook = &callback;
    assert(!registry.install(&unknown_hook, &callback, patch));
    void* empty = nullptr;
    assert(!registry.install(&empty, &callback, patch));
    a = &other;
    assert(!registry.install(&a, &callback, patch));
    assert(a == &other && registry.original(&a) == &first);

    void* shared = &second;
    std::thread threads[16];
    for (auto& thread : threads)
        thread = std::thread([&] { assert(registry.install(&shared, &callback, patch)); });
    for (auto& thread : threads) thread.join();
    assert(shared == &callback && registry.original(&shared) == &second);
    assert(patches == 4);

    D3D11HookRegistry publication;
    void* published = &first;
    std::atomic<bool> entered{false};
    std::thread reader;
    assert(publication.install(&published, &callback, [&](void** slot, void*, void* hook) {
        *slot = hook;
        reader = std::thread([&] {
            entered.store(true);
            assert(publication.original(&published) == &first);
        });
        while (!entered.load()) std::this_thread::yield();
        return true;
    }));
    reader.join();
    std::puts("PASS: distinct/shared slots, duplicate/late installation, failed patch retry, collision, concurrency and callback publication");
}

#pragma once
#include <mutex>
#include <new>
#include <vector>

// Records precede hook publication so callbacks can always recover their original.
class D3D11HookRegistry {
    struct Entry { void** slot; void* original; void* hook; };
    std::mutex mutex;
    std::vector<Entry> entries;

public:
    template<class Patch>
    bool install(void** slot, void* hook, Patch patch) {
        std::lock_guard<std::mutex> lock(mutex);
        for (const auto& entry : entries)
            if (entry.slot == slot)
                return entry.hook == hook && *slot == hook;
        if (!*slot || *slot == hook) return false;
        try { entries.push_back({slot, *slot, hook}); }
        catch (const std::bad_alloc&) { return false; }
        if (!patch(slot, entries.back().original, hook)) {
            entries.pop_back();
            return false;
        }
        return true;
    }

    void* original(void** slot) {
        std::lock_guard<std::mutex> lock(mutex);
        for (const auto& entry : entries)
            if (entry.slot == slot) return entry.original;
        return nullptr;
    }
};

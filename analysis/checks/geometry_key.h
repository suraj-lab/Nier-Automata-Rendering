#pragma once
// Geometry identity for a draw. The key names the object: the POSITION stream, index buffer, layout and draw range.
// Pointers of the other vertex streams go into the version instead, so a new one rebuilds the mesh under the same key
// and the object never leaves the scene. popin-b4000 / popin-fast-b4000 (2026-11-01): 99% of re-keyed objects
// (6,713 and 7,433 of the churn) changed only vb2_ptr, every one in the same place, and 0.8% vb1_ptr.
// Prior art: Remix keys an asset on positions + indices + geometry descriptor, never on secondary streams.
#include <algorithm>
#include <cstdint>
#include <map>
#include <vector>

namespace geometry_key {

inline std::uint64_t mix(std::uint64_t x) {  // splitmix64 finalizer
    x += 0x9e3779b97f4a7c15ull;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}

// Two draws of one key in the same frame with different secondary streams are different objects (say, one mesh with
// two UV sets): the n-th distinct secondary set seen this frame gets key variant n. Repeats with the same set share
// variant 0, so instancing still maps to one mesh. `seen` is cleared every frame by the caller.
inline std::uint64_t variant(std::uint64_t key, std::uint64_t secondary,
                             std::map<std::uint64_t, std::vector<std::uint64_t>>& seen) {
    auto& sets = seen[key];
    const auto at = std::find(sets.begin(), sets.end(), secondary);
    const std::size_t n = static_cast<std::size_t>(at - sets.begin());
    if (at == sets.end()) sets.push_back(secondary);
    return n ? mix(key ^ (0x5ec0000000000000ull + n)) : key;
}

}  // namespace geometry_key

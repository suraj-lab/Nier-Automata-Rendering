// Bounded, diagnostic-only visibility trace. Pure C++17, no IO, no GPU.
// Not a renderer policy: it only records how draw visibility decisions change.
#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <vector>

namespace visibility_trace {

constexpr unsigned kMaxEvents = 4096;

enum class Reason : unsigned {
  Accepted, Pass, Prepass, Small, Topology, Layout, Limit, Constants, Bones,
  Data, Transform, Decode, Ui, Sky, MeshMissing, BadTransform, Drawn, DrawFailed,
  // Why a draw the hook saw produced no upload. Without these the trace called every one "accepted" and the
  // capture side looked healthy while 24% of submitted instances had no mesh (live-budgetfix).
  DeferredBudget, DeferredRead, ReadPending, DecodeFailed, Dropped, Unchanged,
  Count
};

inline const char* reason_name(Reason r) {
  switch (r) {
    case Reason::Accepted: return "accepted";
    case Reason::Pass: return "pass";
    case Reason::Prepass: return "prepass";
    case Reason::Small: return "small";
    case Reason::Topology: return "topology";
    case Reason::Layout: return "layout";
    case Reason::Limit: return "limit";
    case Reason::Constants: return "constants";
    case Reason::Bones: return "bones";
    case Reason::Data: return "data";
    case Reason::Transform: return "transform";
    case Reason::Decode: return "decode";
    case Reason::Ui: return "ui";
    case Reason::Sky: return "sky";
    case Reason::MeshMissing: return "mesh_missing";
    case Reason::BadTransform: return "bad_transform";
    case Reason::Drawn: return "drawn";
    case Reason::DrawFailed: return "draw_failed";
    case Reason::DeferredBudget: return "deferred_budget";
    case Reason::DeferredRead: return "deferred_read";
    case Reason::ReadPending: return "read_pending";
    case Reason::DecodeFailed: return "decode_failed";
    case Reason::Dropped: return "dropped";
    case Reason::Unchanged: return "unchanged";
    default: return "unknown";
  }
}

struct Event {
  std::uint64_t source = 0;
  std::uint64_t geometry = 0;
  std::uint64_t ib = 0;
  unsigned index_count = 0;
  unsigned start_index = 0;
  unsigned target_w = 0;
  unsigned target_h = 0;
  unsigned instances = 0;
  unsigned texture = 0;
  unsigned bones = 0;
  unsigned flags = 0;
  unsigned error = 0;
  float position[3] = {};
  Reason reason = Reason::Data;
  // Every input of the geometry key, so a re-keyed draw can say what moved (dropout_watch::key_diff). Kept as plain
  // fields so this header stays standalone (test_visibility_trace compiles it alone).
  std::uint64_t vb[4] = {}, layout = 0;
  unsigned stride[4] = {}, vb_offset[4] = {}, ib_format = 0, ib_offset = 0;
  int base_vertex = 0;
};

struct Batch {
  std::vector<Event> events;
  unsigned dropped = 0;
  void add(const Event& e) {
    if (events.size() < kMaxEvents)
      events.push_back(e);
    else
      ++dropped;
  }
};

struct Change {
  std::uint64_t sequence = 0;
  Event event;
  bool missing = false;
  std::uint64_t mask = 0;
  unsigned calls = 0;
  unsigned instances = 0;
};

class Tracker {
 public:
  std::uint64_t untracked = 0;  // new keys refused once the retention cap is full
  std::uint64_t suppressed = 0; // would-be Change callbacks beyond the output cap

  explicit Tracker(std::size_t max_keys = 8192, std::uint64_t max_changes = 65536)
      : max_keys_(max_keys), max_changes_(max_changes) {}

  std::size_t tracked() const { return states_.size(); }

  // sequence 0, duplicates, and older snapshots are ignored. No IO here.
  template <class Emit>
  void consume(std::uint64_t sequence, const Batch& batch, const Emit& emit) {
    if (sequence <= last_sequence_) return;
    last_sequence_ = sequence;

    // Aggregate the snapshot by ordered key (source, geometry, target_w, target_h);
    // the first event seen for a key is the sample. Animated position is recorded
    // but never compared.
    std::map<Key, Agg> aggs;
    for (const Event& e : batch.events) {
      Agg& a = aggs[Key{e.source, e.geometry, e.target_w, e.target_h}];
      if (a.first) {
        a.first = false;
        a.sample = e;
      }
      ++a.calls;
      a.instances += e.instances;
      const unsigned r = static_cast<unsigned>(e.reason);
      if (r < static_cast<unsigned>(Reason::Count)) a.mask |= std::uint64_t(1) << r;  // no UB shift
    }

    for (const auto& kv : aggs) {
      const Agg& a = kv.second;
      auto it = states_.find(kv.first);
      if (it == states_.end()) {
        if (states_.size() >= max_keys_) {
          ++untracked;  // cap reached: never stored
          continue;
        }
        State s;
        s.present = true;
        s.mask = a.mask;
        s.calls = a.calls;
        s.instances = a.instances;
        s.sample = a.sample;
        states_.emplace(kv.first, s);
        emit_change(Change{sequence, a.sample, false, a.mask, a.calls, a.instances}, emit);
        continue;
      }
      State& s = it->second;
      const bool reappearance = !s.present;
      const bool changed = s.mask != a.mask || s.calls != a.calls ||
                           s.instances != a.instances ||
                           s.sample.texture != a.sample.texture ||
                           s.sample.bones != a.sample.bones ||
                           s.sample.flags != a.sample.flags ||
                           s.sample.error != a.sample.error;
      if (reappearance || changed) {
        s.present = true;
        s.mask = a.mask;
        s.calls = a.calls;
        s.instances = a.instances;
        s.sample = a.sample;
        emit_change(Change{sequence, a.sample, false, a.mask, a.calls, a.instances}, emit);
      }
    }

    // Only a complete snapshot may imply absence; missing fires once per transition,
    // and only for retained keys that are absent from this batch.
    if (batch.dropped == 0) {
      for (auto& kv : states_) {
        State& s = kv.second;
        if (!s.present || aggs.count(kv.first)) continue;
        s.present = false;
        Change c;
        c.sequence = sequence;
        c.event = s.sample;
        c.missing = true;
        c.mask = s.mask;
        c.calls = s.calls;
        c.instances = s.instances;
        emit_change(c, emit);
      }
    }
  }

 private:
  struct Key {
    std::uint64_t source = 0;
    std::uint64_t geometry = 0;
    unsigned target_w = 0;
    unsigned target_h = 0;
    bool operator<(const Key& o) const {
      if (source != o.source) return source < o.source;
      if (geometry != o.geometry) return geometry < o.geometry;
      if (target_w != o.target_w) return target_w < o.target_w;
      return target_h < o.target_h;
    }
  };

  struct Agg {
    bool first = true;
    std::uint64_t mask = 0;
    unsigned calls = 0;
    unsigned instances = 0;
    Event sample;
  };

  struct State {
    bool present = false;
    std::uint64_t mask = 0;
    unsigned calls = 0;
    unsigned instances = 0;
    Event sample;
  };

  template <class Emit>
  void emit_change(const Change& c, const Emit& emit) {
    if (emitted_ < max_changes_) {
      ++emitted_;
      emit(c);
    } else {
      ++suppressed;
    }
  }

  std::size_t max_keys_;
  std::uint64_t max_changes_;
  std::uint64_t emitted_ = 0;
  std::uint64_t last_sequence_ = 0;
  std::map<Key, State> states_;  // retained, never erased
};

}  // namespace visibility_trace

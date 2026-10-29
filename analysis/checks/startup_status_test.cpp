#include "startup_status.h"
#include <atomic>
#include <cassert>
#include <cstdio>
#include <thread>
#include <vector>

using namespace startup_status;
using render_settings::Mode;
static bool same(const Snapshot& a,const Snapshot& b) {
    return a.settings_observed==b.settings_observed && a.settings.mode==b.settings.mode &&
        a.settings.valid==b.settings.valid && a.settings.defaulted==b.settings.defaulted &&
        a.outcome==b.outcome && a.failure==b.failure && a.detail==b.detail;
}
int main() {
    {
        Publication p; Snapshot result;
        result.detail=77;const auto sentinel=result;
        assert(!p.read(result) && same(result,sentinel));
        Snapshot native;
        native.settings_observed=true;native.settings={Mode::Native,false,false};
        native.outcome=Outcome::NativeBypass;native.failure=Failure::InvalidConfig;
        assert(p.publish(native));assert(p.read(result) && same(result,native));
        Snapshot changed;changed.detail=123;
        assert(!p.publish(changed));assert(p.read(result) && same(result,native));
    }
    for (int round=0;round<32;++round) {
        Publication publication;
        std::atomic<bool> start{false};std::atomic<int> winner{0},successes{0};
        std::vector<std::thread> threads;
        for (int id=1;id<=4;++id) threads.emplace_back([&,id] {
            while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
            Snapshot data;data.settings_observed=true;data.settings={Mode::Custom75,true,true};
            data.outcome=Outcome::Custom75Applied;data.failure=Failure::None;data.detail=id;
            if (publication.publish(data)) { winner.store(id);++successes; }
        });
        for (int reader=0;reader<4;++reader) threads.emplace_back([&] {
            while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
            for (int i=0;i<10000;++i) {
                Snapshot data;data.detail=-7;
                if (publication.read(data)) {
                    assert(data.settings_observed && data.settings.mode==Mode::Custom75);
                    assert(data.settings.valid && data.settings.defaulted);
                    assert(data.outcome==Outcome::Custom75Applied && data.failure==Failure::None);
                    assert(data.detail>=1 && data.detail<=4);
                } else assert(data.detail==-7);
            }
        });
        start.store(true,std::memory_order_release);
        for (auto& thread:threads) thread.join();
        Snapshot result;assert(successes==1 && publication.read(result));
        assert(result.detail==winner);
    }
    for (auto outcome : {Outcome::NotApplied,Outcome::Incomplete,Outcome::NotStarted,Outcome::Remix50Applied}) {
        Publication p;Snapshot value;
        value.outcome=outcome;value.failure=outcome==Outcome::Remix50Applied ? Failure::None :
            outcome==Outcome::Incomplete ? Failure::MissingGate : Failure::ThreadCreation;
        assert(p.publish(value));Snapshot copy;assert(p.read(copy));assert(same(copy,value));
    }
    std::puts("{\"passed\":true,\"concurrent_rounds\":32,\"writers\":4,\"readers\":4,\"limits\":\"Transport only; actual setter producers not connected\"}");
}

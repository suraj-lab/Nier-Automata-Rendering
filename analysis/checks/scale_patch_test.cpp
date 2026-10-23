// Native unit test for scale_patch.h: g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined
#include "scale_patch.h"
#include <cassert>
#include <cstdio>
#include <vector>

using namespace scale_patch;

static bool yes(const void*, std::size_t) { return true; }
static bool no(const void*, std::size_t) { return false; }

struct Fake {
    std::vector<unsigned char> image = std::vector<unsigned char>(kRendererGlobalRva + 64, 0xcc);
    alignas(16) unsigned char renderer[0x100] = {};
    Fake(std::uint32_t w = 2880, std::uint32_t h = 1800, float s = 1.0f)
    {
        std::memcpy(&image[kSig1Rva], kSig1, sizeof(kSig1));
        std::memcpy(&image[kSig2Rva], kSig2, sizeof(kSig2));
        set_renderer(renderer);
        std::memcpy(renderer + kWidth, &w, 4);
        std::memcpy(renderer + kHeight, &h, 4);
        std::memcpy(renderer + kScale, &s, 4);
    }
    void set_renderer(void* p) { std::memcpy(&image[kRendererGlobalRva], &p, sizeof(p)); }
    float scale() const { float s; std::memcpy(&s, renderer + kScale, 4); return s; }
    Result run(float s = 0.75f, ReadableFn r = yes, Info* i = nullptr) { return try_apply(image.data(), image.size(), s, r, i); }
};

int main()
{
    { Fake f; Info i; assert(f.run(0.75f, yes, &i) == Result::Applied); assert(f.scale() == 0.75f);
      assert(i.width == 2880 && i.height == 1800 && i.before == 1.0f && i.renderer == f.renderer);
      assert(f.run() == Result::NotDefault && f.scale() == 0.75f); }               // second call: no re-write
    { Fake f; f.image[kSig1Rva + 1] ^= 1; assert(f.run() == Result::SigMismatch && f.scale() == 1.0f); }
    { Fake f; f.image[kSig2Rva + 5] ^= 1; assert(f.run() == Result::SigMismatch && f.scale() == 1.0f); }
    { Fake f; f.image[kSig1Rva + 3] ^= 1; assert(f.run() == Result::SigMismatch && f.scale() == 1.0f); } // disp
    { Fake f; f.set_renderer(nullptr); assert(f.run() == Result::NoRenderer); }
    { Fake f; assert(f.run(0.75f, no) == Result::Unreadable && f.scale() == 1.0f); }
    { Fake f(0, 0); assert(f.run() == Result::BadSize && f.scale() == 1.0f); }
    { Fake f(20000, 1800); assert(f.run() == Result::BadSize && f.scale() == 1.0f); }
    { Fake f(2880, 1800, 0.5f); assert(f.run() == Result::NotDefault && f.scale() == 0.5f); }
    { Fake f; assert(f.run(1.0f) == Result::BadScale && f.run(0.1f) == Result::BadScale && f.scale() == 1.0f); }
    { Fake f; assert(try_apply(f.image.data(), kSig2Rva, 0.75f, yes, nullptr) == Result::BadImage); }
    assert(retryable(Result::NoRenderer) && retryable(Result::BadSize) && !retryable(Result::SigMismatch));
    std::puts("scale_patch_test: all passed");
}

// Compares the pinned upstream skinning shader (upstream_rtx/pass/skinning.h, compiled as C++ with
// shim_glsl.h types) against the reference four-weight CPU bake our live path uses today, on the real
// weight/index tuples of captured NieR draws.
//
// Upstream reads weights at a 1-float stride whatever bonesPerVertex says: vertex i reads weights[i],
// weights[i+1], weights[i+2] and derives the fourth. Neighbouring vertices therefore overlap, which is the
// tearing we measured. The only exact arrangement is to give every drawn vertex its own triple, i.e. keep
// the real vertices at slots 0, 3, 6, ... and remap the index buffer to 3 * index. The two slots after each
// real vertex are never drawn. Variant "naive" is what the API does today and must disagree, otherwise this
// check proves nothing.
#include <algorithm>  // before the upstream header: its C++ min/max macros clash with libstdc++
#include <cctype>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <string>
#include <vector>
#include "shim_glsl.h"
#include "upstream_rtx/pass/skinning.h"

struct Draw {
    std::string name;
    std::vector<unsigned char> indices, weights;  // 4 per vertex
    std::size_t vertices() const { return weights.size() / 4; }
};

static std::vector<Draw> load(const char* path) {
    FILE* f = std::fopen(path, "rb");
    if (!f) { std::perror(path); std::exit(2); }
    std::string s;
    char buf[65536];
    while (std::size_t n = std::fread(buf, 1, sizeof buf, f)) s.append(buf, n);
    std::fclose(f);
    std::vector<Draw> out;
    for (std::size_t at = s.find("\"draw_"); at != std::string::npos; at = s.find("\"draw_", at + 1)) {
        Draw d;
        const std::size_t q = s.find('"', at + 1);
        if (q == std::string::npos) break;
        d.name = s.substr(at + 1, q - at - 1);
        auto array = [&](const char* key) {
            std::vector<unsigned char> v;
            std::size_t p = s.find(key, q);
            if (p == std::string::npos) return v;
            p = s.find('[', p);
            for (++p; p < s.size() && s[p] != ']';) {
                if (!std::isdigit(static_cast<unsigned char>(s[p]))) { ++p; continue; }  // separators, newlines
                char* end = nullptr;
                const long n = std::strtol(s.c_str() + p, &end, 10);
                v.push_back(static_cast<unsigned char>(n));
                p = static_cast<std::size_t>(end - s.c_str());
            }
            return v;
        };
        d.indices = array("\"indices\":");
        d.weights = array("\"weights\":");
        if (d.weights.size() == d.indices.size() && d.weights.size() % 4 == 0 && !d.weights.empty())
            out.push_back(std::move(d));
    }
    return out;
}

static void palette(std::vector<dxvk::Matrix4>& bones) {
    for (std::size_t k = 0; k < bones.size(); ++k) {
        const float s = 1.f + 0.05f * static_cast<float>(k);
        const float t = 0.5f * static_cast<float>(k);
        bones[k].rows[0] = Vector4{s, 0, 0, t};
        bones[k].rows[1] = Vector4{0, s * 1.5f, 0, -t};
        bones[k].rows[2] = Vector4{0, 0, s * 0.75f, t * 2};
        bones[k].rows[3] = Vector4{0, 0, 0, 1};
    }
}

static void bind_position(std::size_t i, float out[3]) {
    out[0] = static_cast<float>(i % 37) * 0.31f - 5.f;
    out[1] = static_cast<float>(i % 11) * 0.73f - 3.f;
    out[2] = static_cast<float>(i % 5) * 1.17f;
}

struct Run { std::vector<float> xyz; };

// Runs the shader with the runtime's own parameters (rtx_remix_api.cpp): position/normal strides from the
// vertex layout, weight and index strides fixed at 4 bytes. `slot` maps a drawn vertex to its slot in the
// arrays; the returned positions are per drawn vertex.
static Run skin(const Draw& d, const std::vector<dxvk::Matrix4>& bones, std::size_t slots,
                std::size_t (*slot)(std::size_t)) {
    const std::size_t v = d.vertices();
    std::vector<float> pos(3 * slots, 0.f), nrm(3 * slots, 0.f), dstp(3 * slots, 0.f), dstn(3 * slots, 0.f);
    std::vector<float> weights(slots + 4, 0.f);  // the runtime gets 4 floats per vertex; keep the same slack
    std::vector<uint32_t> packed(slots, 0);
    for (std::size_t i = 0; i < v; ++i) {
        const std::size_t s = slot(i);
        bind_position(i, &pos[3 * s]);
        nrm[3 * s + 2] = 1.f;
        for (unsigned k = 0; k < 4; ++k) {
            packed[s] |= static_cast<uint32_t>(d.indices[4 * i + k]) << (8 * k);
            if (k < 3) weights[s + k] = d.weights[4 * i + k] / 255.f;  // fourth weight is derived
        }
    }
    dxvk::SkinningArgs cb{};
    cb.bones = const_cast<dxvk::Matrix4*>(bones.data());
    cb.blendWeightStride = sizeof(float);
    cb.blendIndicesStride = sizeof(uint32_t);
    cb.srcPositionStride = cb.srcNormalStride = cb.dstPositionStride = cb.dstNormalStride = 3 * sizeof(float);
    cb.numBones = 4;
    cb.useIndices = 1;
    cb.useOctahedralNormals = 0;
    cb.numVertices = static_cast<uint>(slots);
    for (std::size_t i = 0; i < v; ++i) {
        const std::size_t s = slot(i);
        // Base pointers only: the shader applies idx * stride itself, exactly as it does in the runtime.
        dxvk::skinning(static_cast<uint32_t>(s), dstp.data(), dstn.data(), pos.data(), weights.data(),
                       reinterpret_cast<const uint8_t*>(packed.data()), nrm.data(), cb);
    }
    Run r;
    r.xyz.resize(3 * v);
    for (std::size_t i = 0; i < v; ++i)
        for (unsigned k = 0; k < 3; ++k) r.xyz[3 * i + k] = dstp[3 * slot(i) + k];
    return r;
}

// The reference: our live path's four-weight bake, same weights and palette.
static Run reference(const Draw& d, const std::vector<dxvk::Matrix4>& bones) {
    const std::size_t v = d.vertices();
    Run r;
    r.xyz.resize(3 * v);
    for (std::size_t i = 0; i < v; ++i) {
        float p[3];
        bind_position(i, p);
        float acc[3] = {0, 0, 0};
        for (unsigned k = 0; k < 4; ++k) {
            const float w = d.weights[4 * i + k] / 255.f;
            if (w == 0) continue;
            const auto& m = bones[d.indices[4 * i + k]];
            for (int row = 0; row < 3; ++row)
                acc[row] += w * (m.rows[row].x * p[0] + m.rows[row].y * p[1] + m.rows[row].z * p[2] + m.rows[row].w);
        }
        for (int row = 0; row < 3; ++row) r.xyz[3 * i + row] = acc[row];
    }
    return r;
}

static double worst_diff(const std::vector<float>& a, const std::vector<float>& b) {
    double m = 0;
    for (std::size_t i = 0; i < a.size(); ++i) m = std::fmax(m, std::fabs(static_cast<double>(a[i]) - b[i]));
    return m;
}

static std::size_t dense(std::size_t i) { return i; }
static std::size_t spread(std::size_t i) { return 3 * i; }

int main(int argc, char** argv) {
    if (argc != 2) { std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]); return 2; }
    auto draws = load(argv[1]);
    if (draws.empty()) { std::fprintf(stderr, "no draws parsed from %s\n", argv[1]); return 2; }
    std::vector<dxvk::Matrix4> bones(64);
    palette(bones);
    int failures = 0;
    for (const auto& d : draws) {
        const auto ref = reference(d, bones);
        const double spread_diff = worst_diff(ref.xyz, skin(d, bones, 3 * d.vertices(), spread).xyz);
        const double dense_diff = worst_diff(ref.xyz, skin(d, bones, d.vertices(), dense).xyz);
        std::printf("%s vertices=%zu spread_vs_reference=%.6f dense_vs_reference=%.6f\n", d.name.c_str(),
                    d.vertices(), spread_diff, dense_diff);
        if (!(spread_diff < 1e-4)) { std::fprintf(stderr, "  FAIL three-slot layout does not reproduce the reference\n"); ++failures; }
        if (!(dense_diff > 1e-2) && d.vertices() > 4) { std::fprintf(stderr, "  FAIL the 1-float stride agrees, so this check has no teeth\n"); ++failures; }
    }
    std::printf("%s\n", failures ? "FAILED" : "PASSED");
    return failures ? 1 : 0;
}

#pragma once
// Does the geometry we submit actually land on screen? Pure arithmetic on the game's own matrices:
// world (CB11) -> view -> projection -> NDC -> pixels, plus the degeneracies that make a mesh invisible even though
// DrawInstance succeeded (non-finite vertex, zero-area triangle, w <= 0, extent collapsed by the transform).
//
// This exists because counters said "drawn" while the picture said "gone": the only way to settle that without
// looking is to project the vertices and count the pixels they should cover.
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace visibility_math {

struct Mat4 {  // row-major, m[row][col]
    float m[4][4] = {};
};

struct Point3 { float x = 0.f, y = 0.f, z = 0.f; };

inline Mat4 from_rows(const float* f) {  // 16 floats, row-major
    Mat4 r;
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) r.m[i][j] = f[4 * i + j];
    return r;
}

inline Mat4 from_3x4(const float* f) {  // 12 floats, row-major 3x4 (translation in the 4th column)
    Mat4 r;
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 4; ++j) r.m[i][j] = f[4 * i + j];
        r.m[3][0] = r.m[3][1] = r.m[3][2] = 0.f;
    }
    r.m[3][3] = 1.f;
    return r;
}

inline bool finite(const Mat4& a) {
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j)
            if (!std::isfinite(a.m[i][j])) return false;
    return true;
}

// Determinant of the 3x3 part: a zero or near-zero value collapses the mesh to a line or point.
inline double determinant3(const Mat4& a) {
    const double d =
        static_cast<double>(a.m[0][0]) * (static_cast<double>(a.m[1][1]) * a.m[2][2] - static_cast<double>(a.m[1][2]) * a.m[2][1]) -
        static_cast<double>(a.m[0][1]) * (static_cast<double>(a.m[1][0]) * a.m[2][2] - static_cast<double>(a.m[1][2]) * a.m[2][0]) +
        static_cast<double>(a.m[0][2]) * (static_cast<double>(a.m[1][0]) * a.m[2][1] - static_cast<double>(a.m[1][1]) * a.m[2][0]);
    return d;
}

inline Point3 transform_point(const Mat4& a, const Point3& p) {
    Point3 out;
    out.x = a.m[0][0] * p.x + a.m[0][1] * p.y + a.m[0][2] * p.z + a.m[0][3];
    out.y = a.m[1][0] * p.x + a.m[1][1] * p.y + a.m[1][2] * p.z + a.m[1][3];
    out.z = a.m[2][0] * p.x + a.m[2][1] * p.y + a.m[2][2] * p.z + a.m[2][3];
    return out;
}

inline Mat4 multiply(const Mat4& a, const Mat4& b) {
    Mat4 r;
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) {
            double s = 0;
            for (int k = 0; k < 4; ++k) s += static_cast<double>(a.m[i][k]) * b.m[k][j];
            r.m[i][j] = static_cast<float>(s);
        }
    return r;
}

struct Screen {
    float x = 0.f, y = 0.f;   // pixels, origin top-left
    float w = 0.f;            // clip w; <= 0 means behind the camera
    bool finite = false;
};

// world -> view -> projection -> NDC -> pixels. `view_projection` is view*projection.
inline Screen project(const Mat4& view_projection, const Point3& world, float width, float height) {
    const float x = view_projection.m[0][0] * world.x + view_projection.m[0][1] * world.y +
                    view_projection.m[0][2] * world.z + view_projection.m[0][3];
    const float y = view_projection.m[1][0] * world.x + view_projection.m[1][1] * world.y +
                    view_projection.m[1][2] * world.z + view_projection.m[1][3];
    const float w = view_projection.m[3][0] * world.x + view_projection.m[3][1] * world.y +
                    view_projection.m[3][2] * world.z + view_projection.m[3][3];
    Screen s;
    s.finite = std::isfinite(x) && std::isfinite(y) && std::isfinite(w);
    s.w = w;
    if (!s.finite || w <= 1e-6f) return s;
    const float ndc_x = x / w, ndc_y = y / w;
    s.x = (ndc_x * 0.5f + 0.5f) * width;
    s.y = (0.5f - ndc_y * 0.5f) * height;
    return s;
}

// Twice the signed area of the projected triangle, in pixels^2. Zero means the triangle cannot cover a pixel:
// three collinear projections, or a vertex behind the camera (the caller must check `w` for all three).
inline double triangle_area_px(const Screen& a, const Screen& b, const Screen& c) {
    return static_cast<double>(b.x - a.x) * (c.y - a.y) - static_cast<double>(c.x - a.x) * (b.y - a.y);
}

struct Coverage {
    unsigned triangles = 0;        // total triangles considered
    unsigned on_screen = 0;        // at least one vertex inside the frame
    unsigned degenerate = 0;       // zero (or non-finite) projected area
    unsigned behind = 0;           // a vertex with w <= 0: the triangle is clipped, not visible as-is
    double area_px = 0;            // sum of |area| of on-screen triangles, pixels^2 (double counts overlap)
    float min_x = 1e30f, min_y = 1e30f, max_x = -1e30f, max_y = -1e30f;
};

inline void add_triangle(Coverage& c, const Screen& a, const Screen& b, const Screen& d, float width, float height) {
    ++c.triangles;
    if (!a.finite || !b.finite || !d.finite) { ++c.degenerate; return; }
    if (a.w <= 1e-6f || b.w <= 1e-6f || d.w <= 1e-6f) { ++c.behind; return; }
    const double area = triangle_area_px(a, b, d);
    if (!std::isfinite(area) || area == 0.0) { ++c.degenerate; return; }
    const float lo_x = std::fmin(a.x, std::fmin(b.x, d.x)), hi_x = std::fmax(a.x, std::fmax(b.x, d.x));
    const float lo_y = std::fmin(a.y, std::fmin(b.y, d.y)), hi_y = std::fmax(a.y, std::fmax(b.y, d.y));
    if (hi_x < 0.f || lo_x > width || hi_y < 0.f || lo_y > height) return;  // fully outside: not counted
    ++c.on_screen;
    c.area_px += std::fabs(area) * 0.5;
    c.min_x = std::fmin(c.min_x, lo_x); c.max_x = std::fmax(c.max_x, hi_x);
    c.min_y = std::fmin(c.min_y, lo_y); c.max_y = std::fmax(c.max_y, hi_y);
}

// Fraction of the frame this coverage could touch, 0..1. A draw that should be a wall fills a large part of the
// frame; a draw whose geometry really is on screen but whose fraction is ~0 is where "we drew it, we cannot see it"
// starts.
inline double screen_fraction(const Coverage& c, float width, float height) {
    if (width <= 0.f || height <= 0.f || c.on_screen == 0) return 0.0;
    const double w = std::fmax(0.f, std::fmin(width, c.max_x) - std::fmax(0.f, c.min_x));
    const double h = std::fmax(0.f, std::fmin(height, c.max_y) - std::fmax(0.f, c.min_y));
    return w * h / (static_cast<double>(width) * height);
}

// ---- Remix's own camera -----------------------------------------------------------------------------------------
// The worker hands Remix position/forward/up/right/fovY/aspect (nscn_scene.h setup_camera), so the projection below is
// the one the runtime itself uses: coverage measured here is "what Remix's camera says should be on screen", which is
// the only claim we can make about the picture without looking at it.
struct Cam {
    float px = 0.f, py = 0.f, pz = 0.f;
    float fx = 0.f, fy = 0.f, fz = 0.f;
    float ux = 0.f, uy = 0.f, uz = 0.f;
    float rx = 0.f, ry = 0.f, rz = 0.f;
    float tan_y = 1.f, aspect = 1.f;
};

inline Cam camera_from(const float c[14], float aspect) {
    Cam cam;
    cam.px = c[0]; cam.py = c[1]; cam.pz = c[2];
    cam.fx = c[3]; cam.fy = c[4]; cam.fz = c[5];
    cam.ux = c[6]; cam.uy = c[7]; cam.uz = c[8];
    cam.rx = c[9]; cam.ry = c[10]; cam.rz = c[11];
    const float fov = c[12] > 1.f ? c[12] : 50.f;
    cam.tan_y = std::tan(fov * 0.5f * 3.14159265358979323846f / 180.f);
    cam.aspect = aspect > 0.f ? aspect : 1.f;
    return cam;
}

// World -> view space with the camera basis, then a standard perspective divide where w = -z_view.
inline Screen project_camera(const Cam& cam, const Point3& w, float width, float height) {
    const float dx = w.x - cam.px, dy = w.y - cam.py, dz = w.z - cam.pz;
    const float vx = dx * cam.rx + dy * cam.ry + dz * cam.rz;
    const float vy = dx * cam.ux + dy * cam.uy + dz * cam.uz;
    const float vz = -(dx * cam.fx + dy * cam.fy + dz * cam.fz);
    Screen s;
    s.finite = std::isfinite(vx) && std::isfinite(vy) && std::isfinite(vz);
    s.w = -vz;
    if (!s.finite || s.w <= 1e-6f) return s;
    const float ndc_x = vx / (cam.tan_y * cam.aspect) / s.w;
    const float ndc_y = vy / cam.tan_y / s.w;
    s.x = (ndc_x * 0.5f + 0.5f) * width;
    s.y = (0.5f - ndc_y * 0.5f) * height;
    return s;
}

struct Bounds {
    float lo[3] = {1e30f, 1e30f, 1e30f};
    float hi[3] = {-1e30f, -1e30f, -1e30f};
    bool valid() const { return lo[0] <= hi[0] && lo[1] <= hi[1] && lo[2] <= hi[2]; }
    void add(const float p[3]) {
        for (int i = 0; i < 3; ++i) {
            lo[i] = std::fmin(lo[i], p[i]);
            hi[i] = std::fmax(hi[i], p[i]);
        }
    }
};

// Fraction of the frame the transformed box could touch, from its 8 projected corners. `behind` counts corners with
// w <= 0: a box straddling the camera plane reports a fraction but the caller must not treat it as simply visible.
inline double fraction_from_bounds(const Cam& cam, const Bounds& b, const Mat4& world, float width, float height,
                                   unsigned* corners_on_screen = nullptr, unsigned* corners_behind = nullptr) {
    if (!b.valid() || !finite(world)) return 0.0;
    float lo_x = 1e30f, lo_y = 1e30f, hi_x = -1e30f, hi_y = -1e30f;
    unsigned on = 0, behind = 0;
    for (int k = 0; k < 8; ++k) {
        const Point3 corner{(k & 1) ? b.hi[0] : b.lo[0], (k & 2) ? b.hi[1] : b.lo[1], (k & 4) ? b.hi[2] : b.lo[2]};
        const Screen s = project_camera(cam, transform_point(world, corner), width, height);
        if (!s.finite || s.w <= 1e-6f) { ++behind; continue; }
        ++on;
        lo_x = std::fmin(lo_x, s.x); hi_x = std::fmax(hi_x, s.x);
        lo_y = std::fmin(lo_y, s.y); hi_y = std::fmax(hi_y, s.y);
    }
    if (corners_on_screen) *corners_on_screen = on;
    if (corners_behind) *corners_behind = behind;
    if (!on) return 0.0;
    const double w = std::fmax(0.f, std::fmin(width, hi_x) - std::fmax(0.f, lo_x));
    const double h = std::fmax(0.f, std::fmin(height, hi_y) - std::fmax(0.f, lo_y));
    return w * h / (static_cast<double>(width) * height);
}

}  // namespace visibility_math

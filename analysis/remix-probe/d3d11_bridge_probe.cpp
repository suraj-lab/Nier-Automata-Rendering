// Bridge probe: can a path-traced Remix frame end up in a D3D11 texture, in one process, with DXVK and the
// Remix runtime each holding their own Vulkan device?
//
// This is the last untested link for "live Remix in NieR". The game's own Present hook draws into a D3D11
// backbuffer, so the Remix frame has to travel: dxvk_CopyRenderingOutput -> D3D9 surface -> CPU -> D3D11
// texture. Everything else in that chain is proven (see analysis/LIVE_TRANSFER.md).
//
// Deliberately minimal: one emissive triangle, no shaders, no window presentation on the D3D11 side, so a
// failure can only be the bridge. Mirrors the probe's proven call order exactly.
//
// Build: x86_64-w64-mingw32-g++ -std=c++17 -O1 -Wall -Wextra -municode -static -static-libgcc
//        -static-libstdc++ -isystem vendor d3d11_bridge_probe.cpp -o ../runtime/remix-probe/d3d11-bridge.exe
// Run:   <host> --render Z:\path\to\.trex\d3d9.dll [--frames N] [--out bridge.ppm]
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#include <d3d11.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <vector>
#include <remix_c.h>

namespace {
FILE* report_file=nullptr;
// Under Proton the child's stdout is dropped entirely (measured), so every result goes to a file.
void report(const char* fmt, ...) {
    va_list a; va_start(a,fmt);
    if (report_file) { std::vfprintf(report_file,fmt,a); std::fflush(report_file); }
    va_end(a);
}

struct RemixSide {
    remixapi_Interface api{};
    remixapi_HMODULE module=nullptr;
    IDirect3D9Ex* d3d9=nullptr;
    IDirect3DDevice9Ex* device=nullptr;
    HWND window=nullptr;
    unsigned width=0, height=0;
    remixapi_MaterialHandle material=nullptr;
    remixapi_MeshHandle mesh=nullptr;
    remixapi_LightHandle light=nullptr;
    bool pre_registered=false;
};

bool remix_init(RemixSide& r, const wchar_t* runtime_path, unsigned w, unsigned h) {
    report("remix: InitializeLibrary %ls\n", runtime_path);
    if (remixapi_lib_loadRemixDllAndInitialize(runtime_path,&r.api,&r.module)!=REMIXAPI_ERROR_CODE_SUCCESS) {
        report("remix: InitializeLibrary FAILED\n"); return false;
    }
    // Hidden window: Remix needs somewhere to own a swapchain, and we must not add a second visible window.
    WNDCLASSW wc{}; wc.lpfnWndProc=DefWindowProcW; wc.hInstance=GetModuleHandleW(nullptr);
    wc.lpszClassName=L"nier-bridge-probe";
    RegisterClassW(&wc);
    r.window=CreateWindowExW(0,wc.lpszClassName,L"bridge probe",WS_POPUP,0,0,(int)w,(int)h,
                             nullptr,nullptr,wc.hInstance,nullptr);
    if (!r.window) { report("remix: CreateWindow failed %lu\n",GetLastError()); return false; }
    r.width=w; r.height=h;

    // Proven order (LIVE_TRANSFER.md): our device first, register it, then Startup refuses with ALREADY_EXISTS.
    remixapi_StartupInfo startup{};
    startup.sType=REMIXAPI_STRUCT_TYPE_STARTUP_INFO;
    startup.hwnd=r.window;
    startup.combineGuiInFinalColor=1;
    if (!r.api.dxvk_CreateD3D9 || !r.api.dxvk_RegisterD3D9Device || !r.api.Startup) {
        report("remix: runtime lacks the interop members\n"); return false;
    }
    if (r.api.dxvk_CreateD3D9(0,&r.d3d9) || !r.d3d9) { report("remix: dxvk_CreateD3D9 FAILED\n"); return false; }
    D3DPRESENT_PARAMETERS pp{};
    pp.BackBufferWidth=w; pp.BackBufferHeight=h; pp.BackBufferFormat=D3DFMT_A8R8G8B8;
    pp.BackBufferCount=1; pp.SwapEffect=D3DSWAPEFFECT_DISCARD; pp.Windowed=TRUE;
    pp.hDeviceWindow=r.window; pp.PresentationInterval=D3DPRESENT_INTERVAL_IMMEDIATE;
    if (FAILED(r.d3d9->CreateDeviceEx(D3DADAPTER_DEFAULT,D3DDEVTYPE_HAL,r.window,
            D3DCREATE_HARDWARE_VERTEXPROCESSING|D3DCREATE_MULTITHREADED,&pp,nullptr,&r.device)) || !r.device) {
        report("remix: CreateDeviceEx FAILED\n"); return false;
    }
    r.pre_registered=r.api.dxvk_RegisterD3D9Device(r.device)==0;
    const remixapi_ErrorCode startup_rc=r.api.Startup(&startup);
    report("remix: registered=%d startup_rc=%d (ALREADY_EXISTS expected)\n",r.pre_registered?1:0,(int)startup_rc);
    if (!r.pre_registered) return false;

    // One emissive triangle: bright enough that the D3D11 side cannot be confused with a clear colour.
    remixapi_MaterialInfoOpaqueEXT opaque{};
    opaque.sType=REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    opaque.albedoConstant={0.1f,0.9f,0.2f}; opaque.opacityConstant=1.f; opaque.roughnessConstant=0.5f;
    remixapi_MaterialInfo mat{};
    mat.sType=REMIXAPI_STRUCT_TYPE_MATERIAL_INFO; mat.pNext=&opaque; mat.hash=1;
    mat.emissiveIntensity=0.f;
    if (r.api.CreateMaterial(&mat,&r.material) || !r.material) { report("remix: CreateMaterial FAILED\n"); return false; }
    report("remix: material created but NOT used on the surface (default material path)\n");

    // Shapes copied from the working probe (triangle.cpp), not guessed: remixapi_HardcodedVertex carries
    // position, normal, texcoord and a packed colour, and the surface points at them directly.
    const float positions[3][3]={{-0.8f,-0.6f,2.5f},{0.8f,-0.6f,2.5f},{0.f,0.8f,2.5f}};
    const float uvs[3][2]={{0.f,0.f},{1.f,0.f},{0.5f,1.f}};
    remixapi_HardcodedVertex vertices[3]{};
    for (unsigned i=0;i<3;++i) {
        for (unsigned k=0;k<3;++k) vertices[i].position[k]=positions[i][k];
        vertices[i].normal[2]=-1.f;
        for (unsigned k=0;k<2;++k) vertices[i].texcoord[k]=uvs[i][k];
        vertices[i].color=0xffffffffu;
    }
    remixapi_MeshInfoSurfaceTriangles surface{};
    surface.vertices_values=vertices; surface.vertices_count=3;
    surface.indices_values=nullptr; surface.indices_count=0;
    surface.material=nullptr;  // default material: custom-material + mesh is the variant known to be unproven
    remixapi_MeshInfo mesh{};
    mesh.sType=REMIXAPI_STRUCT_TYPE_MESH_INFO;
    mesh.hash=1; mesh.surfaces_values=&surface; mesh.surfaces_count=1;
    if (r.api.CreateMesh(&mesh,&r.mesh) || !r.mesh) { report("remix: CreateMesh FAILED\n"); return false; }

    remixapi_LightInfoDistantEXT distant{};
    distant.sType=REMIXAPI_STRUCT_TYPE_LIGHT_INFO_DISTANT_EXT;
    distant.direction={0.3f,-0.9f,0.3f};
    distant.angularDiameterDegrees=20.f;      // wide disc: same irradiance without tripping the firefly clamp
    distant.volumetricRadianceScale=1.f;
    remixapi_LightInfo li{};
    li.sType=REMIXAPI_STRUCT_TYPE_LIGHT_INFO; li.pNext=&distant; li.hash=7;
    li.radiance={2.f,2.f,1.9f};
    if (r.api.CreateLight(&li,&r.light) || !r.light) { report("remix: CreateLight FAILED\n"); return false; }
    return true;
}

bool remix_frame(RemixSide& r) {
    remixapi_CameraInfoParameterizedEXT params{};
    params.sType=REMIXAPI_STRUCT_TYPE_CAMERA_INFO_PARAMETERIZED_EXT;
    params.position={0.f,0.f,0.f}; params.forward={0.f,0.f,1.f};
    params.up={0.f,1.f,0.f}; params.right={1.f,0.f,0.f};
    params.fovYInDegrees=60.f; params.aspect=float(r.width)/float(r.height);
    params.nearPlane=0.1f; params.farPlane=100.f;
    remixapi_CameraInfo camera{};
    camera.sType=REMIXAPI_STRUCT_TYPE_CAMERA_INFO;
    camera.pNext=&params; camera.type=REMIXAPI_CAMERA_TYPE_WORLD;
    remixapi_InstanceInfo inst{};
    inst.sType=REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
    inst.mesh=r.mesh; inst.doubleSided=1;
    for (unsigned i=0;i<3;++i) inst.transform.matrix[i][i]=1.f;
    bool ok = r.api.SetupCamera(&camera)==0;
    ok = ok && r.api.DrawInstance(&inst)==0;
    ok = ok && r.api.DrawLightInstance(r.light)==0;
    ok = ok && r.api.Present(nullptr)==0;
    return ok;
}

// The bridge itself: Remix's final colour -> D3D9 surface -> CPU -> D3D11 texture -> back to CPU.
bool bridge_once(RemixSide& r, ID3D11Device* dev, ID3D11DeviceContext* ctx,
                 ID3D11Texture2D* upload, ID3D11Texture2D* staging,
                 std::vector<unsigned char>& out, unsigned& w, unsigned& h, const char*& stage_name) {
    IDirect3DSurface9* backbuffer=nullptr;
    if (FAILED(r.device->GetBackBuffer(0,0,D3DBACKBUFFER_TYPE_MONO,&backbuffer)) || !backbuffer) {
        stage_name="getBackBuffer"; return false;
    }
    D3DSURFACE_DESC desc{};
    backbuffer->GetDesc(&desc);
    backbuffer->Release();
    w=desc.Width; h=desc.Height;

    IDirect3DSurface9* target=nullptr;
    if (FAILED(r.device->CreateRenderTarget(w,h,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&target,nullptr)) || !target) {
        stage_name="createRenderTarget"; return false;
    }
    if (r.api.dxvk_CopyRenderingOutput(target,REMIXAPI_DXVK_COPY_RENDERING_OUTPUT_TYPE_FINAL_COLOR)) {
        target->Release(); stage_name="copyRenderingOutput"; return false;
    }
    IDirect3DSurface9* sys=nullptr;
    if (FAILED(r.device->CreateOffscreenPlainSurface(w,h,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&sys,nullptr)) || !sys) {
        target->Release(); stage_name="createOffscreenPlainSurface"; return false;
    }
    if (FAILED(r.device->GetRenderTargetData(target,sys))) {
        sys->Release(); target->Release(); stage_name="getRenderTargetData"; return false;
    }
    D3DLOCKED_RECT locked{};
    if (FAILED(sys->LockRect(&locked,nullptr,D3DLOCK_READONLY))) {
        sys->Release(); target->Release(); stage_name="lockRect"; return false;
    }
    // D3D11 side: the frame has to survive DXVK's D3D11 path, not just reach our memory.
    D3D11_BOX box{0,0,0,w,h,1};
    ctx->UpdateSubresource(upload,0,&box,locked.pBits,(UINT)locked.Pitch,0);
    sys->UnlockRect();
    sys->Release(); target->Release();
    ctx->CopyResource(staging,upload);
    D3D11_MAPPED_SUBRESOURCE mapped{};
    if (FAILED(ctx->Map(staging,0,D3D11_MAP_READ,0,&mapped))) { stage_name="d3d11 map"; return false; }
    out.resize((size_t)w*h*4);
    for (unsigned y=0;y<h;++y)
        std::memcpy(&out[(size_t)y*w*4],static_cast<const unsigned char*>(mapped.pData)+(size_t)y*mapped.RowPitch,(size_t)w*4);
    ctx->Unmap(staging,0);
    stage_name=nullptr;
    return true;
}

// --bench WxH: cost of the D3D11 hop alone (upload + GPU copy + map back), no Remix involved. The live budget
// is this plus the measured Remix->CPU copy (0.49 ms at 2580x1080).
int bench_bridge(unsigned w, unsigned h, int frames) {
    ID3D11Device* dev=nullptr; ID3D11DeviceContext* ctx=nullptr; D3D_FEATURE_LEVEL level{};
    const D3D_FEATURE_LEVEL want[]={D3D_FEATURE_LEVEL_11_0};
    if (FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,want,1,D3D11_SDK_VERSION,
                                 &dev,&level,&ctx)) || !dev) { report("RESULT bench_d3d11_failed\n"); return 1; }
    D3D11_TEXTURE2D_DESC td{};
    td.Width=w; td.Height=h; td.MipLevels=1; td.ArraySize=1; td.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    td.SampleDesc={1,0}; td.Usage=D3D11_USAGE_DEFAULT; td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* upload=nullptr;
    if (FAILED(dev->CreateTexture2D(&td,nullptr,&upload))) { report("RESULT bench_upload_failed\n"); return 1; }
    td.Usage=D3D11_USAGE_STAGING; td.BindFlags=0; td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* staging=nullptr;
    if (FAILED(dev->CreateTexture2D(&td,nullptr,&staging))) { report("RESULT bench_staging_failed\n"); return 1; }
    std::vector<unsigned char> src((size_t)w*h*4, 128), dst((size_t)w*h*4);
    for (int i=0;i<5;++i) {  // warm up
        D3D11_BOX box{0,0,0,w,h,1};
        ctx->UpdateSubresource(upload,0,&box,src.data(),w*4,0);
        ctx->CopyResource(staging,upload);
        D3D11_MAPPED_SUBRESOURCE m{};
        if (SUCCEEDED(ctx->Map(staging,0,D3D11_MAP_READ,0,&m))) {
            for (unsigned y=0;y<h;++y) std::memcpy(&dst[(size_t)y*w*4],(const unsigned char*)m.pData+(size_t)y*m.RowPitch,(size_t)w*4);
            ctx->Unmap(staging,0);
        }
    }
    LARGE_INTEGER f,t0,t1; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&t0);
    for (int i=0;i<frames;++i) {
        D3D11_BOX box{0,0,0,w,h,1};
        ctx->UpdateSubresource(upload,0,&box,src.data(),w*4,0);
        ctx->CopyResource(staging,upload);
        D3D11_MAPPED_SUBRESOURCE m{};
        if (SUCCEEDED(ctx->Map(staging,0,D3D11_MAP_READ,0,&m))) {
            for (unsigned y=0;y<h;++y) std::memcpy(&dst[(size_t)y*w*4],(const unsigned char*)m.pData+(size_t)y*m.RowPitch,(size_t)w*4);
            ctx->Unmap(staging,0);
        }
    }
    QueryPerformanceCounter(&t1);
    const double ms=(t1.QuadPart-t0.QuadPart)*1000.0/double(f.QuadPart)/frames;
    report("RESULT bench size=%ux%u frames=%d ms_per_frame=%.3f fps_ceiling=%.1f\n",w,h,frames,ms,1000.0/ms);
    staging->Release(); upload->Release(); ctx->Release(); dev->Release();
    return 0;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    const wchar_t* runtime=nullptr; int frames=60; const wchar_t* out_path=L"bridge.ppm";
    report_file=std::fopen("bridge.txt","w");
    for (int i=1;i<argc;++i) {
        if (!std::wcscmp(argv[i],L"--render") && i+1<argc) runtime=argv[++i];
        else if (!std::wcscmp(argv[i],L"--frames") && i+1<argc) frames=_wtoi(argv[++i]);
        else if (!std::wcscmp(argv[i],L"--out") && i+1<argc) out_path=argv[++i];
        else if (!std::wcscmp(argv[i],L"--bench") && i+1<argc) {
            unsigned bw=0,bh=0;
            if (std::swscanf(argv[++i],L"%ux%u",&bw,&bh)==2 && bw && bh) {
                if (!report_file) report_file=std::fopen("bridge.txt","w");
                const int rc=bench_bridge(bw,bh,frames);
                if (report_file) std::fclose(report_file);
                return rc;
            }
        }
    }
    if (!report_file) return 2;
    if (!runtime || !runtime[0] || !std::wcschr(runtime,L':')) {
        report("usage: d3d11-bridge.exe --render <absolute d3d9.dll> [--frames N]\n");
        std::fclose(report_file); return 2;
    }
    const unsigned w=640, h=360;
    RemixSide remix;
    if (!remix_init(remix,runtime,w,h)) { report("RESULT remix_init_failed\n"); std::fclose(report_file); return 1; }

    // D3D11: the API the game presents through.
    ID3D11Device* dev=nullptr; ID3D11DeviceContext* ctx=nullptr;
    D3D_FEATURE_LEVEL level{};
    const D3D_FEATURE_LEVEL want[]={D3D_FEATURE_LEVEL_11_0};
    if (FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,want,1,D3D11_SDK_VERSION,
                                 &dev,&level,&ctx)) || !dev) {
        report("RESULT d3d11_device_failed\n"); std::fclose(report_file); return 1;
    }
    report("d3d11: device ok, feature level 0x%x\n",(unsigned)level);
    D3D11_TEXTURE2D_DESC td{};
    td.Width=w; td.Height=h; td.MipLevels=1; td.ArraySize=1; td.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    td.SampleDesc={1,0}; td.Usage=D3D11_USAGE_DEFAULT; td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* upload=nullptr;
    if (FAILED(dev->CreateTexture2D(&td,nullptr,&upload)) || !upload) {
        report("RESULT d3d11_upload_texture_failed\n"); std::fclose(report_file); return 1;
    }
    td.Usage=D3D11_USAGE_STAGING; td.BindFlags=0; td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* staging=nullptr;
    if (FAILED(dev->CreateTexture2D(&td,nullptr,&staging)) || !staging) {
        report("RESULT d3d11_staging_texture_failed\n"); std::fclose(report_file); return 1;
    }

    for (int i=0;i<frames;++i) {
        if (!remix_frame(remix)) { report("RESULT frame_failed at %d\n",i); std::fclose(report_file); return 1; }
        Sleep(16);
    }
    std::vector<unsigned char> pixels; unsigned bw=0, bh=0; const char* stage_name=nullptr;
    if (!bridge_once(remix,dev,ctx,upload,staging,pixels,bw,bh,stage_name)) {
        report("RESULT bridge_failed stage=%s\n",stage_name?stage_name:"?");
        std::fclose(report_file); return 1;
    }
    double sum=0; unsigned long nonblack=0, greenish=0;
    const unsigned long total=(unsigned long)bw*bh;
    for (unsigned long i=0;i<total;++i) {
        const unsigned char* p=&pixels[(size_t)i*4];  // B,G,R,A
        sum+=(0.0722*p[0]+0.7152*p[1]+0.2126*p[2])/255.0;
        if (p[0]|p[1]|p[2]) ++nonblack;
        if (p[0]>120 && p[1]>120 && p[2]>120) ++greenish;  // bright pixels: the lit triangle
    }
    report("RESULT ok size=%ux%u mean_luma=%.4f nonblack=%.4f greenish=%.4f\n",
           bw,bh,sum/total,double(nonblack)/total,double(greenish)/total);
    if (FILE* f=_wfopen(out_path,L"wb")) {
        std::fprintf(f,"P6\n%u %u\n255\n",bw,bh);
        for (unsigned long i=0;i<total;++i) {
            const unsigned char* p=&pixels[(size_t)i*4];
            const unsigned char rgb[3]={p[2],p[1],p[0]};
            std::fwrite(rgb,1,3,f);
        }
        std::fclose(f);
    }
    if (remix.api.Shutdown) remix.api.Shutdown();
    if (remix.light) remix.api.DestroyLight(remix.light);
    if (remix.mesh) remix.api.DestroyMesh(remix.mesh);
    if (remix.material) remix.api.DestroyMaterial(remix.material);
    if (staging) staging->Release();
    if (upload) upload->Release();
    if (ctx) ctx->Release();
    if (dev) dev->Release();
    if (remix.device) remix.device->Release();
    if (remix.d3d9) remix.d3d9->Release();
    if (remix.window) DestroyWindow(remix.window);
    std::fclose(report_file);
    return 0;
}

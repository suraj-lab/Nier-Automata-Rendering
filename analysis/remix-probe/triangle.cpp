// Standalone Remix API probe. No game hooks, Toolkit connection or runtime load without --render.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cwchar>
#include <stdexcept>

namespace {
// Reference-scene baseline follows NVIDIA's RemixAPI_C sample geometry.
constexpr float positions[3][3] = {{5.f,-5.f,10.f},{0.f,5.f,10.f},{-5.f,-5.f,10.f}};
constexpr float uv[3][2] = {{0,1},{1,1},{0.5f,0}};
constexpr std::uint32_t indices[3] = {0,1,2};
constexpr unsigned frames = 16, frame_delay_ms = 250;  // submission bound, NOT a GPU/VRAM usage guarantee

enum class Command { Help, Check, Render, Invalid };
Command command(int argc, const wchar_t* const* argv) {
    if (argc == 1) return Command::Help;
    if (argc == 2 && !std::wcscmp(argv[1], L"--self-check")) return Command::Check;
    // Only explicit --render plus an absolute drive-qualified DLL path may load the runtime.
    if (argc == 3 && !std::wcscmp(argv[1], L"--render")) {
        const wchar_t* p = argv[2];
        const bool drive = ((p[0]>=L'A' && p[0]<=L'Z') || (p[0]>=L'a' && p[0]<=L'z'));
        if (std::wcslen(p) >= 3 && drive && p[1] == L':' && (p[2] == L'\\' || p[2] == L'/'))
            return Command::Render;
    }
    return Command::Invalid;
}
void require(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
void selfcheck() {
    for (auto i : indices) require(i < 3, "index out of bounds");
    for (const auto& p : positions) for (float v : p) require(std::isfinite(v), "non-finite vertex");
    for (const auto& t : uv) for (float v : t) require(v>=0 && v<=1, "UV out of range");
    const float area = (positions[1][0]-positions[0][0])*(positions[2][1]-positions[0][1]) -
                       (positions[1][1]-positions[0][1])*(positions[2][0]-positions[0][0]);
    require(area > 0, "degenerate/reversed triangle");
    const wchar_t* help[] = {L"probe"};
    const wchar_t* check[] = {L"probe",L"--self-check"};
    const wchar_t* render[] = {L"probe",L"--render",L"C:\\isolated\\d3d9.dll"};
    const wchar_t* relative[] = {L"probe",L"--render",L"d3d9.dll"};
    const wchar_t* drive_relative[] = {L"probe",L"--render",L"C:d3d9.dll"};
    const wchar_t* missing[] = {L"probe",L"--render"};
    const wchar_t* empty[] = {L"probe",L"--render",L""};
    const wchar_t* unknown[] = {L"probe",L"--anything"};
    require(command(1,help)==Command::Help, "default must not render");
    require(command(2,check)==Command::Check, "self-check dispatch");
    require(command(3,render)==Command::Render, "explicit render dispatch");
    require(command(3,relative)==Command::Invalid, "relative DLL path accepted");
    require(command(3,drive_relative)==Command::Invalid, "drive-relative path accepted");
    require(command(2,missing)==Command::Invalid && command(3,empty)==Command::Invalid, "missing DLL path accepted");
    require(command(2,unknown)==Command::Invalid, "unknown option accepted");
}
} // namespace

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
// Keep the upstream Windows-only header unmodified; native CPU checks above do not include it.
#include <remix_c.h>

namespace {
// Diagnostic: find threads burning CPU and record where they are. Addresses are captured while the
// thread is suspended WITHOUT taking locks or allocating; names are resolved only after resuming it.
void print_address(DWORD64 address) {
    HMODULE module=nullptr; wchar_t path[MAX_PATH]=L"?";
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(address),&module) && module)
        GetModuleFileNameW(module,path,MAX_PATH);
    const wchar_t* name=std::wcsrchr(path,L'\\'); name=name?name+1:path;
    std::printf("    %ls+0x%llx\n",name,static_cast<unsigned long long>(address-reinterpret_cast<DWORD64>(module)));
}
void sample_thread(DWORD id) {
    HANDLE thread=OpenThread(THREAD_SUSPEND_RESUME|THREAD_GET_CONTEXT|THREAD_QUERY_INFORMATION,FALSE,id);
    if (!thread) return;
    DWORD64 frames[24]={}; unsigned count=0;
    if (SuspendThread(thread)!=static_cast<DWORD>(-1)) {
        CONTEXT ctx{}; ctx.ContextFlags=CONTEXT_FULL;
        if (GetThreadContext(thread,&ctx)) {
            for (; count<24 && ctx.Rip; ++count) {
                frames[count]=ctx.Rip;
                DWORD64 base=0;
                PRUNTIME_FUNCTION fn=RtlLookupFunctionEntry(ctx.Rip,&base,nullptr);
                if (fn) {
                    void* handler=nullptr; DWORD64 frame=0;
                    RtlVirtualUnwind(UNW_FLAG_NHANDLER,base,ctx.Rip,fn,&ctx,&handler,&frame,nullptr);
                } else {
                    DWORD64 ret=0; SIZE_T got=0;
                    if (!ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<void*>(ctx.Rsp),&ret,sizeof ret,&got)) break;
                    ctx.Rip=ret; ctx.Rsp+=8;
                }
            }
        }
        ResumeThread(thread);
    }
    CloseHandle(thread);
    std::printf("  thread %lu stack (%u frames):\n",id,count);
    for (unsigned i=0;i<count;++i) print_address(frames[i]);
}
DWORD main_thread_id=0;
DWORD WINAPI sampler(void*) {
    struct Seen { DWORD id; ULONGLONG cpu; } seen[256]={}; unsigned n=0;
    for (int round=0; round<6; ++round) {
        Sleep(round==0 ? 16000 : 10000);
        HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
        if (snap==INVALID_HANDLE_VALUE) continue;
        THREADENTRY32 te{}; te.dwSize=sizeof te;
        std::printf("[sampler round %d]\n",round);
        for (BOOL ok=Thread32First(snap,&te); ok; ok=Thread32Next(snap,&te)) {
            if (te.th32OwnerProcessID!=GetCurrentProcessId() || te.th32ThreadID==GetCurrentThreadId()) continue;
            HANDLE h=OpenThread(THREAD_QUERY_INFORMATION,FALSE,te.th32ThreadID);
            if (!h) continue;
            FILETIME c,e,k,u; ULONGLONG cpu=0;
            if (GetThreadTimes(h,&c,&e,&k,&u))
                cpu=((ULONGLONG(k.dwHighDateTime)<<32|k.dwLowDateTime)+(ULONGLONG(u.dwHighDateTime)<<32|u.dwLowDateTime))/10000;
            CloseHandle(h);
            unsigned i=0; while (i<n && seen[i].id!=te.th32ThreadID) ++i;
            const ULONGLONG before=i<n?seen[i].cpu:0;
            if (i==n && n<256) seen[n++]={te.th32ThreadID,cpu}; else if (i<n) seen[i].cpu=cpu;
            if (round>0 && cpu-before>=5000) {  // >=50% of a core over the 10 s window
                std::printf(" busy thread %lu%s: +%llu ms CPU\n",te.th32ThreadID,
                    te.th32ThreadID==main_thread_id?" (MAIN)":"",static_cast<unsigned long long>(cpu-before));
                for (int s=0;s<3;++s) { sample_thread(te.th32ThreadID); Sleep(40); }
            }
        }
        CloseHandle(snap);
        if (round>0) { std::printf(" main thread %lu:\n",main_thread_id); sample_thread(main_thread_id); }
    }
    return 0;
}
void stage(const char* operation) {
    std::printf("[%llu] begin %s\n",static_cast<unsigned long long>(GetTickCount64()),operation);
}
bool check(remixapi_ErrorCode code, const char* operation) {
    std::printf("[%llu] end %s -> %u\n",static_cast<unsigned long long>(GetTickCount64()),operation,static_cast<unsigned>(code));
    if (code == REMIXAPI_ERROR_CODE_SUCCESS) return true;
    std::fprintf(stderr, "%s failed: Remix API code %u\n", operation, static_cast<unsigned>(code));
    return false;
}
LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wp, LPARAM lp) {
    // Finish submissions before destroying our window; Runtime performs the final close before Shutdown.
    if (message == WM_CLOSE || message == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(window,message,wp,lp);
}
int render(const wchar_t* dll) {
    // The window guard outlives Runtime; Runtime may close it explicitly and clear this handle.
    struct Window {
        HWND handle=nullptr;
        ~Window() { if (handle && IsWindow(handle)) DestroyWindow(handle); }
    } window;
    // This branch is intentionally never run by build.py or on the laptop without approval.
    main_thread_id=GetCurrentThreadId();
    std::printf("main thread %lu\n",main_thread_id);
    if (HANDLE s=CreateThread(nullptr,0,sampler,nullptr,0,nullptr)) CloseHandle(s);
    remixapi_Interface api{};
    remixapi_HMODULE module = nullptr;
    stage("InitializeLibrary");
    if (!check(remixapi_lib_loadRemixDllAndInitialize(dll,&api,&module), "InitializeLibrary")) return 1;
    struct Runtime {
        remixapi_Interface& api; remixapi_HMODULE module; HWND& window;
        ~Runtime() {
            if (window && IsWindow(window)) {
                stage("DestroyWindow before Shutdown");
                const BOOL destroyed=DestroyWindow(window);
                std::printf("end DestroyWindow -> %d\n",static_cast<int>(destroyed));
                if (destroyed) window=nullptr;
            }
            stage("Shutdown API");
            if (api.Shutdown) check(api.Shutdown(),"Shutdown API");
            stage("FreeLibrary");
            const BOOL released=FreeLibrary(module);
            std::printf("end FreeLibrary -> %d\n",static_cast<int>(released));
        }
    } runtime{api,module,window.handle};
    if (!api.Startup || !api.Shutdown || !api.CreateMaterial || !api.CreateMesh || !api.CreateLight ||
        !api.SetupCamera || !api.DrawInstance || !api.DrawLightInstance || !api.Present ||
        !api.DestroyLight || !api.DestroyMesh || !api.DestroyMaterial) {
        std::fprintf(stderr,"Required API function missing; use a matching SDK/runtime build.\n"); return 1;
    }
    WNDCLASSW wc{}; wc.lpfnWndProc=window_proc; wc.hInstance=GetModuleHandleW(nullptr);
    wc.lpszClassName=L"NierRemixStandaloneProbe";
    if (!RegisterClassW(&wc)) { std::fprintf(stderr,"RegisterClass error %lu\n",GetLastError()); return 1; }
    RECT rect{0,0,512,512}; AdjustWindowRect(&rect,WS_OVERLAPPEDWINDOW,FALSE);
    window.handle=CreateWindowW(wc.lpszClassName,L"Standalone Remix triangle - NOT NieR",WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT,CW_USEDEFAULT,rect.right-rect.left,rect.bottom-rect.top,nullptr,nullptr,wc.hInstance,nullptr);
    if (!window.handle) { std::fprintf(stderr,"CreateWindow error %lu\n",GetLastError()); return 1; }
    ShowWindow(window.handle,SW_SHOW);
    remixapi_StartupInfo startup{};
    startup.sType=REMIXAPI_STRUCT_TYPE_STARTUP_INFO; startup.hwnd=window.handle;
    startup.combineGuiInFinalColor=1;
    stage("Startup");
    if (!check(api.Startup(&startup),"Startup")) return 1;

    remixapi_MaterialInfoOpaqueEXT opaque{};
    opaque.sType=REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    opaque.albedoConstant={0.9f,0.35f,0.08f}; opaque.opacityConstant=1; opaque.roughnessConstant=0.6f;
    remixapi_MaterialInfo material{};
    material.sType=REMIXAPI_STRUCT_TYPE_MATERIAL_INFO; material.pNext=&opaque; material.hash=1;
    // A weak emissive component keeps the triangle identifiable even if light conventions need adjustment.
    material.emissiveIntensity=0.2f; material.emissiveColorConstant={0.9f,0.35f,0.08f};
    remixapi_MaterialHandle mat=nullptr;
    stage("CreateMaterial");
    if (!check(api.CreateMaterial(&material,&mat),"CreateMaterial") || !mat) return 1;
    remixapi_HardcodedVertex vertices[3]{};
    static_assert(sizeof(remixapi_HardcodedVertex)==64, "pinned SDK vertex layout changed");
    for (unsigned i=0;i<3;++i) {
        for (unsigned k=0;k<3;++k) vertices[i].position[k]=positions[i][k];
        vertices[i].normal[2]=-1;
        for (unsigned k=0;k<2;++k) vertices[i].texcoord[k]=uv[i][k];
        vertices[i].color=0xffffffff;
    }
    remixapi_MeshInfoSurfaceTriangles surface{};
    surface.vertices_values=vertices; surface.vertices_count=3;
    // Match the official sample's non-indexed/default-material surface to isolate scene setup.
    surface.indices_values=nullptr; surface.indices_count=0; surface.material=nullptr;
    remixapi_MeshInfo mesh_info{};
    mesh_info.sType=REMIXAPI_STRUCT_TYPE_MESH_INFO; mesh_info.hash=2;
    mesh_info.surfaces_values=&surface; mesh_info.surfaces_count=1;
    remixapi_MeshHandle mesh=nullptr;
    stage("CreateMesh");
    if (!check(api.CreateMesh(&mesh_info,&mesh),"CreateMesh") || !mesh) return 1;
    remixapi_LightInfoSphereEXT sphere{};
    sphere.sType=REMIXAPI_STRUCT_TYPE_LIGHT_INFO_SPHERE_EXT;
    sphere.position={0,-1,0}; sphere.radius=0.1f;
    remixapi_LightInfo light_info{};
    light_info.sType=REMIXAPI_STRUCT_TYPE_LIGHT_INFO; light_info.pNext=&sphere;
    light_info.hash=3; light_info.radiance={100,200,100};
    remixapi_LightHandle light=nullptr;
    stage("CreateLight");
    if (!check(api.CreateLight(&light_info,&light),"CreateLight") || !light) return 1;
    remixapi_CameraInfoParameterizedEXT params{};
    params.sType=REMIXAPI_STRUCT_TYPE_CAMERA_INFO_PARAMETERIZED_EXT;
    params.position={0,0,0}; params.forward={0,0,1}; params.up={0,1,0}; params.right={1,0,0};
    params.fovYInDegrees=70; params.aspect=1; params.nearPlane=0.1f; params.farPlane=1000;
    remixapi_CameraInfo camera{};
    camera.sType=REMIXAPI_STRUCT_TYPE_CAMERA_INFO; camera.pNext=&params; camera.type=REMIXAPI_CAMERA_TYPE_WORLD;
    remixapi_InstanceInfo instance{};
    instance.sType=REMIXAPI_STRUCT_TYPE_INSTANCE_INFO; instance.mesh=mesh; instance.doubleSided=1;
    for (unsigned i=0;i<3;++i) instance.transform.matrix[i][i]=1;
    instance.transform.matrix[2][3]=5;

    unsigned submitted=0;
    for (;submitted<frames;++submitted) {
        MSG msg{}; bool quit=false;
        while (PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)) {
            if (msg.message==WM_QUIT) quit=true;
            TranslateMessage(&msg); DispatchMessageW(&msg);
        }
        if (quit || !IsWindow(window.handle)) break;
        std::printf("Frame %u\n",submitted);
        stage("SetupCamera"); if (!check(api.SetupCamera(&camera),"SetupCamera")) return 1;
        stage("DrawInstance"); if (!check(api.DrawInstance(&instance),"DrawInstance")) return 1;
        stage("DrawLightInstance"); if (!check(api.DrawLightInstance(light),"DrawLightInstance")) return 1;
        stage("Present"); if (!check(api.Present(nullptr),"Present")) return 1;
        Sleep(frame_delay_ms);
    }
    std::printf("Submitted %u Remix frames. API success is NOT visual correctness; inspect the window.\n",submitted);
    stage("DestroyLight"); if (!check(api.DestroyLight(light),"DestroyLight")) return 1;
    stage("DestroyMesh"); if (!check(api.DestroyMesh(mesh),"DestroyMesh")) return 1;
    stage("DestroyMaterial"); if (!check(api.DestroyMaterial(mat),"DestroyMaterial")) return 1;
    return 0; // No assets/files are edited by this program.
}
} // namespace

int wmain(int argc, wchar_t** argv) {
    std::setvbuf(stdout,nullptr,_IONBF,0);
    std::setvbuf(stderr,nullptr,_IONBF,0);
    try {
        selfcheck();
        const auto mode=command(argc,argv);
        if (mode==Command::Check) { std::puts("CPU self-check passed; no runtime loaded."); return 0; }
        if (mode==Command::Render) return render(argv[2]);
        std::puts("Default: no runtime loaded.\n--self-check: CPU checks only.\n"
                  "--render C:\\absolute\\runtime\\d3d9.dll: REAL GPU WORK. Requires separate approval.\n"
                  "Run only from an isolated working folder, never the game folder. No game needed.");
        return mode==Command::Invalid ? 2 : 0;
    } catch (const std::exception& error) { std::fprintf(stderr,"%s\n",error.what()); return 1; }
}
#else
int main() {
    try { selfcheck(); std::puts("CPU scene/argument checks passed; Windows renderer not executed."); return 0; }
    catch (const std::exception& error) { std::fprintf(stderr,"%s\n",error.what()); return 1; }
}
#endif

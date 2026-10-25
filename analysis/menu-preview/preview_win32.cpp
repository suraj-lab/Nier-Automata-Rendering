// Standalone host based on Dear ImGui's MIT example_win32_directx11 (see vendor notices).
#include "panel.h"
#include "backends/imgui_impl_win32.h"
#include "backends/imgui_impl_dx11.h"
#include <windows.h>
#include <d3d11.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

static ID3D11Device* device;
static ID3D11DeviceContext* context;
static IDXGISwapChain* swapchain;
static ID3D11RenderTargetView* target;
static std::unique_ptr<render_menu::State> state;
static int simulated_result = 0;  // 0 committed, 1 not saved, 2 recovery required (F5 cycles)
static unsigned save_calls = 0;
static menu_preview::SaveReport simulated_save(render_settings::Mode mode, void*) {
    ++save_calls;
    using render_menu::FileState; using render_menu::SaveOutcome;
    if (simulated_result == 1) return {SaveOutcome::NotSaved, state->file, state->saved};
    if (simulated_result == 2) return {SaveOutcome::RecoveryRequired, FileState::Missing, render_settings::Mode::Custom75};
    return {SaveOutcome::Committed, FileState::Valid, mode};
}
extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND, UINT, WPARAM, LPARAM);

static bool render_target() {
    ID3D11Texture2D* buffer = nullptr;
    if (FAILED(swapchain->GetBuffer(0,IID_PPV_ARGS(&buffer)))) return false;
    const HRESULT result = device->CreateRenderTargetView(buffer,nullptr,&target);
    buffer->Release(); return SUCCEEDED(result);
}
static void cleanup() {
    if (target) { target->Release(); target=nullptr; }
    if (swapchain) { swapchain->Release(); swapchain=nullptr; }
    if (context) { context->Release(); context=nullptr; }
    if (device) { device->Release(); device=nullptr; }
}
static bool create_device(HWND hwnd) {
    DXGI_SWAP_CHAIN_DESC desc{};
    desc.BufferCount=2;desc.BufferDesc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;desc.OutputWindow=hwnd;
    desc.SampleDesc.Count=1;desc.Windowed=TRUE;desc.SwapEffect=DXGI_SWAP_EFFECT_DISCARD;
    const D3D_FEATURE_LEVEL levels[]={D3D_FEATURE_LEVEL_11_0,D3D_FEATURE_LEVEL_10_0};
    D3D_FEATURE_LEVEL level;
    HRESULT result=D3D11CreateDeviceAndSwapChain(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,levels,2,
        D3D11_SDK_VERSION,&desc,&swapchain,&device,&level,&context);
    if (result==DXGI_ERROR_UNSUPPORTED)
        result=D3D11CreateDeviceAndSwapChain(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,levels,2,
            D3D11_SDK_VERSION,&desc,&swapchain,&device,&level,&context);
    return SUCCEEDED(result) && render_target();
}
static LRESULT WINAPI window_proc(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp) {
    if (ImGui::GetCurrentContext()) {
        if (msg==WM_KEYDOWN && !(lp & (1LL<<30))) {
            if (wp==VK_INSERT) menu_preview::key_event(*state,ImGuiKey_Insert);
            if (wp==VK_ESCAPE) menu_preview::key_event(*state,ImGuiKey_Escape);
            if (wp==VK_F5) simulated_result=(simulated_result+1)%3; // Preview-only simulator, never part of the game UI.
        }
        if (ImGui_ImplWin32_WndProcHandler(hwnd,msg,wp,lp)) return 1;
    }
    if (msg==WM_SIZE && device && wp!=SIZE_MINIMIZED) {
        context->OMSetRenderTargets(0,nullptr,nullptr);
        if (target) { target->Release();target=nullptr; }
        if (FAILED(swapchain->ResizeBuffers(0,LOWORD(lp),HIWORD(lp),DXGI_FORMAT_UNKNOWN,0)) || !render_target())
            PostQuitMessage(1);
        return 0;
    }
    if (msg==WM_DESTROY) { PostQuitMessage(0);return 0; }
    if (msg==WM_SYSCOMMAND && (wp&0xfff0)==SC_KEYMENU) return 0;
    return DefWindowProcW(hwnd,msg,wp,lp);
}
static bool write_new(const wchar_t* name,const void* data,DWORD size) {
    HANDLE file=CreateFileW(name,GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if (file==INVALID_HANDLE_VALUE) return false;
    DWORD written=0;
    const bool ok=WriteFile(file,data,size,&written,nullptr) && written==size;
    const bool closed=CloseHandle(file)!=FALSE;
    return ok && closed;
}
static bool capture(const menu_preview::Geometry& g) {
    ID3D11Texture2D* buffer=nullptr;
    if (FAILED(swapchain->GetBuffer(0,IID_PPV_ARGS(&buffer)))) return false;
    D3D11_TEXTURE2D_DESC desc{};buffer->GetDesc(&desc);
    if (!desc.Width || !desc.Height || desc.Width>8192 || desc.Height>8192 ||
        desc.Format!=DXGI_FORMAT_R8G8B8A8_UNORM) { buffer->Release();return false; }
    desc.Usage=D3D11_USAGE_STAGING;desc.BindFlags=0;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;desc.MiscFlags=0;
    ID3D11Texture2D* staging=nullptr;
    if (FAILED(device->CreateTexture2D(&desc,nullptr,&staging))) { buffer->Release();return false; }
    context->CopyResource(staging,buffer);buffer->Release();
    D3D11_MAPPED_SUBRESOURCE mapped{};
    if (FAILED(context->Map(staging,0,D3D11_MAP_READ,0,&mapped))) { staging->Release();return false; }
    const DWORD bytes=desc.Width*desc.Height*4;
    BITMAPFILEHEADER header{};header.bfType=0x4D42;header.bfOffBits=sizeof(header)+sizeof(BITMAPINFOHEADER);header.bfSize=header.bfOffBits+bytes;
    BITMAPINFOHEADER info{};info.biSize=sizeof(info);info.biWidth=desc.Width;info.biHeight=-static_cast<LONG>(desc.Height);
    info.biPlanes=1;info.biBitCount=32;info.biCompression=BI_RGB;info.biSizeImage=bytes;
    std::vector<unsigned char> output(header.bfSize);
    std::memcpy(output.data(),&header,sizeof(header));std::memcpy(output.data()+sizeof(header),&info,sizeof(info));
    for (UINT y=0;y<desc.Height;++y) {
        const auto* src=static_cast<const unsigned char*>(mapped.pData)+y*mapped.RowPitch;
        auto* dst=output.data()+header.bfOffBits+y*desc.Width*4;
        for (UINT x=0;x<desc.Width;++x) { dst[4*x]=src[4*x+2];dst[4*x+1]=src[4*x+1];dst[4*x+2]=src[4*x];dst[4*x+3]=255; }
    }
    context->Unmap(staging,0);staging->Release();
    char metrics[1024];
    const int count=std::snprintf(metrics,sizeof(metrics),
        "{\"simulated\":true,\"width\":%u,\"height\":%u,\"panel\":[%.2f,%.2f,%.2f,%.2f],\"save\":[%.2f,%.2f,%.2f,%.2f],\"body_scroll_max\":%.2f,\"save_calls\":%u}\n",
        desc.Width,desc.Height,g.panel.min.x,g.panel.min.y,g.panel.max.x,g.panel.max.y,
        g.save.min.x,g.save.min.y,g.save.max.x,g.save.max.y,g.body_scroll_max,save_calls);
    return count>0 && count<static_cast<int>(sizeof(metrics)) && write_new(L"capture.bmp",output.data(),static_cast<DWORD>(output.size())) &&
        write_new(L"metrics.json",metrics,static_cast<DWORD>(count));
}

int main(int argc,char** argv) {
    std::fprintf(stderr,"preview: main entered\n");std::fflush(stderr);
    float scale=1;int width=1920,height=1080;bool capture_mode=false;std::string scenario="custom75";
    for (int i=1;i<argc;++i) {
        const std::string arg=argv[i];
        if (arg=="--capture") capture_mode=true;
        else if (arg=="--scale=1") scale=1;
        else if (arg=="--scale=1.5") scale=1.5f;
        else if (arg=="--scale=2") scale=2;
        else if (arg=="--viewport=1920x1080") { width=1920;height=1080; }
        else if (arg=="--viewport=3440x1440") { width=3440;height=1440; }
        else if (arg.rfind("--case=",0)==0) scenario=arg.substr(7);
        else { std::fprintf(stderr,"Unknown argument: %s\n",arg.c_str());return 2; }
    }
    static const char* const known[]={"custom75","native","startup-fail","dirty","saved","save-fail","closed",
        "missing-file","invalid-file","unreadable-file","recovery"};
    if (std::find(std::begin(known),std::end(known),scenario)==std::end(known)) {
        std::fprintf(stderr,"Unknown scenario\n");return 2;
    }
    using render_menu::FileState; using render_settings::Mode;
    const bool bad_file=scenario=="invalid-file" || scenario=="unreadable-file";
    const bool native=scenario=="native" || bad_file,failed=scenario=="startup-fail";
    const FileState file=scenario=="missing-file" ? FileState::Missing : scenario=="invalid-file" ? FileState::Invalid :
        scenario=="unreadable-file" ? FileState::Unreadable : FileState::Valid;
    state=std::make_unique<render_menu::State>(failed ? render_menu::SessionMode::NotApplied :
        native ? render_menu::SessionMode::Native : render_menu::SessionMode::Custom75,
        file,native ? Mode::Native : Mode::Custom75,!native || bad_file);
    state->open=scenario!="closed";
    if (scenario=="dirty" || scenario=="saved" || scenario=="save-fail" || scenario=="recovery") render_menu::select(*state,Mode::Native);
    if (scenario=="saved") render_menu::complete_save(*state,render_menu::SaveOutcome::Committed,FileState::Valid,Mode::Native);
    if (scenario=="save-fail") { render_menu::complete_save(*state,render_menu::SaveOutcome::NotSaved,FileState::Valid,Mode::Custom75);simulated_result=1; }
    if (scenario=="recovery") render_menu::complete_save(*state,render_menu::SaveOutcome::RecoveryRequired,FileState::Missing,Mode::Custom75);
    ImGui_ImplWin32_EnableDpiAwareness();
    WNDCLASSEXW wc{};wc.cbSize=sizeof(wc);wc.style=CS_CLASSDC;wc.lpfnWndProc=window_proc;
    wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"NierRenderIsolatedPreview";
    if (!RegisterClassExW(&wc)) return 3;
    RECT rect{0,0,width,height};AdjustWindowRect(&rect,WS_OVERLAPPEDWINDOW,FALSE);
    HWND hwnd=CreateWindowW(wc.lpszClassName,L"NIER RENDER — ISOLATED SIMULATION (no game attached)",WS_OVERLAPPEDWINDOW,
        0,0,rect.right-rect.left,rect.bottom-rect.top,nullptr,nullptr,wc.hInstance,nullptr);
    std::fprintf(stderr,"preview: creating D3D11 device\n");std::fflush(stderr);
    if (!hwnd || !create_device(hwnd)) { std::fprintf(stderr,"D3D11 preview creation failed\n");cleanup();return 3; }
    ShowWindow(hwnd,SW_SHOWDEFAULT);UpdateWindow(hwnd);
    IMGUI_CHECKVERSION();ImGui::CreateContext();
    auto& io=ImGui::GetIO();io.IniFilename=nullptr;io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard;
    menu_preview::Fonts fonts;
    try {
        wchar_t exe[32768];const DWORD n=GetModuleFileNameW(nullptr,exe,32768);
        if (!n || n>=32768) throw std::runtime_error("Cannot locate preview fonts");
        std::fprintf(stderr,"preview: loading fonts\n");std::fflush(stderr);
        menu_preview::apply_style(scale);
        fonts=menu_preview::load_fonts(std::filesystem::path(exe).parent_path()/L"fonts",scale);
    } catch (const std::exception& error) {
        std::fprintf(stderr,"%s\n",error.what());ImGui::DestroyContext();cleanup();DestroyWindow(hwnd);return 4;
    }
    std::fprintf(stderr,"preview: initializing backends\n");std::fflush(stderr);
    const bool platform_ready=ImGui_ImplWin32_Init(hwnd);
    const bool renderer_ready=platform_ready && ImGui_ImplDX11_Init(device,context);
    if (!renderer_ready) {
        if (platform_ready) ImGui_ImplWin32_Shutdown();
        ImGui::DestroyContext();cleanup();DestroyWindow(hwnd);UnregisterClassW(wc.lpszClassName,wc.hInstance);return 5;
    }
    menu_preview::RuntimeInfo data{native ? "AA BACKEND UNKNOWN · D3D11 · WINDOWS (CONCEPT)" : "FSR 4.1.1 · D3D11 · PROTON (FIXTURE)",
        native ? nullptr : "2580×1080","3440×1440","Simulated prerequisite failure; no patches attempted."};
    int exit_code=0;unsigned frames=0;bool done=false;
    while (!done) {
        MSG msg;
        while (PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)) {
            TranslateMessage(&msg);DispatchMessageW(&msg);
            if (msg.message==WM_QUIT) { done=true;exit_code=static_cast<int>(msg.wParam); }
        }
        if (done || !target) break;
        ImGui_ImplDX11_NewFrame();ImGui_ImplWin32_NewFrame();ImGui::NewFrame();
        menu_preview::Geometry geometry;
        menu_preview::draw_panel(*state,data,fonts,scale,simulated_save,nullptr,&geometry);
        ImGui::GetBackgroundDrawList()->AddText(fonts.items[menu_preview::Mono],fonts.items[menu_preview::Mono]->FontSize,
            ImVec2(24,io.DisplaySize.y-40),IM_COL32(200,210,195,255),
            "ISOLATED PREVIEW / simulated session / no game or settings I/O / F5: cycle simulated save result");
        ImGui::Render();
        const float background[]={0.114f,0.141f,0.133f,1};
        context->OMSetRenderTargets(1,&target,nullptr);context->ClearRenderTargetView(target,background);
        ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
        if (capture_mode && ++frames==4) {
            std::fprintf(stderr,"preview: capturing fourth frame\n");std::fflush(stderr);
            exit_code=capture(geometry) ? 0 : 6;done=true;
        }
        const HRESULT result=swapchain->Present(1,0);
        if (FAILED(result)) { exit_code=7;done=true; }
    }
    ImGui_ImplDX11_Shutdown();ImGui_ImplWin32_Shutdown();ImGui::DestroyContext();cleanup();
    DestroyWindow(hwnd);UnregisterClassW(wc.lpszClassName,wc.hInstance);
    return exit_code;
}

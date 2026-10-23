set pagination off
set confirm off
set print thread-events off
set debuginfod enabled off
set auto-load off
set startup-with-shell off
set disable-randomization off
set follow-fork-mode parent
handle SIGUSR1 nostop noprint pass
handle SIGUSR2 nostop noprint pass
handle SIGSEGV nostop noprint pass
handle SIGILL nostop noprint pass
handle SIGFPE nostop noprint pass
set environment PATH=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/protonfixes/files/bin:/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/bin/:/home/suraj/.npm-global/bin:/home/suraj/.local/share/zinit/polaris/bin:/home/suraj/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/var/lib/flatpak/exports/bin:/usr/bin/site_perl:/usr/bin/vendor_perl:/usr/bin/core_perl:/opt/rocm/bin:/usr/lib/rustup/bin:/home/suraj/.lmstudio/bin:/home/suraj/.lmstudio/bin
set environment HOME=/home/suraj
set environment USER=suraj
set environment LOGNAME=suraj
set environment SHELL=/usr/bin/zsh
set environment DISPLAY=:1
set environment WAYLAND_DISPLAY=wayland-1
set environment XDG_RUNTIME_DIR=/run/user/1000
set environment DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
set environment LANG=en_US.UTF-8
set environment LC_CTYPE=C.UTF-8
set environment STEAM_COMPAT_DATA_PATH=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runtime/proton-sk-wait-debug
set environment STEAM_COMPAT_CLIENT_INSTALL_PATH=/home/suraj/.local/share/Steam
set environment STEAM_COMPAT_INSTALL_PATH=/home/suraj/Projects/Nier-Automata-Rendering/analysis/visual-stack/sk-native-gdb
set environment SteamAppId=0
set environment SteamGameId=0
set environment WINEDEBUG=-all
set environment WINEDLLOVERRIDES=d3d11=n,b;dxgi=n,b;mscoree,mshtml=;steam.exe=b;dotnetfx35.exe=b;dotnetfx35setup.exe=b;beclient.dll=b,n;beclient_x64.dll=b,n;winebth.sys=d;opencl=n,d;d3d11=n;d3d10core=n;d3d9=n;dxgi=n;d3d12=n;d3d12core=n;nvapi64=n;nvofapi64=n;nvapi=n;nvcuda=b
set environment DXVK_LOG_PATH=/home/suraj/Projects/Nier-Automata-Rendering/analysis/evidence/sk-native-gdb/direct64
set environment MESA_SHADER_CACHE_DIR=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runtime/shadercache
set environment PROTON_LOG=1
set environment PROTON_LOG_DIR=/home/suraj/Projects/Nier-Automata-Rendering/analysis/evidence/sk-native-gdb/direct64
set environment XDG_CACHE_HOME=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runtime/visual-stack-cache
set environment PROTON_PIPEWIRE_ALSA_PLUGIN=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/lib/x86_64-linux-gnu/alsa-lib/libasound_module_pcm_pipewire.so
set environment XLOCALEDIR=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/share/X11/locale
set environment ORIG_LD_LIBRARY_PATH=
set environment LD_LIBRARY_PATH=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/protonfixes/files/lib/x86_64-linux-gnu:/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/protonfixes/files/lib/aarch64-linux-gnu:/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/protonfixes/files/lib/i386-linux-gnu:/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/lib/x86_64-linux-gnu:/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/lib/i386-linux-gnu
set environment WINEDLLPATH=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/lib/vkd3d:/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/lib/wine
set environment MEDIACONV_BLANK_VIDEO_FILE=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/share/media/blank.mkv
set environment MEDIACONV_BLANK_AUDIO_FILE=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/share/media/blank.ptna
set environment ESPEAK_DATA_PATH=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runners/GE-Proton11-7-x86_64/files/share
set environment WINEPREFIX=/home/suraj/Projects/Nier-Automata-Rendering/analysis/runtime/proton-sk-wait-debug/pfx/
set environment DXVK_LOG_LEVEL=info
set environment DXVK_NVAPI_LOG_LEVEL=info
set environment VKD3D_DEBUG=warn
set environment VKD3D_SHADER_DEBUG=fixme
set environment WINE_MONO_TRACE=E:System.NotImplementedException
set environment WINENTSYNC=1
set environment WINEESYNC=1
set environment WINEFSYNC=1
set environment WINE_LARGE_ADDRESS_AWARE=1
set environment PROTON_USE_XALIA=1
set environment XALIA_SUPPORTED_ONLY=1
set environment INTC_ALT_DRIVER_EXTENSIONS_PATH=C:\Windows\System32
set environment __GLVND_DISALLOW_PATCHING=1
set environment WINE_MONO_HIDETYPES=0
set environment DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS=DLSSIndicator=0,DLSSGIndicator=0,
set environment DXVK_ENABLE_NVAPI=1
set environment GNUTLS_SYSTEM_PRIORITY_FILE=/dev/null
set environment LC_MESSAGES=en_US.UTF-8
set environment PROTON_EAC_RUNTIME=/home/suraj/.local/share/Steam/steamapps/common/Proton EasyAntiCheat Runtime
handle SIGSYS nostop noprint pass
run
echo \nWAIT_SNAPSHOT\n
info inferiors
thread apply all bt 25
info proc mappings
detach
quit

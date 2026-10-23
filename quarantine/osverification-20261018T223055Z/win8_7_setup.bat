@echo off
::This will remove NieRAutomata, leaving only the Windows 7, 8, 8.1 executable. This is then renamed.
IF EXIST "NieRAutomataCompat.exe" (
DEL /Q /F NieRAutomata.exe
REN NieRAutomataCompat.exe NieRAutomata.exe
)
DEL /Q /F installation_os_check.vdf
DEL /Q /F win10setup.bat
DEL /Q /F win8_7_setup.bat
EXIT 1
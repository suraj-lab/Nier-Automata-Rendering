// File-backed output: the upstream test's console output was not captured under Proton.
#define main upstream_main
#include "../../upstream/Nier-FSR4/tests/smoke.cpp"
#undef main

int main(int argc, char** argv)
{
    if (!freopen("abi-check-results.txt", "w", stdout))
        return 2;
    const int result = upstream_main(argc, argv);
    printf("RESULT exit=%d\n", result);
    if (fclose(stdout) != 0)
        return 2;
    return result;
}

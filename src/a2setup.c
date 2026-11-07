/* SPDX-License-Identifier: GPL-3.0-only */
/* Runs the original setup and closes the folder windows it opens.
   Usage: a2setup.exe <setup.exe> [arguments...]
   At the end, the InstallShield setup shows its Start menu group in a Wine Explorer window. That
   window keeps the prefix busy, and Proton, and with it the Lutris installer, waits until it is
   closed by hand. a2setup.exe starts the setup in its own folder, waits for it and every process it
   starts (InstallShield runs its engine as a child process), closes Explorer folder windows in the
   meantime and for a few seconds afterwards, and returns the setup's exit code. */
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_TRACKED 256

static DWORD tracked[MAX_TRACKED];
static int ntracked;

static int is_tracked(DWORD pid) {
    for (int i = 0; i < ntracked; i++) if (tracked[i] == pid) return 1;
    return 0;
}

/* Adds new descendants of the tracked processes; returns 1 if any tracked process still runs. */
static int setup_running(void) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32 pe; pe.dwSize = sizeof pe;
    int running = 0, added;
    do {  /* repeat, so that grandchildren listed before their parent are found too */
        added = 0;
        for (BOOL ok = Process32First(snap, &pe); ok; ok = Process32Next(snap, &pe))
            if (!is_tracked(pe.th32ProcessID) && is_tracked(pe.th32ParentProcessID) &&
                _stricmp(pe.szExeFile, "explorer.exe") != 0 && ntracked < MAX_TRACKED) {
                tracked[ntracked++] = pe.th32ProcessID; added = 1;
            }
    } while (added);
    for (BOOL ok = Process32First(snap, &pe); ok; ok = Process32Next(snap, &pe))
        if (is_tracked(pe.th32ProcessID)) running = 1;
    CloseHandle(snap);
    return running;
}

static BOOL CALLBACK close_folder(HWND w, LPARAM closed) {
    char cls[64];
    if (GetClassNameA(w, cls, sizeof cls) &&
        (!strcmp(cls, "ExplorerWClass") || !strcmp(cls, "CabinetWClass"))) {
        PostMessageA(w, WM_CLOSE, 0, 0);
        (*(int *)closed)++;
    }
    return TRUE;
}

static void close_folders(void) {
    int closed = 0;
    EnumWindows(close_folder, (LPARAM)&closed);
    if (closed) { printf("a2setup: closed %d folder window(s)\n", closed); fflush(stdout); }
}

int main(void) {
    char *cmd = GetCommandLineA();
    if (*cmd == '"') { cmd = strchr(cmd + 1, '"'); cmd = cmd ? cmd + 1 : ""; }
    else { while (*cmd && *cmd != ' ') cmd++; }
    while (*cmd == ' ') cmd++;
    if (!*cmd) { fprintf(stderr, "Usage: a2setup.exe setup.exe [arguments]\n"); return 2; }

    /* program path with backslashes (Lutris gets D:/SETUP.EXE, since its argument parsing would
       drop backslashes); working directory = folder of the setup, it finds its files there */
    char prog[MAX_PATH], dir[MAX_PATH];
    int quoted = *cmd == '"';
    const char *start = cmd + quoted, *end = strchr(start, quoted ? '"' : ' ');
    size_t len = end ? (size_t)(end - start) : strlen(start);
    const char *rest = end ? end + quoted : "";
    if (len >= sizeof prog) { fprintf(stderr, "a2setup: path too long\n"); return 2; }
    memcpy(prog, start, len); prog[len] = 0;
    for (char *p = prog; *p; p++) if (*p == '/') *p = '\\';
    char *line = malloc(len + strlen(rest) + 3);
    if (!line) return 1;
    sprintf(line, "\"%s\"%s", prog, rest);
    strcpy(dir, prog);
    char *slash = strrchr(dir, '\\');
    if (slash) { *slash = 0; SetCurrentDirectoryA(dir); }

    STARTUPINFOA si; PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof si); si.cb = sizeof si;
    if (!CreateProcessA(NULL, line, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
        fprintf(stderr, "a2setup: could not start %s (error %lu)\n", line, GetLastError());
        return 1;
    }
    tracked[ntracked++] = pi.dwProcessId;
    while (setup_running()) { close_folders(); Sleep(300); }
    /* the folder window may only open after the setup has ended */
    for (int i = 0; i < 20; i++) { close_folders(); Sleep(250); }

    DWORD code = 0; GetExitCodeProcess(pi.hProcess, &code);
    printf("a2setup: setup finished with exit code %lu\n", code);
    return (int)code;
}

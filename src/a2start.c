/* SPDX-License-Identifier: GPL-3.0-only */
/* Starts a program after switching the display to 640x480 with 16-bit color depth.
   Usage: a2start.exe <program.exe> [arguments...]
   Anstoss 2 checks for hicolor mode before switching modes itself.
   The game is started suspended and patched in memory to work around Wine differences
   (see the patch_* functions). The .exe file on disk stays unchanged. Two builds of the game are
   known: anstoss2.exe of the 1999 CD and run.exe of the 2007 release, the same code at different
   addresses (struct version); run.exe of GOG and of the 2007 CD (unpacked by src/a2unpack.py)
   differ only in the addresses of their import slots. Each patch first checks that the bytes match
   exactly; results are written to a2start.log. Addresses in the comments are those of the CD version. */
#include <windows.h>
#include <stdio.h>
#include <string.h>

static void logf_(const char *msg, long v) {
    FILE *f = fopen("a2start.log", "a");
    if (f) { fprintf(f, "%s %ld\n", msg, v); fclose(f); }
}

/* Patch addresses of one build of the game */
struct version {
    const char *name;
    DWORD indeo;                               /* "IR32" */
    DWORD font[16];                            /* width operands, see patch_fonts */
    DWORD anim_at, anim_call, iat_setwindowpos;
    DWORD drawdib_site[2], drawdib_thunk;
    DWORD avipal;
    DWORD wide_at, wide_face, iat_getmodulehandle, iat_getprocaddress, wide_face_push[3];
    DWORD bits_site, iat_getbitmapbits, iat_getdibits, iat_getdc, iat_releasedc;
    DWORD calc_init;                           /* see patch_calcinit */
    DWORD btn_ctor_end, btn_vtable;            /* see patch_btninit */
};

static const struct version versions[] = {
    { "anstoss2.exe (CD, 08.07.1999)", 0x6ab9e0,
      { 0x573766, 0x573795, 0x5737c4, 0x5737f3, 0x573822, 0x573851, 0x573880, 0x5738af, 0x5738de,
        0x57390d, 0x57393c, 0x57396b, 0x5739c6, 0x5e8c4e, 0x60b716, 0x616b26 },
      0x40a4c8, 0x66faf7, 0x677518,
      { 0x4675cc, 0x639a6d }, 0x6554da,
      0x418dc2,
      0x573740, 0x6bece8, 0x677220, 0x677224, { 0x5738ee, 0x57391d, 0x5739a7 },
      0x419ee2, 0x6770b0, 0x6770f0, 0x6775f8, 0x6775e8,
      0x4a513f,
      0x5bc43a, 0x69ba78 },
    { "run.exe (GOG)", 0x6ae9e0,
      { 0x575a16, 0x575a45, 0x575a74, 0x575aa3, 0x575ad2, 0x575b01, 0x575b30, 0x575b5f, 0x575b8e,
        0x575bbd, 0x575bec, 0x575c1b, 0x575c76, 0x5ec5ee, 0x6102a6, 0x61b6b6 },
      0x40a4c8, 0x674927, 0xcbaca0,
      { 0x4696cc, 0x63e5ad }, 0x65a30a,
      0x41a012,
      0x5759f0, 0x6c1de8, 0xcba6f8, 0xcba6fc, { 0x575b9e, 0x575bcd, 0x575c57 },
      0x41b132, 0xcba364, 0xcba3a4, 0xcbad80, 0xcbad70,
      0x4a733f,
      0x5bf16a, 0x6a0a78 },
    { "run.exe (2007 CD)", 0x6ae9e0,
      { 0x575a16, 0x575a45, 0x575a74, 0x575aa3, 0x575ad2, 0x575b01, 0x575b30, 0x575b5f, 0x575b8e,
        0x575bbd, 0x575bec, 0x575c1b, 0x575c76, 0x5ec5ee, 0x6102a6, 0x61b6b6 },
      0x40a4c8, 0x674927, 0x67c518,
      { 0x4696cc, 0x63e5ad }, 0x65a30a,
      0x41a012,
      0x5759f0, 0x6c1de8, 0x67c220, 0x67c224, { 0x575b9e, 0x575bcd, 0x575c57 },
      0x41b132, 0x67c0b0, 0x67c0f0, 0x67c5f8, 0x67c5e8,
      0x4a733f,
      0x5bf16a, 0x6a0a78 },
};

/* The build whose menu font function starts with "push esi; push <face name>" and which calls
   GetBitmapBits through its own import slot (GOG and 2007 CD differ only there), or NULL */
static const struct version *detect(HANDLE proc) {
    for (size_t i = 0; i < sizeof versions / sizeof versions[0]; i++) {
        const struct version *v = &versions[i];
        BYTE want[6] = { 0x56, 0x68 }, cur[6], call[6] = { 0xff, 0x15 }; SIZE_T got;
        memcpy(want + 2, &v->wide_face, 4);
        memcpy(call + 2, &v->iat_getbitmapbits, 4);
        if (ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)v->wide_at, cur, 6, &got) && got == 6 &&
            memcmp(cur, want, 6) == 0 &&
            ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)v->bits_site, cur, 6, &got) && got == 6 &&
            memcmp(cur, call, 6) == 0)
            return v;
    }
    return NULL;
}

/* Indeo check: the game looks for a video codec named "IR32" (Indeo 3.2) via ICGetInfo, which Wine
   lacks. The videos are converted to MS Video 1, so the search string in the .data section is
   changed to "MS-CRAM" (Wine's MS Video 1 decoder). */
static void patch_indeo(HANDLE proc, const struct version *v) {
    static const char want[8] = { 'I','R','3','2',0,0,0,0 };
    static const char repl[8] = "MS-CRAM";
    LPVOID addr = (LPVOID)(ULONG_PTR)v->indeo;
    char cur[8]; SIZE_T n = 0;
    if (!ReadProcessMemory(proc, addr, cur, sizeof cur, &n) || n != sizeof cur) { logf_("Indeo patch: read failed", (long)GetLastError()); return; }
    if (memcmp(cur, want, sizeof want) != 0) { logf_("Indeo patch: different program version, nothing changed", 0); return; }
    if (WriteProcessMemory(proc, addr, repl, sizeof repl, &n) && n == sizeof repl) logf_("Indeo patch: applied", 1);
    else logf_("Indeo patch: write failed", (long)GetLastError());
}

/* Fonts: FUN_00573740 creates the menu fonts with CreateFontA(height, width, ..., "MS SANS SERIF"),
   the list and table windows (FUN_005e8xxx, FUN_0060bxxx, FUN_00616xxx) create their own 10 px font.
   MS Sans Serif is a bitmap font. Wine stretches it continuously to the requested width
   (headings about a third wider, text gets cut off). The width is therefore set to 0
   (natural width). The patched byte is the operand of "push <width>" before each call. */
static void patch_fonts(HANDLE proc, const struct version *v) {
    /* want = original width, val = 0 (natural width) */
    /* original widths for v->font[]; each is set to 0 (natural width) */
    static const BYTE want[16] = {
        6, 6, 6, 6, 6, 6, 7, 7, 10,
        12,     /* 20 px regular: club names */
        16,     /* 24 px regular */
        10,     /* 16 px bold */
        12,     /* 20 px bold */
        7, 7, 7 /* 10 px regular in the list and table windows (tables, cups, statistics) */
    };
    const int n = 16;
    const BYTE zero = 0;
    BYTE cur; SIZE_T got;
    for (int i = 0; i < n; i++) {   /* check everything first, then write */
        if (!ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)v->font[i], &cur, 1, &got) || got != 1 || cur != want[i]) {
            logf_("Font patch: different program version, nothing changed", (long)v->font[i]);
            return;
        }
    }
    int ok = 0;
    for (int i = 0; i < n; i++)
        if (WriteProcessMemory(proc, (LPVOID)(ULONG_PTR)v->font[i], &zero, 1, &got) && got == 1) ok++;
    FlushInstructionCache(proc, NULL, 0);
    logf_("Font patch: locations changed", ok);
}

/* Mascot in dialogs: FUN_0040a3d0 (animation in a STATIC control) builds the frames at full bitmap
   size and draws them into the control. The control is often smaller than the image. Windows still
   shows the overhang because the STATIC class has CS_PARENTDC. Wine clips to the control, and the
   mascot loses its legs. Fix: right after the image size is determined, the control is enlarged
   to at least the image size with SetWindowPos (never shrunk).
   The 9 bytes at 0x40a4c8 (lea ecx,[esp+0x40]; call 0x66faf7) are replaced by a jump into
   injected code, which executes them itself afterwards. */
static void patch_anim(HANDLE proc, const struct version *v) {
    const DWORD at = v->anim_at, back = at + 9, orig_call = v->anim_call, iat_setwindowpos = v->iat_setwindowpos;
    BYTE want[9] = { 0x8d,0x4c,0x24,0x40, 0xe8 };   /* lea ecx,[esp+0x40]; call orig_call */
    DWORD rel0 = orig_call - (at + 9); memcpy(want + 5, &rel0, 4);
    BYTE cur[9]; SIZE_T got;
    if (!ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)at, cur, 9, &got) || got != 9 || memcmp(cur, want, 9) != 0) {
        logf_("Mascot patch: different program version, nothing changed", 0); return;
    }
    LPVOID mem = VirtualAllocEx(proc, NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!mem || (ULONG_PTR)mem > 0xFFFF0000u) { logf_("Mascot patch: no memory", (long)GetLastError()); return; }
    DWORD c = (DWORD)(ULONG_PTR)mem;
    BYTE k[128]; int n = 0;
#define B(x) k[n++] = (BYTE)(x)
#define D(x) do { DWORD v_ = (DWORD)(x); memcpy(k + n, &v_, 4); n += 4; } while (0)
    B(0x60);                                   /* pushad (moves esp by 0x20) */
    B(0x8b); B(0x84); B(0x24); D(0x20 + 0xc4); /* mov eax,[esp+0xe4]  image width */
    B(0x8b); B(0x8c); B(0x24); D(0x20 + 0xac); /* mov ecx,[esp+0xcc]  Client right */
    B(0x3b); B(0xc1);                          /* cmp eax,ecx */
    B(0x7d); B(0x02);                          /* jge +2 */
    B(0x8b); B(0xc1);                          /* mov eax,ecx */
    B(0x8b); B(0x94); B(0x24); D(0x20 + 0xc8); /* mov edx,[esp+0xe8]  image height */
    B(0x8b); B(0x8c); B(0x24); D(0x20 + 0xb0); /* mov ecx,[esp+0xd0]  Client bottom */
    B(0x3b); B(0xd1);                          /* cmp edx,ecx */
    B(0x7d); B(0x02);                          /* jge +2 */
    B(0x8b); B(0xd1);                          /* mov edx,ecx */
    B(0x6a); B(0x16);                          /* push SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE */
    B(0x52);                                   /* push edx (cy) */
    B(0x50);                                   /* push eax (cx) */
    B(0x6a); B(0x00); B(0x6a); B(0x00); B(0x6a); B(0x00); /* y, x, hWndInsertAfter */
    B(0xff); B(0x75); B(0x1c);                 /* push dword [ebp+0x1c]  hwnd */
    B(0xff); B(0x15); D(iat_setwindowpos);     /* call [SetWindowPos] */
    B(0x61);                                   /* popad */
    B(0x8d); B(0x4c); B(0x24); B(0x40);        /* lea ecx,[esp+0x40]  (original) */
    B(0xe8); D(orig_call - (c + n + 4));       /* call 0x66faf7       (original) */
    B(0xe9); D(back - (c + n + 4));            /* jmp 0x40a4d1 */
#undef B
#undef D
    BYTE jmp[9] = { 0xe9, 0,0,0,0, 0x90,0x90,0x90,0x90 };
    DWORD rel = c - (at + 5); memcpy(jmp + 1, &rel, 4);
    if (!WriteProcessMemory(proc, mem, k, n, &got) || got != (SIZE_T)n ||
        !WriteProcessMemory(proc, (LPVOID)(ULONG_PTR)at, jmp, 9, &got) || got != 9) {
        logf_("Mascot patch: write failed", (long)GetLastError()); return;
    }
    FlushInstructionCache(proc, NULL, 0);
    logf_("Mascot patch: applied", 1);
}

/* Crests and flags: FUN_00467470 calls DrawDibDraw with a destination rectangle (x, y, 32, 32); the
   destination width/height is computed from it as 32-x and 32-y and is therefore negative. Windows
   treats a negative destination size like -1 ("use the image size"), Wine only exactly -1, and
   otherwise draws mirrored and stretched (a huge upside-down flag). Fix: the DrawDibDraw calls
   (through the import thunk 0x6554da) go through injected code that sets negative sizes to -1. */
static void patch_drawdib(HANDLE proc, const struct version *v) {
    const DWORD thunk = v->drawdib_thunk;
    BYTE cur[5]; SIZE_T got;
    for (int i = 0; i < 2; i++) {   /* call thunk */
        BYTE want[5] = { 0xe8 }; DWORD rel0 = thunk - (v->drawdib_site[i] + 5); memcpy(want + 1, &rel0, 4);
        if (!ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)v->drawdib_site[i], cur, 5, &got) || got != 5 || memcmp(cur, want, 5) != 0) {
            logf_("DrawDib patch: different program version, nothing changed", (long)v->drawdib_site[i]); return;
        }
    }
    LPVOID mem = VirtualAllocEx(proc, NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!mem || (ULONG_PTR)mem > 0xFFFF0000u) { logf_("DrawDib patch: no memory", (long)GetLastError()); return; }
    DWORD c = (DWORD)(ULONG_PTR)mem;
    BYTE k[64]; int n = 0;
    /* Stack on entry: [esp]=return address, +4 hdd, +8 hdc, +0xc x, +0x10 y, +0x14 dx, +0x18 dy */
    static const BYTE body[] = {
        0x83,0x7c,0x24,0x14,0x00,                    /* cmp dword [esp+0x14],0 */
        0x7d,0x08,                                   /* jge +8 */
        0xc7,0x44,0x24,0x14,0xff,0xff,0xff,0xff,     /* mov dword [esp+0x14],-1 */
        0x83,0x7c,0x24,0x18,0x00,                    /* cmp dword [esp+0x18],0 */
        0x7d,0x08,                                   /* jge +8 */
        0xc7,0x44,0x24,0x18,0xff,0xff,0xff,0xff,     /* mov dword [esp+0x18],-1 */
    };
    memcpy(k, body, sizeof body); n = sizeof body;
    k[n++] = 0xe9; { DWORD rel = thunk - (c + n + 4); memcpy(k + n, &rel, 4); n += 4; } /* jmp DrawDibDraw */
    if (!WriteProcessMemory(proc, mem, k, n, &got) || got != (SIZE_T)n) { logf_("DrawDib patch: write failed", (long)GetLastError()); return; }
    for (int i = 0; i < 2; i++) {
        BYTE call[5] = { 0xe8 }; DWORD rel = c - (v->drawdib_site[i] + 5); memcpy(call + 1, &rel, 4);
        if (!WriteProcessMemory(proc, (LPVOID)(ULONG_PTR)v->drawdib_site[i], call, 5, &got) || got != 5) {
            logf_("DrawDib patch: write failed", (long)GetLastError()); return;
        }
    }
    FlushInstructionCache(proc, NULL, 0);
    logf_("DrawDib patch: applied", 2);
}

/* Videos with an 8-bit palette (e.g. "Tor des Monats", goal of the month): FUN_00418cd0 calls
   AVIStreamGetFrameOpen with a requested "8 bit" format followed by an empty palette. Windows then uses
   the video's palette, Wine takes the empty one and every color turns black. With NULL ("the video's
   format") Wine returns the same format (8 bit, 256 colors) with the correct palette. To do so,
   "push eax" (pointer to the requested format) at 0x418dc2 is replaced by "push ebx"; ebx is 0 here. */
static void patch_avipal(HANDLE proc, const struct version *v) {
    const DWORD at = v->avipal; BYTE cur, val = 0x53; SIZE_T got;
    BYTE ctx[3];  /* check: followed by "mov dword [eax],0x28" (c7 00 28) */
    if (!ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)at, &cur, 1, &got) || cur != 0x50 ||
        !ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)(at + 1), ctx, 3, &got) || ctx[0] != 0xc7 || ctx[1] != 0x00 || ctx[2] != 0x28) {
        logf_("Video palette patch: different program version, nothing changed", 0); return;
    }
    if (WriteProcessMemory(proc, (LPVOID)(ULONG_PTR)at, &val, 1, &got) && got == 1) logf_("Video palette patch: applied", 1);
    else logf_("Video palette patch: write failed", (long)GetLastError());
    FlushInstructionCache(proc, NULL, 0);
}

/* Large fonts (club names, e.g. the match announcement): the game requests MS Sans Serif with 20 px
   height and 12 px width (or 24/16). Windows scales bitmap fonts by integer factors only and doubles
   the characters horizontally here. Wine only widens the gaps. Fix: the font "A2 Sans Serif Wide"
   (a2wide20.fnt/a2wide24.fnt, generated from the original by mkwide.py) already contains
   double-width characters. Wine does not load bitmap fonts from C:\windows\Fonts, so the game loads
   them itself with AddFontResourceA: at the start of FUN_00573740 (creates all menu fonts) it jumps
   into injected code that loads both files. The three affected CreateFontA calls get the new face
   name; patch_fonts has already set their width to 0 (natural). */
static void patch_widefont(HANDLE proc, const struct version *v, const char *dir) {
    const DWORD at = v->wide_at, back = at + 6, face_old = v->wide_face;
    const DWORD iat_getmodulehandle = v->iat_getmodulehandle, iat_getprocaddress = v->iat_getprocaddress;
    const DWORD *face_push = v->wide_face_push;                          /* 20 regular, 24 regular, 20 bold */
    static const int face_size[] = { 0, 1, 0 };                          /* index into file[] */
    BYTE want[6] = { 0x56, 0x68 };                                       /* push esi; push 0x6bece8 */
    memcpy(want + 2, &face_old, 4);
    /* a2wide24.fnt is missing when it was built from Wine's MS Sans Serif (no 24 px size); the
       24 px font then keeps MS Sans Serif */
    char file[2][MAX_PATH + 16]; int have[2], nhave = 0;
    snprintf(file[0], sizeof file[0], "%s\\a2wide20.fnt", dir);
    snprintf(file[1], sizeof file[1], "%s\\a2wide24.fnt", dir);
    for (int i = 0; i < 2; i++) nhave += have[i] = GetFileAttributesA(file[i]) != INVALID_FILE_ATTRIBUTES;
    if (!nhave) { logf_("Wide font patch: a2wide20.fnt/a2wide24.fnt missing, nothing changed", 0); return; }
    BYTE cur[6]; SIZE_T got;
    if (!ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)at, cur, 6, &got) || got != 6 || memcmp(cur, want, 6) != 0) {
        logf_("Wide font patch: different program version, nothing changed", 0); return;
    }
    for (int i = 0; i < 3; i++) {
        BYTE p[5];
        if (!ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)face_push[i], p, 5, &got) || got != 5 ||
            p[0] != 0x68 || memcmp(p + 1, &face_old, 4) != 0) {
            logf_("Wide font patch: different program version, nothing changed", (long)face_push[i]); return;
        }
    }
    LPVOID mem = VirtualAllocEx(proc, NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!mem || (ULONG_PTR)mem > 0xFFFF0000u) { logf_("Wide font patch: no memory", (long)GetLastError()); return; }
    DWORD c = (DWORD)(ULONG_PTR)mem;
    /* data from c+0x200 */
    BYTE k[4096]; memset(k, 0, sizeof k);
    const DWORD s_gdi = 0x200, s_proc = 0x210, s_face = 0x230, s_file[2] = { 0x250, 0x250 + 0x120 };
    strcpy((char *)k + s_gdi, "gdi32.dll");
    strcpy((char *)k + s_proc, "AddFontResourceA");
    strcpy((char *)k + s_face, "A2 Sans Serif Wide");
    for (int i = 0; i < 2; i++) strcpy((char *)k + s_file[i], file[i]);
    int n = 0, j1, j2;
#define B(x) k[n++] = (BYTE)(x)
#define D(x) do { DWORD v_ = (DWORD)(x); memcpy(k + n, &v_, 4); n += 4; } while (0)
    B(0x60);                                   /* pushad */
    B(0x68); D(c + s_gdi);                     /* push "gdi32.dll" */
    B(0xff); B(0x15); D(iat_getmodulehandle);  /* call [GetModuleHandleA] */
    B(0x85); B(0xc0);                          /* test eax,eax */
    B(0x74); j1 = n; B(0);                     /* jz done */
    B(0x68); D(c + s_proc);                    /* push "AddFontResourceA" */
    B(0x50);                                   /* push eax */
    B(0xff); B(0x15); D(iat_getprocaddress);   /* call [GetProcAddress] */
    B(0x85); B(0xc0);                          /* test eax,eax */
    B(0x74); j2 = n; B(0);                     /* jz done */
    B(0x8b); B(0xd8);                          /* mov ebx,eax */
    for (int i = 0; i < 2; i++)
        if (have[i]) {
            B(0x68); D(c + s_file[i]);         /* push file */
            B(0xff); B(0xd3);                  /* call ebx */
        }
    /* done: */
    k[j1] = (BYTE)(n - (j1 + 1)); k[j2] = (BYTE)(n - (j2 + 1));
    B(0x61);                                   /* popad */
    B(0x56);                                   /* push esi        (original) */
    B(0x68); D(face_old);                      /* push 0x6bece8   (original) */
    B(0xe9); D(back - (c + n + 4));            /* jmp 0x573746 */
#undef B
#undef D
    if (n > (int)s_gdi) { logf_("Wide font patch: code too long", n); return; }
    BYTE jmp[6] = { 0xe9, 0,0,0,0, 0x90 };
    DWORD rel = c - (at + 5); memcpy(jmp + 1, &rel, 4);
    DWORD face_new = c + s_face;
    if (!WriteProcessMemory(proc, mem, k, sizeof k, &got) || got != sizeof k) {
        logf_("Wide font patch: write failed", (long)GetLastError()); return;
    }
    int faces = 0;
    for (int i = 0; i < 3; i++) {
        if (!have[face_size[i]]) continue;
        if (!WriteProcessMemory(proc, (LPVOID)(ULONG_PTR)(face_push[i] + 1), &face_new, 4, &got) || got != 4) {
            logf_("Wide font patch: write failed", (long)GetLastError()); return;
        }
        faces++;
    }
    if (!WriteProcessMemory(proc, (LPVOID)(ULONG_PTR)at, jmp, 6, &got) || got != 6) {
        logf_("Wide font patch: write failed", (long)GetLastError()); return;
    }
    FlushInstructionCache(proc, NULL, 0);
    logf_("Wide font patch: applied", faces);
}

/* Cup draw (club names on the sign in the video, ARCHIVES/MoveList.dat): FUN_00419e10 draws the names
   with GDI into a CreateCompatibleBitmap(screen, 128, 32) and reads it with GetBitmapBits(bitmap,
   0x2000, [esi+0xc]), expecting 16 bit per pixel (256 bytes per row). Under Wine the bitmap has 32 bit
   per pixel even in the 16-bit mode, so the game gets the upper half of the picture with each pixel
   split in two: the names come out twice as wide, half as high and dotted. Fix: the call goes to
   injected code that fetches the picture with GetDIBits as a top-down 16-bit DIB. Wine ignores the
   color masks of a BI_BITFIELDS request (white came out as 0x0011, nearly black), so the code asks
   for BI_RGB (5-5-5) and converts the pixels itself to 5-6-5 if the game's surface uses that format
   (green mask [esi+0x8040] = 0x7e0, esi = the video object). Black stays 0 (transparent). */
static void patch_bitmapbits(HANDLE proc, const struct version *v) {
    const DWORD at = v->bits_site;
    BYTE want[6] = { 0xff, 0x15 }, cur[6]; SIZE_T got;
    memcpy(want + 2, &v->iat_getbitmapbits, 4);
    if (!ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)at, cur, 6, &got) || got != 6 || memcmp(cur, want, 6) != 0) {
        logf_("Cup draw patch: different program version, nothing changed", 0); return;
    }
    LPVOID mem = VirtualAllocEx(proc, NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!mem || (ULONG_PTR)mem > 0xFFFF0000u) { logf_("Cup draw patch: no memory", (long)GetLastError()); return; }
    DWORD c = (DWORD)(ULONG_PTR)mem;
    BYTE k[192]; int n = 0;
#define B(x) k[n++] = (BYTE)(x)
#define D(x) do { DWORD v_ = (DWORD)(x); memcpy(k + n, &v_, 4); n += 4; } while (0)
    /* stdcall like GetBitmapBits(hbm, cb, bits): [esp+4] hbm, [esp+8] cb, [esp+0xc] bits */
    B(0x55); B(0x53);                                    /* push ebp; push ebx */
    B(0x83); B(0xec); B(0x34);                           /* sub esp,0x34  BITMAPINFO */
    B(0xc7); B(0x04); B(0x24); D(40);                    /* biSize */
    B(0xc7); B(0x44); B(0x24); B(0x04); D(128);          /* biWidth */
    B(0xc7); B(0x44); B(0x24); B(0x08); D(-32);          /* biHeight: top-down */
    B(0xc7); B(0x44); B(0x24); B(0x0c); D(0x00100001);   /* biPlanes 1, biBitCount 16 */
    B(0x33); B(0xc0);                                    /* xor eax,eax */
    for (int o = 0x10; o <= 0x24; o += 4) { B(0x89); B(0x44); B(0x24); B(o); } /* BI_RGB, rest 0 */
    B(0x6a); B(0x00); B(0xff); B(0x15); D(v->iat_getdc); /* GetDC(NULL) */
    B(0x8b); B(0xd8);                                    /* mov ebx,eax */
    B(0x8b); B(0xcc);                                    /* mov ecx,esp  BITMAPINFO */
    B(0x6a); B(0x00);                                    /* push DIB_RGB_COLORS */
    B(0x51);                                             /* push ecx */
    B(0xff); B(0x74); B(0x24); B(0x50);                  /* push bits ([esp+0x48] before 2 pushes) */
    B(0x6a); B(0x20); B(0x6a); B(0x00);                  /* push 32 lines; push start 0 */
    B(0xff); B(0x74); B(0x24); B(0x54);                  /* push hbm ([esp+0x40] before 5 pushes) */
    B(0x53);                                             /* push hdc */
    B(0xff); B(0x15); D(v->iat_getdibits);               /* GetDIBits */
    B(0x8b); B(0xe8);                                    /* mov ebp,eax */
    B(0x53); B(0x6a); B(0x00); B(0xff); B(0x15); D(v->iat_releasedc); /* ReleaseDC(NULL, hdc) */
    B(0x81); B(0xbe); D(0x8040); D(0x7e0);               /* cmp dword [esi+0x8040],0x7e0  5-6-5? */
    B(0x75); B(0x30);                                    /* jne done */
    B(0x8b); B(0x54); B(0x24); B(0x48);                  /* mov edx,[esp+0x48]  bits */
    B(0xb9); D(128 * 32);                                /* mov ecx,4096 */
    B(0x0f); B(0xb7); B(0x02);                           /* L: movzx eax,word [edx]  0rrrrrgggggbbbbb */
    B(0x8b); B(0xd8);                                    /* mov ebx,eax */
    B(0x81); B(0xe3); D(0x1f);                           /* and ebx,0x1f      blue */
    B(0x25); D(0x7fe0);                                  /* and eax,0x7fe0    red, green */
    B(0xd1); B(0xe0);                                    /* shl eax,1 */
    B(0x0b); B(0xd8);                                    /* or ebx,eax */
    B(0x25); D(0x400);                                   /* and eax,0x400     top green bit */
    B(0xc1); B(0xe8); B(0x05);                           /* shr eax,5         to the lowest one */
    B(0x0b); B(0xc3);                                    /* or eax,ebx */
    B(0x66); B(0x89); B(0x02);                           /* mov [edx],ax */
    B(0x83); B(0xc2); B(0x02);                           /* add edx,2 */
    B(0x49);                                             /* dec ecx */
    B(0x75); B(0xd9);                                    /* jne L */
    B(0x8b); B(0xc5);                                    /* done: mov eax,ebp */
    B(0x83); B(0xc4); B(0x34);                           /* add esp,0x34 */
    B(0x5b); B(0x5d);                                    /* pop ebx; pop ebp */
    B(0xc2); B(0x0c); B(0x00);                           /* ret 0xc */
#undef B
#undef D
    BYTE call[6] = { 0xe8, 0,0,0,0, 0x90 };
    DWORD rel = c - (at + 5); memcpy(call + 1, &rel, 4);
    if (!WriteProcessMemory(proc, mem, k, n, &got) || got != (SIZE_T)n ||
        !WriteProcessMemory(proc, (LPVOID)(ULONG_PTR)at, call, 6, &got) || got != 6) {
        logf_("Cup draw patch: write failed", (long)GetLastError()); return;
    }
    FlushInstructionCache(proc, NULL, 0);
    logf_("Cup draw patch: applied", 1);
}

/* Preseason calculation ("ANSTOSS2 - Kalkulation"): the constructor of its dialog (FUN_004a4d80)
   sets the selection of "Ermittlung der Zahlen" (word [dlg+0x10d48]) to 0 but leaves that of
   "Darstellung" (word [dlg+0x10d46]) as it comes from the heap. OnInitDialog selects that entry in
   the 4-entry list, and its paint code (FUN_005bf1f0) copies the entry's name without checking the
   upper bound. On Windows the fresh heap memory is 0 ("Reine Kalkulation"); under Wine it may hold
   anything, depending on what was freed before (e.g. without Italy as a bonus country). A large value
   makes the copy read outside the dialog: the access violation inside WM_INITDIALOG is swallowed by
   the window callback, so the dialog is left hidden and half set up while the game waits for it.
   Fix: "mov word [esi+0x10d48],0; mov eax,esi" (11 bytes) becomes "mov eax,esi;
   and dword [esi+0x10d46],0; nop; nop", which clears both words. */
static void patch_calcinit(HANDLE proc, const struct version *v) {
    static const BYTE want[11] = { 0x66,0xc7,0x86,0x48,0x0d,0x01,0x00,0x00,0x00, 0x8b,0xc6 };
    static const BYTE repl[11] = { 0x8b,0xc6, 0x83,0xa6,0x46,0x0d,0x01,0x00,0x00, 0x90,0x90 };
    BYTE cur[11]; SIZE_T got;
    LPVOID addr = (LPVOID)(ULONG_PTR)v->calc_init;
    if (!ReadProcessMemory(proc, addr, cur, sizeof cur, &got) || got != sizeof cur || memcmp(cur, want, sizeof want) != 0) {
        logf_("Calculation patch: different program version, nothing changed", 0); return;
    }
    if (WriteProcessMemory(proc, addr, repl, sizeof repl, &got) && got == sizeof repl) logf_("Calculation patch: applied", 1);
    else logf_("Calculation patch: write failed", (long)GetLastError());
    FlushInstructionCache(proc, NULL, 0);
}

/* Picture buttons (e.g. "A/B" and "i" in the team lineup before a match): the constructor of the
   button class (FUN_005bc3a0) leaves the BITMAP fields [btn+0x7c..0x93] as they come from the heap;
   width and height ([btn+0x80], [btn+0x84]) are only filled by GetObjectA when a picture is loaded.
   The lineup moves "A/B" and "i" to their template position (FUN_005bcc10, MoveWindow with these
   width and height) before loading their pictures, which then align them to the bottom right corner
   of that window (FUN_005bcca0). On Windows the fresh memory is 0: the window has size 0, and the
   alignment puts the button exactly where the template has it. Under Wine the memory may hold old
   pixel data: the window gets a huge size, Wine limits its corner to 32767, and the button ends up
   outside the screen until the lineup is opened again. Fix: the constructor's last two instructions
   "mov dword [esi],vtable; mov eax,esi" (8 bytes, followed by "pop esi; ret") jump into injected code
   that clears the BITMAP fields first. */
static void patch_btninit(HANDLE proc, const struct version *v) {
    const DWORD at = v->btn_ctor_end;
    BYTE want[10] = { 0xc7,0x06, 0,0,0,0, 0x8b,0xc6, 0x5e,0xc3 }, cur[10]; SIZE_T got;
    memcpy(want + 2, &v->btn_vtable, 4);
    if (!ReadProcessMemory(proc, (LPVOID)(ULONG_PTR)at, cur, 10, &got) || got != 10 || memcmp(cur, want, 10) != 0) {
        logf_("Button patch: different program version, nothing changed", 0); return;
    }
    LPVOID mem = VirtualAllocEx(proc, NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!mem || (ULONG_PTR)mem > 0xFFFF0000u) { logf_("Button patch: no memory", (long)GetLastError()); return; }
    BYTE k[64]; int n = 0;
    k[n++] = 0x33; k[n++] = 0xc0;                          /* xor eax,eax */
    for (DWORD off = 0x7c; off < 0x94; off += 4) {         /* mov [esi+off],eax (bmType..bmBits) */
        k[n++] = 0x89; k[n++] = 0x86; memcpy(k + n, &off, 4); n += 4;
    }
    memcpy(k + n, want, 10); n += 10;                      /* original: mov [esi],vtable; mov eax,esi; pop esi; ret */
    BYTE jmp[8] = { 0xe9, 0,0,0,0, 0x90,0x90,0x90 };
    DWORD rel = (DWORD)(ULONG_PTR)mem - (at + 5); memcpy(jmp + 1, &rel, 4);
    if (!WriteProcessMemory(proc, mem, k, n, &got) || got != (SIZE_T)n ||
        !WriteProcessMemory(proc, (LPVOID)(ULONG_PTR)at, jmp, 8, &got) || got != 8) {
        logf_("Button patch: write failed", (long)GetLastError()); return;
    }
    FlushInstructionCache(proc, NULL, 0);
    logf_("Button patch: applied", 1);
}

int main(void) {
    /* working directory = folder of a2start.exe (system32 otherwise when started via explorer /desktop) */
    char dir[MAX_PATH] = ".";
    DWORD dl = GetModuleFileNameA(NULL, dir, MAX_PATH);
    if (dl && dl < MAX_PATH) { char *s = strrchr(dir, '\\'); if (s) { *s = 0; SetCurrentDirectoryA(dir); } }

    char *cmd = GetCommandLineA();
    /* skip our own program name */
    if (*cmd == '"') { cmd = strchr(cmd + 1, '"'); cmd = cmd ? cmd + 1 : ""; }
    else { while (*cmd && *cmd != ' ') cmd++; }
    while (*cmd == ' ') cmd++;
    if (!*cmd) { MessageBoxA(NULL, "Usage: a2start.exe program.exe [arguments]", "a2start", MB_OK); return 1; }

    DEVMODEA dm; memset(&dm, 0, sizeof dm);
    dm.dmSize = sizeof dm;
    dm.dmPelsWidth = 640; dm.dmPelsHeight = 480; dm.dmBitsPerPel = 16;
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL;
    LONG r = ChangeDisplaySettingsA(&dm, 0);
    HDC dc = GetDC(NULL);
    logf_("ChangeDisplaySettings:", r);
    logf_("BITSPIXEL afterwards:", GetDeviceCaps(dc, BITSPIXEL));
    ReleaseDC(NULL, dc);

    STARTUPINFOA si; PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof si); si.cb = sizeof si;
    char *buf = _strdup(cmd);
    if (!CreateProcessA(NULL, buf, NULL, NULL, FALSE, CREATE_SUSPENDED, NULL, NULL, &si, &pi)) {
        logf_("CreateProcess failed:", (long)GetLastError());
        ChangeDisplaySettingsA(NULL, 0);
        return 1;
    }
    const struct version *v = detect(pi.hProcess);
    if (v) {
        FILE *f = fopen("a2start.log", "a");
        if (f) { fprintf(f, "Program version: %s\n", v->name); fclose(f); }
        patch_indeo(pi.hProcess, v);
        patch_fonts(pi.hProcess, v);
        patch_anim(pi.hProcess, v);
        patch_drawdib(pi.hProcess, v);
        patch_avipal(pi.hProcess, v);
        patch_widefont(pi.hProcess, v, dir);
        patch_bitmapbits(pi.hProcess, v);
        patch_calcinit(pi.hProcess, v);
        patch_btninit(pi.hProcess, v);
    } else {
        logf_("Unknown program version, nothing changed", 0);
    }
    ResumeThread(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0; GetExitCodeProcess(pi.hProcess, &code);
    ChangeDisplaySettingsA(NULL, 0);
    return (int)code;
}

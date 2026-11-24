# SPDX-License-Identifier: GPL-3.0-only
# Masks of transparent pictures as on a 16-bit screen of Windows 98 (a2start.exe, "Mask patch").
#
# The game draws its transparent pictures (among them the figures of the interviews) with a
# monochrome mask that it makes by copying the colour bitmap into a 1-bit bitmap: every pixel of
# the background colour (mostly black) becomes transparent. On a 16-bit screen of Windows 98 the
# colour bitmap has 16 bit per pixel, so the near-black edge that the game's 3D engine leaves around
# a rendered head, (4,2,2) or (2,2,2), is black there and transparent. Windows 10/11 and Wine keep
# such bitmaps at 32 bit even in the 16-bit mode; the edge stays near-black, the mask leaves it
# opaque and the head stands in a black box.
#
# This code sits in front of every BitBlt of the game (its import slot points here). A copy with
# SRCCOPY of a bitmap with more than 16 bit per pixel into a 1-bit bitmap first rounds the copied
# part of the source to 16 bit (5-6-5, through a DIB section and back); then, as for every other
# call, it jumps on to BitBlt itself with the caller's arguments.
#
# stdcall BitBlt(hdcDest, x, y, cx, cy, hdcSrc, x1, y1, rop): [ebp+8] .. [ebp+40] below.
# The import slots of the game are placeholders, which a2start.exe replaces per program version.
# Position independent: only relative jumps and calls inside, absolute addresses only of the slots.
# .github/build-mask.sh assembles it into src/a2mask.h.

        .intel_syntax noprefix
        .equ SLOT_BITBLT,            0x11111100   # the original BitBlt (a slot next to the code)
        .equ SLOT_CREATECOMPATIBLEDC, 0x11111102
        .equ SLOT_CREATEDIBSECTION,  0x11111103
        .equ SLOT_SELECTOBJECT,      0x11111104
        .equ SLOT_DELETEOBJECT,      0x11111105
        .equ SLOT_DELETEDC,          0x11111106
        .equ SLOT_GETCURRENTOBJECT,  0x11111107
        .equ SLOT_GETOBJECTA,        0x11111108
        .equ SRCCOPY,                0x00cc0020

        .text
        .globl _start
_start:
        push    ebp
        mov     ebp, esp
        push    ebx
        push    esi
        push    edi
        sub     esp, 0x40               # [esp] BITMAPINFO (52 bytes), [esp+0x34] bits, [esp+0x38] old bitmap
        mov     esi, [ebp+28]           # hdcSrc
        test    esi, esi
        jz      pass
        cmp     dword ptr [ebp+40], SRCCOPY
        jne     pass
        cmp     dword ptr [ebp+20], 0   # cx
        jle     pass
        cmp     dword ptr [ebp+24], 0   # cy
        jle     pass
        push    dword ptr [ebp+8]
        call    bpp                     # destination: a 1-bit bitmap (a mask)?
        cmp     eax, 1
        jne     pass
        push    esi
        call    bpp                     # source: more than 16 bit per pixel?
        cmp     eax, 16
        jle     pass

        mov     edi, esp                # BITMAPINFOHEADER + 3 colour masks, top-down, 5-6-5
        xor     eax, eax
        mov     ecx, 13
        rep     stosd
        mov     dword ptr [esp], 40     # biSize
        mov     eax, [ebp+20]
        mov     [esp+4], eax            # biWidth = cx
        mov     eax, [ebp+24]
        neg     eax
        mov     [esp+8], eax            # biHeight = -cy
        mov     dword ptr [esp+12], 0x00100001  # biPlanes 1, biBitCount 16
        mov     dword ptr [esp+16], 3   # BI_BITFIELDS
        mov     dword ptr [esp+40], 0xf800
        mov     dword ptr [esp+44], 0x07e0
        mov     dword ptr [esp+48], 0x001f
        mov     eax, esp
        lea     ecx, [eax+0x34]
        push    0
        push    0
        push    ecx                     # &bits
        push    0                       # DIB_RGB_COLORS
        push    eax                     # &BITMAPINFO
        push    esi
        call    dword ptr [SLOT_CREATEDIBSECTION]
        test    eax, eax
        jz      pass
        mov     ebx, eax                # the DIB section
        push    esi
        call    dword ptr [SLOT_CREATECOMPATIBLEDC]
        test    eax, eax
        jz      free_dib
        mov     edi, eax                # a DC for it
        push    ebx
        push    edi
        call    dword ptr [SLOT_SELECTOBJECT]
        mov     [esp+0x38], eax
        push    SRCCOPY                 # source part -> DIB section (rounded to 5-6-5)
        push    dword ptr [ebp+36]
        push    dword ptr [ebp+32]
        push    esi
        push    dword ptr [ebp+24]
        push    dword ptr [ebp+20]
        push    0
        push    0
        push    edi
        call    dword ptr [SLOT_BITBLT]
        push    SRCCOPY                 # and back
        push    0
        push    0
        push    edi
        push    dword ptr [ebp+24]
        push    dword ptr [ebp+20]
        push    dword ptr [ebp+36]
        push    dword ptr [ebp+32]
        push    esi
        call    dword ptr [SLOT_BITBLT]
        push    dword ptr [esp+0x38]
        push    edi
        call    dword ptr [SLOT_SELECTOBJECT]
        push    edi
        call    dword ptr [SLOT_DELETEDC]
free_dib:
        push    ebx
        call    dword ptr [SLOT_DELETEOBJECT]
pass:
        lea     esp, [ebp-12]
        pop     edi
        pop     esi
        pop     ebx
        pop     ebp
        jmp     dword ptr [SLOT_BITBLT] # BitBlt itself, with the caller's arguments and return address

# stdcall bpp(hdc): bits per pixel of the bitmap selected into hdc, 0 if unknown
bpp:
        push    ebp
        mov     ebp, esp
        sub     esp, 24                 # BITMAP
        push    7                       # OBJ_BITMAP
        push    dword ptr [ebp+8]
        call    dword ptr [SLOT_GETCURRENTOBJECT]
        test    eax, eax
        jz      bpp_none
        mov     ecx, esp
        push    ecx
        push    24
        push    eax
        call    dword ptr [SLOT_GETOBJECTA]
        test    eax, eax
        jz      bpp_none
        movzx   eax, word ptr [esp+18]  # bmBitsPixel
        leave
        ret     4
bpp_none:
        xor     eax, eax
        leave
        ret     4

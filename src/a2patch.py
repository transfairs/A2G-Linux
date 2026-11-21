#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Patches anstoss2.exe (1999 CD) or run.exe (GOG, 2007 CD) of Anstoss 2 Gold on disk.

    a2patch.py [--fixes] [--sound] [--arrows] [--video] [--freeze] [--disk] [--squad] [--investments]
               [--money] [--events] [--crashes] [--referee] [--competence] [--grades] [--grade-chart]
               [--appearances] [--fish] [--manager] [--lawn] [--interviews] [--negotiation] [--goals]
               [--speeches] [--coaches] [--disc-check] [--v101] <path to anstoss2.exe or run.exe>

--fixes  all bug fixes: --sound --arrows --video --freeze --disk --squad --investments --money --events
         --crashes --referee --competence --grades --grade-chart --appearances --fish --manager --lawn (the
         installer applies them to every release, together with --interviews; A2G-Patch counts --fish and
         --manager as balancing).
         --negotiation, --goals, --speeches and --coaches change how the game plays (balancing); the
         installer asks for each on a page of its own.

--sound  "Ton über das Standard-Audiogerät von Windows" (bug fix): the game enumerates the sound
         devices and keeps the one with the most 3D hardware buffers. Every device reports 0, and on
         a tie the last one wins, so with several outputs (speakers, Bluetooth headphones, HDMI) the
         sound may go to the wrong one. The patch passes NULL instead of the kept GUID to
         DirectSoundCreate, which means the default device:

             push esi / push &ds / push &guid / call DirectSoundCreate ... mov [&ds],esi
             ->                    push esi / nop x4   (esi is 0 there, as the first push shows)

--arrows "Pfeile zählen beim Gedrückthalten weiter" (bug fix): the repeat thread of the arrow buttons
         posts a step only while none is pending (+F4 == 0) and marks it pending only after posting. If
         the window thread handles the step first (on another core, or boosted), the counter stays 1
         and the thread never posts again. The patch marks the step pending before posting:

             mov eax,[msg] / mov ecx,[esi+1C] / push 0,0,eax,ecx / call ebx (PostMessageA)
             mov eax,[esi+F4] / mov [esi+F0],60 / inc eax / mov [esi+F4],eax / jmp next
             ->  mov [esi+F4],1 / mov [esi+F0],60 / (the post) / nop x3 / jmp next

--video  "Nicht abspielbare Videos überspringen statt abzustürzen" (bug fix): the game's AVI player
         (WM.AVI, EM.AVI, FINALE.AVI) doesn't check AVIStreamGetFrameOpen for NULL and then reads
         through a NULL pointer. The installer converts the Indeo videos, so this only matters if a
         video can't be decoded (e.g. one from a data set). The patch adds the check and on NULL takes
         the way the function takes for a missing stream; the room comes from encoding the setup
         before the call more tightly (75 bytes, the call's displacement is kept). Its first 13 bytes,
         where a2start.exe's video palette patch writes, stay as they are.

--freeze "Kein Einfrieren nach über 24 Tagen Laufzeit" (bug fix): a reply sequence waits
         Sleep(3000 - difference), with the difference compared signed. Reached without a fresh
         timestamp, the difference is about timeGetTime(), negative once the system has run for 2^31
         ms, and the game sleeps for weeks. Unsigned comparison, two places:

             sub eax,[ebp+17C] / cmp eax,0BB8 / mov [ebp+17C],eax / jge (7D)  ->  jae (73)

--disk   "Keine falsche Warnung 'Festplatte fast voll' beim Speichern" (bug fix): the free space from
         GetDiskFreeSpaceA is multiplied in 32 bits (modulo 4 GB), so the warning comes up for no
         reason now and then. The warning is skipped:

             imul eax,[esp+x] / cmp eax,177000 / jae (73)  ->  jmp (EB)

--squad  "Kader nicht über 30 Spieler wachsen lassen" (bug fix): "squad full?" counts a forecast
         (squad minus pending departures plus arrivals, every loan counts as a departure), so a club
         with players on loan can get a 31st player, which overwrites the data behind its player
         array. The patch also calls the squad full at 30 actual players (same 32 bytes):

             push [esp+4] / call forecast / add esp,4 / xor ecx,ecx / cmp ax,1E / setge cl / ...
             ->  push [esp+4] / call forecast / pop ecx / cmp ax,1E / jge full /
                 cmp word [ecx+E6],1E / full: setge al / movzx eax,al / ret

--investments  "Wertzuwachs von Geldanlagen nicht mehr vom Kontostand abziehen" (bug fix): the game
         works out the balance each time as ledger minus the current value of the investments plus
         loans plus the season's bookings, so every gain of an investment comes off the balance (and its
         interest), and closing it gives it back on top of the interest booked. The patch subtracts the
         deposits (+0 of each of the 6 slots at +A8, active if bit 0 of +3 is set) instead, in the same 48
         bytes; "values" lies 0x20 bytes behind "loans", so taking the patch back can restore its call.

--money  "Vereinskonto stoppt bei 2 Mrd. DM, statt ins Minus zu kippen" (bug fix): the game books a
         club's week once, adding the week's result after tax to the ledger at +154 (an Int32) unchecked,
         so past 2,147,483,647 DM it turns into about -2.1 billion and the club counts as broke (overdraft
         interest, a forced loan). The patch stops the booking at 2,000,000,000 DM; a higher ledger (set
         with a trainer) stays and only stops growing. Room for the check comes from the week's result
         (208 bytes), which adds up the same fields as the bookings 0x100 behind its first callee: it is
         rewritten as a call of the bookings that takes +338 back and +33C off (29 bytes, the same result
         and calls), the check follows at +20, and the booking jumps there.

--events  "Ereignisse wirken wie in ihrer Meldung" (bug fix): 19 places where a random event does other
         than its message says (texts of EreigGld.saq): money booked with the wrong sign or as the wrong
         kind (690, 697, 126, 143, 172), the chocolate sponsor's doubled offer (224), freshness given
         instead of taken (307, 308, 369, 414), the wrong sound (56) or player (38), a text too many (392),
         an injury without a name (kind 62 -> 68 "Fischvergiftung"), the riot's text and amounts (284),
         form points the text names (339, 343) and the reasons of a building delay (876/877). Two places
         move a call; its displacement moves with it (rewrite_site).

--crashes  "Kein Absturz bei Ereignissen ohne passenden Spieler" (bug fix): the two functions that draw a
         player for an event return NULL if nobody fits, and four callers read through it without a test.
         Each gets the test in its own bytes.

--referee  "Schiedsrichter mit Groll treffen in den Spielszenen den richtigen Verein" (bug fix): a referee's
         grudge against a club (set by the microphone, interview answers or the affair of --manager) makes him
         show its players more cards, but the scenes he decides compare it with the club's number plus one
         and skip 0, so they hit the club with the next lower number. The patch drops both (3 nops).

--competence  "Trainer und Manager in schwachen Ländern werden jährlich besser" (bug fix): the yearly
         balance of a country's competence adds the raise to the sum but never stores it; the patch stores
         it, in the same 36 bytes.

--grades  "Einsätze ohne Note zählen nicht im Notenschnitt" (bug fix): the season average in the player's
         details and the fans' check for a hated player test the mark together with the cards, so a short
         appearance with a card counts as mark 0. Two places test the mark alone: test al,1F -> test al,1C.

--grade-chart  "Notenverlauf in der Statistik mit 'Noten/6' statt 'Formpunkte/6' beschriften" (bug fix, part
         of "Notenschnitt" in A2G-Patch): the chart of the average marks per week labels its axis with the
         form chart's text. The patch assigns "Noten/6" from the exe, the string in the nops behind the
         function; the two call targets are taken from the next label's text loader.

--appearances  "Vereinsliste der meisten Einsätze nimmt nach 50 Spielern wieder neue auf" (bug fix): a
         player's leaving clears his flag "at the club" in the goals list only, so the appearances list is
         full after 50 players. The patch sets its flags anew from the squad before each count (a routine in
         front of the list's sort, now a bubble sort with the same order) and lets a new player take the
         places from 21 on instead of 11.

--fish   "Fischvergiftung: drei Wochen Ausfall wie in der Meldung" (balancing in A2G-Patch, in --fixes
         here): the injury of the referee events' fish poisoning (text 732) lasts 21 days instead of the 7
         of its kind.

--manager  "Weitere Ereignisse rund um den Manager" (balancing in A2G-Patch, in --fixes here): the
         manager's private life draws from the table of the other kind of events, so 25 of its 39 cases
         never come. The patch builds it from its own table (0x38 bytes behind) and passes the manager's
         name twice for case 32, whose text holds it twice. Six cases without working code (13, 21, 25, 34,
         35, 39) get A2G-Patch's: src/a2manager.json (taken from its ManagerCode.cs by
         src/a2managerbuild.py) is linked into three functions of the game nothing refers to, and the
         switch's jump table leads there. Case 34's weight, which A2G-Linux 0.2.0 set to 0, goes back to 4.

--lawn   "Rasenpflege ohne Strich unter Wine" (bug fix of A2G-Linux, not in A2G-Patch): the stadium's
         button "Rasen pflegen (20.000 DM)" gets the state of the pitch behind a tab ("%s\t%s"), and the
         game draws the button's text without expanding tabs. Windows leaves the tab out, Wine draws it as
         a bar: "(20.000 DM)|Optimal". The two places push the game's own "%s\n%s" instead, so the state
         stands on the button's second line. The other users of "%s\t%s" split their text into columns
         at the tab and keep it.

--interviews  "Antworten in Interviews wirken sich aus" (A2G-Patch counts it as balancing, the installer
         applies it every time): the answers' effect pairs are written to the engine's copy of the
         interview context but applied from the context itself, and codes 10 (morale) and 12 (fine) don't
         match the effect function. The patch adds A2G-Trainer's
         InterviewEffectsFix byte for byte (256 bytes, signature "A2GINT02", flag at +8) and points the
         apply call and the morale call of case 12 at it. Room: in front of where A2G-Patch's cup draw
         helper goes at the end of the last executable section, if zero (GOG's .idata), else a section
         ".a2int" of its own, added as A2G-Patch does it and in front of ".a2v101", which A2G-Patch
         recognizes only as the last section.

--negotiation  "Sperre nach drei Verhandlungsterminen baut sich jeden Monat ab" (balancing): the monthly
         club update halves the negotiation counters at +107D..1080 instead of +1081..1084 (one per human
         manager), so the lock of 3 dates lasts until the season start. The patch moves the 4 loads and 4
         stores.

--goals  "Torgrenzen aufheben" (balancing): the match engine lets a team score only while it
         has fewer than 6 goals up to minute 45 and fewer than 10 after, and halves its chances from
         7 goals on. The patch raises the limit to 15 (the most a result nibble holds) and drops the
         halving:

             limit:  setg r8 / dec r32 / and r, -4 / add r, 10   ->  setg r8 / mov r32, 15 / nop...
             brakes: jle (7E)                                     ->  jmp (EB)

--speeches  "Unpassende Ansprachen schwächen die Mannschaft" (balancing): three places. A failed
         motivation roll counts as no use taken (xor edi,edi -> xor ebx,ebx), the team block is marked
         with the negative speech number for a speech that doesn't fit, and the function applying the
         speech (176 bytes, rewritten) takes the percentages off for a negative number and leaves the
         hardness. The speech table's address is taken from the code.

--coaches  "Neue Trainer: Ex-Spieler ab 33, sonst Kompetenz 3 bis 11 statt 2" (balancing): a retiring
         trainer's place goes to the next former player of a waiting list, but players only get on it if
         they end their career at 36 or older, so the place mostly goes back to the same person with
         competence 2 and the strong trainers die out. The patch lowers the age to 33 (cmp dl,23 ->
         cmp dl,20) and rewrites the two functions that fill a place (trainers and managers, goalkeeper
         trainers) in their own bytes: without an entry, competence 3 + four times random(3). The random
         function is taken from the call behind the age check, the tables from the original code.

--disc-check  run.exe (GOG, 2007 CD) only, bug fix: run.exe is the game of the 2007 CD release, whose
         copy protection checks the CD in 11 places of the game (team names become "Raubkopie",
         players drop to strength 1, ...). Each check calls one signature routine and subtracts
         the expected value; zero (or more) means "original CD". GOG replaced the subtraction with
         NOPs, so the raw signature remains and the checks fail; run.exe of the 2007 CD (unpacked
         with src/a2unpack.py) still has the subtraction and fails as well, since a copy of the CD
         gives another signature. The patch puts in what a passed check leaves, as the 1999 CD
         version (which has none of these checks) behaves:

             call check / mov r32,eax / add esp,4 / {nop x6 | sub r32,imm32}  ->  ... / xor r32,r32 / nop x4
             call check / add esp,4 / {nop x5 | sub eax,imm32} / mov [..],eax ->  ... / xor eax,eax / nop x3 / ...

--v101   run.exe (GOG, 2007 CD) only: the program changes of patch 1.01 (run.exe is built from the
         1.00 source). The code is in src/a2v101.S, assembled by src/a2v101build.py into
         src/a2v101.json (no GNU binutils needed here); it is moved to the address of a new section
         ".a2v101" appended to run.exe, and the places in V101_HOOKS jump there or are changed in
         place; one of them makes the cup draw load archives/movelist.dat from the game folder instead
         of the CD, as 1.01 does (the file comes with patch 1.01, see src/a2data101.py). The section is added as
         A2G-Patch adds it (behind GOG's signature, the overwritten header bytes kept), so for GOG's
         run.exe the result is A2G-Patch's to the byte and A2G-Patch can take it back.

Integrity of run.exe (GOG, 2007 CD, automatic): the 2007 release checks its own program in two ways.
         Five places compute a CRC32 of run.exe on disk (from offset 0x80 to the end) and compare it with
         the value stored at offset 0x7c; five others compute a CRC32 of a stretch of their own code and
         compare it with a value stored in front of it. On a mismatch the game silently skips work,
         doubles negative values (0x418ca0) or runs into garbage. GOG's unpacked run.exe already fails
         all of them (GOG disabled four of the code checks, not the others), run.exe of the 2007 CD fails
         the file checks once it is unpacked or patched. Whenever run.exe is written,
         a2patch.py therefore stores the correct values, so the checks pass as with the untouched original.

All patches but --lawn, --disc-check and --v101 are ports from A2G-Patch by transfairs
(GPLv3, https://github.com/transfairs/A2G-Patcher, Patches.cs and GameInstall.cs), with the same
patterns and bytes. Like A2G-Patch, it writes the backup anstoss2.exe.vor-a2g-patch (run.exe.vor-a2g-patch)
first, so A2G-Patch recognizes the result and can take the
patches back. Each place must occur exactly once and hold either the original or the patched bytes;
otherwise nothing is written.
"""

import argparse
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from a2v101build import relocate  # noqa: E402

BACKUP_SUFFIX = ".vor-a2g-patch"
NOP = 0x90


def find_all(image, pattern):
    """Every start of pattern in image; None entries in pattern match any byte."""
    regex = re.compile(
        b"(?=" + b"".join(b"." if b is None else re.escape(bytes([b])) for b in pattern) + b")", re.DOTALL
    )
    return [m.start() for m in regex.finditer(image)]


# --- Goal limits --------------------------------------------------------------
MAX_GOALS = 15
JLE, JMP = 0x7E, 0xEB
# The instructions right before each rewritten byte.
LIMIT_PATTERN = bytes([0x66, 0x83, 0x7F, 0x08, 0x2D, 0x57, 0x6A, 0x01, 0x0F, 0x9F])
HOME_BRAKE_PATTERN = bytes([0x66, 0x83, 0x7E, 0x0E, 0x06, 0x89, 0x44, 0x24, 0x30])
AWAY_BRAKE_PATTERN = bytes([0x66, 0x8B, 0x56, 0x10, 0x83, 0xC4, 0x04, 0x66, 0x83, 0xFA, 0x06, 0x8B, 0xC8])


def after(image, pattern):
    """The position right after the pattern's only occurrence, or None."""
    found = find_all(image, pattern)
    return found[0] + len(pattern) if len(found) == 1 else None


def limit_originals(register):
    """The original code behind setg for register: its long form, and for eax also the short one."""
    # dec r32 / and r, -4 / add r, 10; with eax the compiler may use the short "and al, -4".
    # The long form comes first: patched, the short form is a prefix of it.
    add = bytes([0x83, 0xC0 + register, 0x0A])
    long_form = bytes([0x48 + register, 0x83, 0xE0 + register, 0xFC]) + add
    return [long_form, bytes([0x48, 0x24, 0xFC]) + add] if register == 0 else [long_form]


def limit_patched(register, length):
    """mov r32, 15, padded with nops to the original's length."""
    return bytes([0xB8 + register]) + struct.pack("<i", MAX_GOALS) + bytes([NOP] * (length - 5))


def goal_sites(image):
    """[(offset, original, patched, is_patched)] or None if the exe doesn't match."""
    limit, home, away = (after(image, p) for p in (LIMIT_PATTERN, HOME_BRAKE_PATTERN, AWAY_BRAKE_PATTERN))
    if limit is None or home is None or away is None:
        return None
    # limit is setg's ModR/M byte (C0+r); the rewritten instructions follow it.
    if limit + 8 > len(image) or not 0xC0 <= image[limit] <= 0xC3:
        return None
    register = image[limit] - 0xC0
    sites = []
    for original in limit_originals(register):
        patched = limit_patched(register, len(original))
        current = image[limit + 1 : limit + 1 + len(original)]
        if current in (original, patched):
            sites.append((limit + 1, original, patched, current == patched))
            break
    else:
        return None
    for at in (home, away):
        if at >= len(image) or image[at] not in (JLE, JMP):
            return None
        sites.append((at, bytes([JLE]), bytes([JMP]), image[at] == JMP))
    return sites


# --- Default sound device -------------------------------------------------------
GUID_AT = 6  # where "push &guid" starts
GUID_BEFORE_POINTER = 0x18  # the kept GUID lies 0x18 bytes before the DirectSound pointer
SOUND_PATCHED = bytes([0x56, NOP, NOP, NOP, NOP])  # push esi (0) / nop x4


def sound_pattern(guid):
    """The pattern of the sound device setup, with guid (the GUID's push or its patched bytes) in it."""
    # push esi / push &ds / {push &guid | push esi, nop x4} / call / test eax,eax / je +15 / call / mov [&ds],esi
    return (
        [0x56, 0x68, None, None, None, None]
        + list(guid)
        + [0xE8, None, None, None, None, 0x85, 0xC0, 0x74, 0x15]
        + [0xE8, None, None, None, None, 0x89, 0x35, None, None, None, None]
    )


def sound_sites(image):
    """[(offset, original, patched, is_patched)] for the GUID's push, or None if the exe doesn't match."""
    original = find_all(image, sound_pattern([0x68, None, None, None, None]))
    patched = find_all(image, sound_pattern(SOUND_PATCHED))
    if len(original) + len(patched) != 1:
        return None
    is_patched = len(patched) == 1
    at = patched[0] if is_patched else original[0]
    pointer = struct.unpack_from("<i", image, at + 2)[0]
    # Both mentions of the pointer must agree, and the GUID must sit where it's expected.
    if struct.unpack_from("<i", image, at + 27)[0] != pointer:
        return None
    push = bytes([0x68]) + struct.pack("<i", pointer - GUID_BEFORE_POINTER)
    if not is_patched and image[at + GUID_AT : at + GUID_AT + len(push)] != push:
        return None
    return [(at + GUID_AT, push, SOUND_PATCHED, is_patched)]


# --- Shared helpers for the patches below ------------------------------------------------
def holes(code):
    """Where the wildcards (None) of code are, in order."""
    return [i for i, b in enumerate(code) if b is None]


def is_displacement(code, places, k):
    """Whether the wildcards from the k-th on are four in a row right behind a call or jmp (E8, E9), and no
    more (a pattern never starts with a wildcard)."""
    at = places[k]
    return (
        k + 3 < len(places)
        and places[k + 3] == at + 3
        and code[at - 1] in (0xE8, 0xE9)
        and (at + 4 == len(code) or code[at + 4] is not None)
    )


def rewrite_site(image, original, patched):
    """(offset, original, patched, is_patched) of one block that occurs exactly once, as original or patched
    code of the same length with as many wildcards (None), or None. The bytes at the found code's wildcards
    (addresses, displacements) are kept from the game and go to the wildcards of both, in order; four of them
    right behind a call or jmp in both are its displacement, moved by the difference where the other code
    has it elsewhere, so that it still reaches the same target (A2G-Patch's RewritePatch.FindOnce)."""
    found_original, found_patched = find_all(image, original), find_all(image, patched)
    if len(found_original) + len(found_patched) != 1:
        return None
    is_patched = len(found_patched) == 1
    at = found_patched[0] if is_patched else found_original[0]
    found = patched if is_patched else original
    found_holes = holes(found)
    kept = bytes(image[at + i] for i in found_holes)

    def fill(code):
        places = holes(code)
        result = bytearray(0 if b is None else b for b in code)
        for k, i in enumerate(places):
            result[i] = kept[k]
        for k, i in enumerate(places):
            if is_displacement(code, places, k) and is_displacement(found, found_holes, k):
                value = struct.unpack_from("<i", kept, k)[0] + found_holes[k] - i
                struct.pack_into("<i", result, i, value)
        return bytes(result)

    return (at, fill(original), fill(patched), is_patched)


def rewrite_sites(image, original, patched):
    """[rewrite_site(...)] or None."""
    site = rewrite_site(image, original, patched)
    return None if site is None else [site]


def rewrites_sites(image, places):
    """One rewrite_site per (original, patched) in places, or None unless all of them are there."""
    sites = [rewrite_site(image, original, patched) for original, patched in places]
    return None if None in sites else sites


def opcode_sites(image, code, at, patched_byte, occurrences=1):
    """One byte (a jump's opcode) at code[at] in code that occurs `occurrences` times, each holding the
    original or the patched byte (mixed states are fine; applying finishes them)."""
    original_byte = code[at]
    patched_code = list(code)
    patched_code[at] = patched_byte
    sites = sorted(
        [(s + at, bytes([original_byte]), bytes([patched_byte]), False) for s in find_all(image, code)]
        + [(s + at, bytes([original_byte]), bytes([patched_byte]), True) for s in find_all(image, patched_code)]
    )
    return sites if len(sites) == occurrences else None


# --- Arrow buttons keep counting while held down ------------------------------------------
# mov eax,[esi+F4] / test eax,eax / jne +29: the check before the rewritten branch.
ARROW_CHECK = bytes.fromhex("8b86f400000085c07529")
ARROW_POST_TAIL = bytes.fromhex("8b4e1c6a006a005051ffd3")  # mov ecx,[esi+1C] / push 0,0,eax,ecx / call ebx
ARROW_PENDING = bytes.fromhex("c786f400000001000000")  # mov [esi+F4],1
ARROW_DELAY = bytes.fromhex("c786f00000003c000000")  # mov [esi+F0],60
ARROW_INCREMENT = bytes.fromhex("8b86f4000000")  # mov eax,[esi+F4]
ARROW_STORE = bytes.fromhex("408986f4000000")  # inc eax / mov [esi+F4],eax
ARROW_JUMP_NEXT = bytes.fromhex("eb0a")


def arrow_original(message):
    return b"\xa1" + message + ARROW_POST_TAIL + ARROW_INCREMENT + ARROW_DELAY + ARROW_STORE + ARROW_JUMP_NEXT


def arrow_patched(message):
    return ARROW_PENDING + ARROW_DELAY + b"\xa1" + message + ARROW_POST_TAIL + bytes([NOP] * 3) + ARROW_JUMP_NEXT


ARROW_ORIGINAL_MESSAGE_AT = len(ARROW_CHECK) + 1
ARROW_PATCHED_MESSAGE_AT = len(ARROW_CHECK) + len(ARROW_PENDING) + len(ARROW_DELAY) + 1


def arrow_pattern(branch, message_at):
    """The check followed by branch, the message address (4 bytes at message_at) left open."""
    # The check followed by a branch, the message address left open.
    code = ARROW_CHECK + branch
    return [None if message_at <= i < message_at + 4 else b for i, b in enumerate(code)]


def arrow_sites(image):
    """[(offset, original, patched, is_patched)] for the arrow buttons' branch, or None if the exe doesn't match."""
    original = find_all(image, arrow_pattern(arrow_original(bytes(4)), ARROW_ORIGINAL_MESSAGE_AT))
    patched = find_all(image, arrow_pattern(arrow_patched(bytes(4)), ARROW_PATCHED_MESSAGE_AT))
    if len(original) + len(patched) != 1:
        return None
    is_patched = len(patched) == 1
    at = patched[0] if is_patched else original[0]
    message_at = at + (ARROW_PATCHED_MESSAGE_AT if is_patched else ARROW_ORIGINAL_MESSAGE_AT)
    message = bytes(image[message_at : message_at + 4])
    return [(at + len(ARROW_CHECK), arrow_original(message), arrow_patched(message), is_patched)]


# --- Videos that can't be decoded are skipped instead of crashing ---------------------------
# test eax,eax / je +21 / release: mov ecx,[ebp] / push ecx / call AVIFileRelease / lea ecx,[esp+10] /
# call / xor eax,eax / pop edi,esi,ebp,ebx / add esp,84 / ret C / mov eax,[edi] / lea edx,[esi+8498] /
# push 8C / push edx / push eax / call AVIStreamInfoA
VIDEO_PREFIX = (
    [0x85, 0xC0, 0x74, 0x21, 0x8B, 0x4D, 0x00, 0x51, 0xE8, None, None, None, None]
    + [0x8D, 0x4C, 0x24, 0x10, 0xE8, None, None, None, None, 0x33, 0xC0, 0x5F, 0x5E, 0x5D, 0x5B]
    + [0x81, 0xC4, 0x84, 0x00, 0x00, 0x00, 0xC2, 0x0C, 0x00]
    + [
        0x8B,
        0x07,
        0x8D,
        0x96,
        0x98,
        0x84,
        0x00,
        0x00,
        0x68,
        0x8C,
        0x00,
        0x00,
        0x00,
        0x52,
        0x50,
        0xE8,
        None,
        None,
        None,
        None,
    ]
)
VIDEO_RELEASE = 4  # where "release" starts in the prefix
# lea eax,[esi+8064] / push eax / mov [eax],28 / mov ecx,[esi+84D4] / mov [eax+4],ecx / mov edx,[esi+84D8] /
# mov [eax+8],edx / mov word [eax+C],1 / mov word [eax+E],8 / mov [eax+10..24],ebx /
# mov eax,[edi] / push eax / call AVIStreamGetFrameOpen / mov [esi+848C],eax
VIDEO_ORIGINAL = bytes.fromhex(
    "8d866480000050c70028000000"
    "8b8ed4840000894804"
    "8b96d8840000895008"
    "66c7400c010066c7400e0800"
    "89581089581489581889581c895820895824"
    "8b0750e80000000089868c840000"
)
VIDEO_ORIGINAL_CALL = 65  # the call's displacement in VIDEO_ORIGINAL
# The same setup, tighter (edi = this+0x8494, so +0x84D4/+0x84D8/+0x848C are edi+40/+44/-8; planes and
# bit count in one dword), then: push [edi] / call / test eax,eax / jnz ok / mov [edi],eax / jmp release /
# ok: mov [edi-8],eax / nop x4
VIDEO_PATCHED = bytes.fromhex(
    "8d866480000050c70028000000"
    "8b4f408948048b4f44894808"
    "c7400c01000800"
    "89581089581489581889581c895820895824"
    "ff37e800000000"
    "85c07507"
    "8907e900000000"
    "8947f890909090"
)
VIDEO_PATCHED_CALL = 53
VIDEO_PATCHED_JUMP = 64
VIDEO_CALL_SHIFT = VIDEO_ORIGINAL_CALL - VIDEO_PATCHED_CALL  # the call moves this much towards the start


def video_original(call):
    """VIDEO_ORIGINAL with call as its call's displacement."""
    code = bytearray(VIDEO_ORIGINAL)
    struct.pack_into("<i", code, VIDEO_ORIGINAL_CALL, call)
    return bytes(code)


def video_patched(call):
    """VIDEO_PATCHED for the original's call displacement call, with its jump back to "release"."""
    code = bytearray(VIDEO_PATCHED)
    struct.pack_into("<i", code, VIDEO_PATCHED_CALL, call + VIDEO_CALL_SHIFT)
    # back to "release" in the prefix, from the end of the jump
    struct.pack_into("<i", code, VIDEO_PATCHED_JUMP, VIDEO_RELEASE - (len(VIDEO_PREFIX) + VIDEO_PATCHED_JUMP + 4))
    return bytes(code)


def video_pattern(code, call):
    """VIDEO_PREFIX + code as a find_all pattern, with the call's four displacement bytes at call as wildcards."""
    return VIDEO_PREFIX + [None if call <= i < call + 4 else b for i, b in enumerate(code)]


def video_sites(image):
    """[(offset, original, patched, is_patched)] for the video setup, or None if the exe doesn't match."""
    original = find_all(image, video_pattern(video_original(0), VIDEO_ORIGINAL_CALL))
    patched = find_all(image, video_pattern(video_patched(0), VIDEO_PATCHED_CALL))
    if len(original) + len(patched) != 1:
        return None
    is_patched = len(patched) == 1
    at = (patched[0] if is_patched else original[0]) + len(VIDEO_PREFIX)
    if is_patched:
        call = struct.unpack_from("<i", image, at + VIDEO_PATCHED_CALL)[0] - VIDEO_CALL_SHIFT
    else:
        call = struct.unpack_from("<i", image, at + VIDEO_ORIGINAL_CALL)[0]
    return [(at, video_original(call), video_patched(call), is_patched)]


# --- No freeze after 24.9 days of uptime -----------------------------------------------------
# sub eax,[ebp+17C] / cmp eax,0BB8 / mov [ebp+17C],eax / jge skip (7D) -> jae skip (73), two places
FREEZE_CODE = list(bytes.fromhex("2b857c0100003db80b000089857c0100007d0e"))


def freeze_sites(image):
    return opcode_sites(image, FREEZE_CODE, 17, 0x73, occurrences=2)


# --- No false "disk almost full" warning when saving ----------------------------------------
# imul eax,[esp+?] / cmp eax,177000 / jae ok (73 -> EB) / lea ecx,[esp+?] / push 0AC1 (the warning's text)
DISK_CODE = [0x0F, 0xAF, 0x44, 0x24, None, 0x3D, 0x00, 0x70, 0x17, 0x00, 0x73, None, 0x8D, 0x4C, 0x24, None]
DISK_CODE += [0x68, 0xC1, 0x0A, 0x00, 0x00]


def disk_sites(image):
    return opcode_sites(image, DISK_CODE, 10, 0xEB)


# --- Squad never grows past 30 players ---------------------------------------------------------
# push [esp+4] / call forecast / add esp,4 / xor ecx,ecx / cmp ax,1E / setge cl / mov eax,ecx / ret / nop x7
SQUAD_ORIGINAL = [0x8B, 0x44, 0x24, 0x04, 0x50, 0xE8, None, None, None, None, 0x83, 0xC4, 0x04, 0x33, 0xC9]
SQUAD_ORIGINAL += [0x66, 0x3D, 0x1E, 0x00, 0x0F, 0x9D, 0xC1, 0x8B, 0xC1, 0xC3] + [NOP] * 7
# push [esp+4] / call forecast / pop ecx / cmp ax,1E / jge full / cmp word [ecx+E6],1E /
# full: setge al / movzx eax,al / ret
SQUAD_PATCHED = [0x8B, 0x44, 0x24, 0x04, 0x50, 0xE8, None, None, None, None, 0x59]
SQUAD_PATCHED += [0x66, 0x3D, 0x1E, 0x00, 0x7D, 0x08, 0x66, 0x83, 0xB9, 0xE6, 0x00, 0x00, 0x00, 0x1E]
SQUAD_PATCHED += [0x0F, 0x9D, 0xC0, 0x0F, 0xB6, 0xC0, 0xC3]


def squad_sites(image):
    return rewrite_sites(image, SQUAD_ORIGINAL, SQUAD_PATCHED)


# --- Investments: their growth no longer taken off the bank balance -----------------------------
# push esi / mov esi,[esp+8] / push edi / push esi / call values / mov edi,[esi] / add esp,4 / sub edi,eax /
# push esi / call loans / add esp,4 / add edi,eax / push esi / call bookings / add esp,4 / add eax,edi /
# pop edi / pop esi / ret / nop x4
INVEST_ORIGINAL = [0x56, 0x8B, 0x74, 0x24, 0x08, 0x57, 0x56, 0xE8, None, None, None, None, 0x8B, 0x3E, 0x83, 0xC4]
INVEST_ORIGINAL += [0x04, 0x2B, 0xF8, 0x56, 0xE8, None, None, None, None, 0x83, 0xC4, 0x04, 0x03, 0xF8]
INVEST_ORIGINAL += [0x56, 0xE8, None, None, None, None, 0x83, 0xC4, 0x04, 0x03, 0xC7, 0x5F, 0x5E, 0xC3] + [NOP] * 4
INVEST_ORIGINAL_VALUES, INVEST_ORIGINAL_LOANS, INVEST_ORIGINAL_BOOKINGS = 8, 21, 32  # the calls' displacements
# push esi / mov esi,[esp+8] / push esi / call loans / add eax,[esi] / sub esi,-80 / push 6 / pop ecx /
# next: test byte [esi+33],1 / je skip / sub eax,[esi+28] / skip: add esi,10 / loop next /
# pop esi / push eax / push esi / call bookings / pop ecx / pop ecx / add eax,ecx / pop esi / ret / nop
INVEST_PATCHED = [0x56, 0x8B, 0x74, 0x24, 0x08, 0x56, 0xE8, None, None, None, None, 0x03, 0x06, 0x83, 0xEE, 0x80]
INVEST_PATCHED += [0x6A, 0x06, 0x59, 0xF6, 0x46, 0x33, 0x01, 0x74, 0x03, 0x2B, 0x46, 0x28, 0x83, 0xC6, 0x10, 0xE2]
INVEST_PATCHED += [0xF2, 0x5E, 0x50, 0x56, 0xE8, None, None, None, None, 0x59, 0x59, 0x03, 0xC1, 0x5E, 0xC3, NOP]
INVEST_PATCHED_LOANS, INVEST_PATCHED_BOOKINGS = 7, 37
# "values" lies 0x20 bytes behind "loans" in every build, seen from the original's two calls.
INVEST_VALUES_BEHIND_LOANS = 0x20 + (INVEST_ORIGINAL_LOANS + 4) - (INVEST_ORIGINAL_VALUES + 4)


def with_displacements(pattern, *pairs):
    """pattern's bytes (None as 0) with each (displacement, place) written."""
    code = bytearray(0 if b is None else b for b in pattern)
    for displacement, place in pairs:
        struct.pack_into("<i", code, place, displacement)
    return bytes(code)


def invest_original(loans, bookings):
    """INVEST_ORIGINAL with the displacements of its three calls ("values" derived from loans)."""
    values = loans + INVEST_VALUES_BEHIND_LOANS
    return with_displacements(
        INVEST_ORIGINAL,
        (values, INVEST_ORIGINAL_VALUES),
        (loans, INVEST_ORIGINAL_LOANS),
        (bookings, INVEST_ORIGINAL_BOOKINGS),
    )


def invest_patched(loans, bookings):
    """INVEST_PATCHED calling loans and bookings (given as the original's displacements)."""
    return with_displacements(
        INVEST_PATCHED,
        (loans + INVEST_ORIGINAL_LOANS - INVEST_PATCHED_LOANS, INVEST_PATCHED_LOANS),
        (bookings + INVEST_ORIGINAL_BOOKINGS - INVEST_PATCHED_BOOKINGS, INVEST_PATCHED_BOOKINGS),
    )


def invest_sites(image):
    """[(offset, original, patched, is_patched)] for the investments function, or None if the exe doesn't match."""
    original, patched = find_all(image, INVEST_ORIGINAL), find_all(image, INVEST_PATCHED)
    if len(original) + len(patched) != 1:
        return None
    is_patched = len(patched) == 1
    at = patched[0] if is_patched else original[0]

    def displacement(place):
        return struct.unpack_from("<i", image, at + place)[0]

    if is_patched:
        loans = displacement(INVEST_PATCHED_LOANS) - (INVEST_ORIGINAL_LOANS - INVEST_PATCHED_LOANS)
        bookings = displacement(INVEST_PATCHED_BOOKINGS) - (INVEST_ORIGINAL_BOOKINGS - INVEST_PATCHED_BOOKINGS)
    else:
        loans, bookings = displacement(INVEST_ORIGINAL_LOANS), displacement(INVEST_ORIGINAL_BOOKINGS)
        if displacement(INVEST_ORIGINAL_VALUES) != loans + INVEST_VALUES_BEHIND_LOANS:
            return None
    return [(at, invest_original(loans, bookings), invest_patched(loans, bookings), is_patched)]


# --- Negotiation lock wears off monthly (balancing) ------------------------------------------------
def negotiation_code(first):
    """The code that halves the four counters from [ebp+0x1000+first] (load, shr 1, push ebp, store)."""
    # mov cl/al/bl/dl,[ebp+first..] / shr cl/al/bl/dl,1 / push ebp / mov [ebp+first..],cl/al/bl/dl
    loads = [0x8D, 0x85, 0x9D, 0x95]
    code = []
    for i, modrm in enumerate(loads):
        code += [0x8A, modrm, first + i, 0x10, 0x00, 0x00]
    code += [0xD0, 0xE9, 0xD0, 0xE8, 0xD0, 0xEB, 0xD0, 0xEA, 0x55]
    for i, modrm in enumerate(loads):
        code += [0x88, modrm, first + i, 0x10, 0x00, 0x00]
    return code


def negotiation_sites(image):
    # +0x107D..0x1080 (one byte too low) -> +0x1081..0x1084, the four counters of the human managers
    return rewrite_sites(image, negotiation_code(0x7D), negotiation_code(0x81))


# --- Unfitting pre-match speeches weaken the team (balancing) -------------------------------------
SPEECH_ROLL_HEAD = [0xE8, None, None, None, None]  # call (the message)
SPEECH_ROLL_TAIL = bytes.fromhex("eb366a04e8")  # jmp +36 / push 4 / call
SPEECH_ROLL_ORIGINAL, SPEECH_ROLL_PATCHED = bytes.fromhex("33ff"), bytes.fromhex("33db")  # xor edi,edi -> xor ebx,ebx
SPEECH_MARK_HEAD = [0x8D, 0x8C, 0x24, 0xA0, 0x06, 0x00, 0x00, 0xE8, None, None, None, None]  # lea ecx,[esp+6A0] / call
SPEECH_MARK_TAIL = bytes.fromhex("8d8c2488080000")  # lea ecx,[esp+888]
# test ebx,ebx / je / test edi,edi / je / mov eax,[esp+17C0] / mov byte [eax+E4],1 / mov cl,[ebp+1440] /
# mov [eax+E5],cl / mov word [eax+1C],64
SPEECH_MARK_ORIGINAL = bytes.fromhex(
    "85db742485ff74208b8424c0170000c680e4000000018a8d401400008888e5000000" "66c7401c6400"
)
# dec ebx / jne / mov eax,[esp+17C0] / sub eax,-80 / mov cl,[ebp+1440] / test edi,edi / je / mov byte [eax+64],1 /
# mov word [eax-64],64 / cmp ax,D9F6 (skips "neg cl") / mov [eax+65],cl
SPEECH_MARK_PATCHED = bytes.fromhex(
    "4b75258b8424c017000083e8808a8d4014000085ff740cc64064016" "6c7409c6400663df6d9884865"
)
# the function at 0x4c4bd0 (cdecl: team block, match, home) with its padding; None: the speech table's addresses
# fmt: off
SPEECH_APPLY_ORIGINAL = list(bytes.fromhex(
    "568b742408578a86e500000084c00f848f000000" "25ff0000008d3c80c1e702f687"
)) + [None] * 4 + list(bytes.fromhex(
    "0174226683 7c2414008b4424107 40c668b4810663b48 0e7f65eb0a668b500e663b50107f590fbe8f".replace(" ", "")
)) + [None] * 4 + list(bytes.fromhex(
    "0fbf461083c1640fafc8b81f85eb51f7e9c1fa058bcab81f85eb51c1e91f03d1668956100fbe8f"
)) + [None] * 4 + list(bytes.fromhex(
    "0fbf561683c1640fafcaf7e9c1fa058bc2c1e81f03d0668956168a87"
)) + [None] * 4 + list(bytes.fromhex("3c637403884631" "5f5ec3" "90909090909090909090"))
SPEECH_APPLY_PATCHED = list(bytes.fromhex(
    "568b742408575 30fbe86e5000000998bda33c22bc27460 8d3c80c1e702f687".replace(" ", "")
)) + [None] * 4 + list(bytes.fromhex(
    "017422 66837c2418008b44241474 0c668b4810663b480e7f3beb0a668b500e663b50107f2f0fbe8f".replace(" ", "")
)) + [None] * 4 + list(bytes.fromhex("8d4610e8240000000fbe8f")) + [None] * 4 + list(bytes.fromhex(
    "8d4616e81500000085db750d8a87"
)) + [None] * 4 + list(bytes.fromhex(
    "3c63740388463 15b5f5ec385db740685c97c02f7d9500fbf0083c1640fafc8b81f85eb51f7e9c1fa058bcac1e91f03d158668910c3"
    .replace(" ", "")
)) + [0xCC] * 11
# fmt: on
# Where the two versions read the speech table, and the fields they read: flags, defence, attack, hardness.
SPEECH_ORIGINAL_REFS, SPEECH_PATCHED_REFS = (0x21, 0x4D, 0x78, 0x98), (0x1F, 0x4B, 0x5A, 0x6C)
SPEECH_TABLE_FIELDS = (0x10, 0x0C, 0x0D, 0x0E)


def speech_with_table(code, refs, table):
    """code (None as 0) with the speech table's address plus each field written at refs."""
    data = bytearray(0 if b is None else b for b in code)
    for ref, field in zip(refs, SPEECH_TABLE_FIELDS):
        struct.pack_into("<I", data, ref, table + field)
    return bytes(data)


def speech_place(image, head, original, patched, tail):
    """(offset, original, patched, is_patched) of the code between head and tail, or None unless found once."""
    found = find_all(image, head + list(original) + list(tail))
    found_patched = find_all(image, head + list(patched) + list(tail))
    if len(found) + len(found_patched) != 1:
        return None
    is_patched = len(found_patched) == 1
    return ((found_patched if is_patched else found)[0] + len(head), original, patched, is_patched)


def speech_apply(image):
    """(offset, original, patched, is_patched) for the speech function, or None if it doesn't match."""
    found, found_patched = find_all(image, SPEECH_APPLY_ORIGINAL), find_all(image, SPEECH_APPLY_PATCHED)
    if len(found) + len(found_patched) != 1:
        return None
    is_patched = len(found_patched) == 1
    at = (found_patched if is_patched else found)[0]
    refs = SPEECH_PATCHED_REFS if is_patched else SPEECH_ORIGINAL_REFS
    tables = {struct.unpack_from("<I", image, at + r)[0] - f for r, f in zip(refs, SPEECH_TABLE_FIELDS)}
    if len(tables) != 1:
        return None
    table = tables.pop()
    original = speech_with_table(SPEECH_APPLY_ORIGINAL, SPEECH_ORIGINAL_REFS, table)
    patched = speech_with_table(SPEECH_APPLY_PATCHED, SPEECH_PATCHED_REFS, table)
    return (at, original, patched, is_patched)


def speech_sites(image):
    """The three places of the speech patch (roll, mark, apply), or None if one of them doesn't match."""
    sites = [
        speech_place(image, SPEECH_ROLL_HEAD, SPEECH_ROLL_ORIGINAL, SPEECH_ROLL_PATCHED, SPEECH_ROLL_TAIL),
        speech_place(image, SPEECH_MARK_HEAD, SPEECH_MARK_ORIGINAL, SPEECH_MARK_PATCHED, SPEECH_MARK_TAIL),
        speech_apply(image),
    ]
    return None if None in sites else sites


# --- Trainer supply: former players from 33, otherwise competence 3 to 11 (balancing) -------------
def wild(*hex_lines):
    """Bytes from hex, ".." as a wildcard (None)."""
    h = "".join(hex_lines)
    return [None if h[i : i + 2] == ".." else int(h[i : i + 2], 16) for i in range(0, len(h), 2)]


# Generated from A2G-Patch's CoachSupply (Patches.cs): the age check before a retiring player gets on the
# trainers' waiting list, and the two functions that fill a place of the trainer/manager pool
# (0x5a1500) and of the goalkeeper trainers (0x5a15c0) from that list or, without an entry, with
# the same person at age 30 (35) and competence 2. Patched, both are rewritten in their own bytes: the list
# as before, else competence 3 + four times random(3) (3 to 11, most often 7).
# fmt: off
COACH_ORIGINAL = wild(
    "0fbf44240853660fb688........0fbfc933c08d0c89c1e1020fbfd003d16683"
    "3cd5........00752d40663d14007ce98b4424088a48058a50043acac640071e"
    "7e0ac6400502c64004015bc3c6400501c64004025bc30fbfc003c18b4c2408c1"
    "e0038a5904668b90........668911668b90........668951028a51053ad38a"
    "90........7e118851050fbed28a92........885104eb0f8851040fbed28a92"
    "........8851058a90........5b88510766c780........0000c3"
)  # 187 bytes
COACH_PATCHED = wild(
    "5356578b7c24100fbf4424140fb680........8d0480c1e0058db0........6a"
    "145966833e00751f83c608e2f5b3036a046a03e8........02d858ff0c2475f1"
    "58b01eb401eb188b0689078a5e0666c70600000fb6c38aa0........8a460488"
    "47078a4f043a4f057c08885f04886705eb06885f058867045f5e5bc390909090"
    "9090909090909090909090909090909090909090909090909090909090909090"
    "909090909090909090909090909090909090909090909090909090"
)  # 187 bytes
KEEPER_ORIGINAL = wild(
    "0fbf442408660fb688........0fbfc933c08d0c89d1e10fbfd003d166833cd5"
    "........00751440663d0a007ce98b442404c6400723c6400402c30fbfc003c1"
    "8b4c2404c1e003668b90........668911668b90........668951028a90...."
    "....8851048a90........88510766c780........0000c3"
)  # 120 bytes
KEEPER_PATCHED = wild(
    "5356578b7c24100fbf4424140fb680........6bc0508db0........6a0a5966"
    "833e00751d83c608e2f5b3036a046a03e8........02d858ff0c2475f158b023"
    "eb0f8b0689078a5e0666c70600008a4604884707885f045f5e5bc39090909090"
    "909090909090909090909090909090909090909090909090"
)  # 120 bytes
COACH_AGE_PATTERN = wild(
    "8a561e660386..00000080fa..0f869e010000"
)  # 19 bytes
# fmt: on
COACH_AGE_AT, COACH_AGE_ORIGINAL, COACH_AGE_PATCHED = 12, 35, 32  # cmp dl,{age} / jbe: not on the list
COACH_RANDOM_CALL, COACH_RANDOM_CALL_AT = bytes.fromhex("6a03e8"), 0x52  # push 3 / call random, behind the check
COACH_ORIGINAL_PLACES = (10, 34, 104, 114, 129, 143, 160, 169, 180)
COACH_PATCHED_PLACES = (15, 27, 52, 88)
KEEPER_ORIGINAL_PLACES = (9, 32, 74, 84, 94, 103, 113)
KEEPER_PATCHED_PLACES = (15, 24, 49)
PUSH_EBX = 0x53  # how both patched functions start (the originals with movsx)


def fill(pattern, places, *values):
    """pattern's bytes (None as 0) with each value written as u32 at its place."""
    code = bytearray(0 if b is None else b for b in pattern)
    for place, value in zip(places, values):
        struct.pack_into("<I", code, place, value & 0xFFFFFFFF)
    return bytes(code)


def coach_original(group, lst, table):
    values = (group, lst, lst, lst + 2, lst + 6, table, table, lst + 4, lst)
    return fill(COACH_ORIGINAL, COACH_ORIGINAL_PLACES, *values)


def coach_patched(group, lst, table, random):
    """random: the random function's distance to the function's start."""
    return fill(COACH_PATCHED, COACH_PATCHED_PLACES, group, lst, random - (COACH_PATCHED_PLACES[2] + 4), table)


def keeper_original(group, lst):
    return fill(KEEPER_ORIGINAL, KEEPER_ORIGINAL_PLACES, group, lst, lst, lst + 2, lst + 6, lst + 4, lst)


def keeper_patched(group, lst, random):
    """random: the random function's distance to the function's start."""
    return fill(KEEPER_PATCHED, KEEPER_PATCHED_PLACES, group, lst, random - (KEEPER_PATCHED_PLACES[2] + 4))


def coach_sites(image):
    """[(offset, original, patched, is_patched)] for the age check and both pool functions, or None."""
    ages = [
        at
        for at in find_all(image, COACH_AGE_PATTERN)
        if image[at + COACH_AGE_AT] in (COACH_AGE_ORIGINAL, COACH_AGE_PATCHED)
    ]

    def one(original, patched):
        found = find_all(image, original) + find_all(image, patched)
        return found[0] if len(found) == 1 else None

    coach, keeper = one(COACH_ORIGINAL, COACH_PATCHED), one(KEEPER_ORIGINAL, KEEPER_PATCHED)
    if len(ages) != 1 or coach is None or keeper is None:
        return None
    age = ages[0]
    if image[age + COACH_RANDOM_CALL_AT : age + COACH_RANDOM_CALL_AT + 3] != COACH_RANDOM_CALL:
        return None
    call = age + COACH_RANDOM_CALL_AT + 2
    random = call + 5 + struct.unpack_from("<i", image, call + 1)[0]  # in the same section as both functions

    def u32(at):
        return struct.unpack_from("<I", image, at)[0]

    coach_is_patched, keeper_is_patched = image[coach] == PUSH_EBX, image[keeper] == PUSH_EBX
    places = (15, 27, 88) if coach_is_patched else (10, 34, 143)
    group, lst, table = (u32(coach + p) for p in places)
    keeper_list = u32(keeper + (24 if keeper_is_patched else 32))
    sites = [
        (
            age + COACH_AGE_AT,
            bytes([COACH_AGE_ORIGINAL]),
            bytes([COACH_AGE_PATCHED]),
            image[age + COACH_AGE_AT] == COACH_AGE_PATCHED,
        ),
        (coach, coach_original(group, lst, table), coach_patched(group, lst, table, random - coach), coach_is_patched),
        (
            keeper,
            keeper_original(group, keeper_list),
            keeper_patched(group, keeper_list, random - keeper),
            keeper_is_patched,
        ),
    ]
    # Each place holds one of its two versions exactly (which also checks that both use the same group table).
    if all(bytes(image[at : at + len(o)]) == (n if done else o) for at, o, n, done in sites):
        return sites
    return None


# --- Money limit: the club's ledger stops at 2 billion DM instead of running over (bug fix) --------
# Generated from A2G-Patch's MoneyLimit (Patches.cs). The week's result (0x572660) adds up the same
# fields as the bookings (0x570f80, 0x100 behind its first callee), which also subtract +338 and add
# +33C. Rewritten as a call of the bookings that takes those two back, it frees its bytes from 0x20 on
# for the check, and the booking of the ledger (club +154) jumps there.
MONEY_LIMIT = 2_000_000_000
MONEY_LIMIT_HEX = struct.pack("<i", MONEY_LIMIT).hex()
# fmt: off
MONEY_WEEK_ORIGINAL = wild(
    "8b44240456578db85401000057e8........8bb73c0200008b97280300008b8f580200002bf28b971803000003f18b8f1c030000"
    "03f28b970802000003f18b8f000200002bf28b972c0300002bf18b8f1802000003f28b97100200002bf18b8f540200002bf2"
    "8b97ac0100002bf18b8fb40100002bf28b97800100002bf18b8ff80100002bf28b97f00100002bf18b8fdc0100002bf2"
    "8b977c0100002bf18b8f7401000003f28b976c01000083c40403f103f2572bf0e8........83c4042bf057e8........"
    "83c40403f08bc65f5ec3"
)  # 208 bytes
# mov eax,[esp+4] / add eax,154 / push eax / call bookings / pop ecx / add eax,[ecx+338] / sub eax,[ecx+33C] /
# ret / nop x3 / check: mov ecx,[esi+154] / mov eax,ecx / add eax,edi / jno sum / mov eax,edi / sar eax,31 /
# xor eax,7FFFFFFF / sum: cmp eax,limit / jle store / cmp eax,ecx / jle store / mov eax,limit / cmp eax,ecx /
# jge store / mov eax,ecx / store: pop edi / mov [esi+154],eax / pop esi / pop ebx / add esp,24 / ret / nop...
MONEY_WEEK_PATCHED = wild(
    "8b442404055401000050e8........59038138030000" "2b813c030000c3909090"
    "8b8e540100008bc103c7710a8bc7c1f81f35ffffff7f3d" + MONEY_LIMIT_HEX + "7e0f3bc17e0bb8" + MONEY_LIMIT_HEX
    + "3bc17d028bc15f8986540100005e5b83c424c3" + "90" * (208 - 0x59)
)  # 208 bytes
MONEY_BOOKINGS = wild(
    "568b7424085756e8........8bbe6c0100008b96800100008b8eb40100002bfa8b96ac0100002bf98b8edc0100002bfa"
    "8b96f80100002bf98b8ef00100002bfa8b967c0100002bf98b8e7401000003fa8b963c02000003f98b8e3803000003fa"
    "8b96280300002bf98b8e580200002bfa8b962c03000003f98b8e1802000003fa8b96100200002bf98b8e3c0300002bfa"
    "8b960802000003f98b8e000200002bfa8b96180300002bf98b8e1c03000003fa8b965402000083c40403f92bfa562bf8"
    "e8........83c4042bf856e8........83c40403c75f5ec3"
)  # 216 bytes
# The booking, behind the call that ends the human clubs' statistics (call / add esp,8):
# mov eax,[esi+154] / add eax,edi / pop edi / mov [esi+154],eax / pop esi / pop ebx / add esp,24 / ret / nop x2
MONEY_BOOKING_ORIGINAL = wild("e8........83c408" "8b865401000003c75f8986540100005e5b83c424c39090")
MONEY_BOOKING_PATCHED = wild("e8........83c408" "e9........" + "90" * 18)  # jmp check / nop x18
# fmt: on
MONEY_WEEK_CALLS = (0x0D, 0xB6, 0xC1)  # the same three functions as the bookings' calls
MONEY_BOOKINGS_CALLS = (0x07, 0xC0, 0xCB)
MONEY_WEEK_PATCHED_CALL, MONEY_CHECK_AT = 0x0A, 0x20
MONEY_BOOKINGS_BEHIND_FIRST = 0x100
MONEY_BOOKING_AT = 8


def with_calls(pattern, at, calls):
    """pattern's bytes (None as 0) at offset at, with each (place, target) as a call or jump at place."""
    code = bytearray(0 if b is None else b for b in pattern)
    for place, target in calls:
        struct.pack_into("<i", code, place + 1, target - (at + place + 5))
    return bytes(code)


def call_target(image, at):
    """Where the call or jump at at leads."""
    return at + 5 + struct.unpack_from("<i", image, at + 1)[0]


def money_sites(image):
    """[(offset, original, patched, is_patched)] for the week's result and the booking, or None."""

    def one(original, patched):
        found = find_all(image, original) + find_all(image, patched)
        return found[0] if len(found) == 1 else None

    week = one(MONEY_WEEK_ORIGINAL, MONEY_WEEK_PATCHED)
    booking = one(MONEY_BOOKING_ORIGINAL, MONEY_BOOKING_PATCHED)
    if week is None or booking is None:
        return None
    booking += MONEY_BOOKING_AT
    week_patched, booking_patched = image[week + MONEY_WEEK_PATCHED_CALL] == 0xE8, image[booking] == 0xE9
    if week_patched:
        bookings = call_target(image, week + MONEY_WEEK_PATCHED_CALL)
    else:
        bookings = call_target(image, week + MONEY_WEEK_CALLS[0]) + MONEY_BOOKINGS_BEHIND_FIRST
    if not 0 <= bookings <= len(image) - len(MONEY_BOOKINGS):
        return None
    if find_all(image[bookings : bookings + len(MONEY_BOOKINGS)], MONEY_BOOKINGS) != [0]:
        return None
    calls = [call_target(image, bookings + at) for at in MONEY_BOOKINGS_CALLS]
    if (
        calls[0] + MONEY_BOOKINGS_BEHIND_FIRST != bookings
        or not week_patched
        and [call_target(image, week + at) for at in MONEY_WEEK_CALLS] != calls
        or booking_patched
        and call_target(image, booking) != week + MONEY_CHECK_AT
    ):
        return None
    jump = with_calls(MONEY_BOOKING_PATCHED[MONEY_BOOKING_AT:], booking, [(0, week + MONEY_CHECK_AT)])
    return [
        (
            week,
            with_calls(MONEY_WEEK_ORIGINAL, week, zip(MONEY_WEEK_CALLS, calls)),
            with_calls(MONEY_WEEK_PATCHED, week, [(MONEY_WEEK_PATCHED_CALL, bookings)]),
            week_patched,
        ),
        (booking, bytes(MONEY_BOOKING_ORIGINAL[MONEY_BOOKING_AT:]), jump, booking_patched),
    ]


# --- Random events do what their message says (bug fix) ---------------------------------------------
# Generated from A2G-Patch's EventEffects (Patches.cs), texts of TEXTE\EreigGld.saq, places in the 1999 CD
# version: the money events (0x556900) book +38C as expenses and +390 as income, so 690 (a free copier
# saves money), 697 (a prize draw costs), 126 (cups for the fan club's tournament), 143 (selling a plot) and
# 172 (the fans' donations) get the other sign or booking; the chocolate sponsor (224) books twice the amount
# after a won negotiation, as offered; four events that say a player loses freshness pass a positive value
# to 0x623cc0, which takes it (a negative one gives it); 56 plays the positive sound; 38 injures the player the
# text names; 392 no longer appends text 393; kind 62 of the referee events' injury (no name) becomes 68,
# "Fischvergiftung"; the riot (284) shows its text with both amounts; 339 and 343 change the form as their
# texts say (0x565a50, 0x565bc0, as far from the places in every build); the building delay draws
# all 12 reasons and drops "wegen" from the two that start with it. Some places move a call (their
# displacement is moved with it, see rewrite_site).
# fmt: off
EVENT_PLACES = (
    (  # 690
        wild("b202000088ffffff"),
        wild("b202000078000000"),
    ),
    (  # 697
        wild("b902000050000000"),
        wild("b9020000b0ffffff"),
    ),
    (  # 126
        wild("6a7e6a6256e8........83c414566a006a016a00e8........83c410e9e70a0000"),
        wild("6a7e6a6256e8........83c414566a006a016a00e8........83c410e923120000"),
    ),
    (  # 143
        wild("688f0000006a6256e8........8bae8c03000083c41403ef6af65389ae8c030000"),
        wild("688f0000006a6256e8........8bae9003000083c41403ef6af65389ae90030000"),
    ),
    (  # 172
        wild("68ac0000006a6256e8........e9a1060000"),
        wild("68ac0000006a6256e8........e965ffffff"),
    ),
    (  # 224
        wild("6685c00f85........663905........5375156a036a006a006a00e8"),
        wild("6685c00f85........3805........53751603ff6a0333c0505050e8"),
    ),
    (  # 307
        wild("68330100006a6055e8........83c4146afe56e8........83c4086afb56e8"),
        wild("68330100006a6055e8........83c4146afe56e8........83c4086a0556e8"),
    ),
    (  # 308
        wild("68340100006a6055e8........83c4146afb56e8"),
        wild("68340100006a6055e8........83c4146a0556e8"),
    ),
    (  # 369
        wild("68710100006a6055e8........83c4146af656e8"),
        wild("68710100006a6055e8........83c4146a0a56e8"),
    ),
    (  # 414
        wild("689e0100006a6055e8........83c4186af657e8........83c4086af656e8"),
        wild("689e0100006a6055e8........83c4186a0a57e8........83c4086a0a56e8"),
    ),
    (  # 56
        wild("6a026a386a6356e8"),
        wild("6a016a386a6356e8"),
    ),
    (  # 38
        wild("83c40c6a076a3253e8"),
        wild("83c40c6a076a3255e8"),
    ),
    (  # 392
        wild("f64328040f84ca0000008d430c"),
        wild("f6432804e9cb000000908d430c"),
    ),
    (  # 732, the table
        wild("3e001400524150544f52"),
        wild("44001400524150544f52"),
    ),
    (  # 284
        wild("681a010000b9........e8e30700008bf883c9ff33c08d542438f2aef7d12bf98bc18bf78bfac1e902f3a58bc883e103"
             "f3a48b35........56e8........8b0d........83c4045051e8........83c404b9........50681b010000e8910700"
             "008d9424340200005052e8........83c4108d84242c0200008d4c243850516a026a5b53"),
        wild("b9........8ba96c0400008b35........56e8........8bf08d7c243c6a0859f3a5ff35........e8........8d4c24"
             "40890c2450b9........ffb1740400008d94243c02000052e8........83c4105e8d84242c02000050556a026a5b5390"
             "909090909090909090909090909090909090909090909090909090909090909090909090"),
    ),
    (  # 339
        wild("6a025668530100006a6055e8........8b853003000083c41403c6898530030000"),
        wild("6a025668530100006a6055e8........01b5300300006a0155e88263000083c41c"),
    ),
    (  # 343
        wild("6a02505068570100006a6055e8........83c4186a1455e8........83c40866b801005f5e5d5b81c460080000c3"),
        wild("6aff506a02505068570100006a6055e8........83c418e8276400006a1455e8........83c410eba39090909090"),
    ),
    (  # 876/877, the reason
        wild("6a0ae8........8b3c85........83c4046a02e8"),
        wild("6a0ce8........8b3c85........83c4046a02e8"),
    ),
    (  # 876/877, the message
        wild("6a02e8........83c404b9........85c00fbff6577432e810b5ffff8d4e415051686c030000b9........e8fcb4ffff"
             "8d54242c5052e8........8a84338408000083c410fec0eb30e8deb4ffff508d464150686d030000b9........e8cab4"
             "ffff8d4c242c5051e8........8a84338408000083c4100402"),
        wild("6a02e8........590fbff6f7d81bc04050b9........57e810b5ffff813877656765750383c006508d4e41518b442408"
             "056c03000050b9........e8ecb4ffff508d54243452e8........83c410588a8c33840800008d440801eb1d........"
             "90........9090909090909090909090909090909090909090"),
    ),
)
# fmt: on


def event_sites(image):
    return rewrites_sites(image, EVENT_PLACES)


# --- No crash on events without a fitting player (bug fix) -----------------------------------------
# Generated from A2G-Patch's EventCrashes: the functions at 0x564ee0 and 0x564c40 (a player of the squad, a fit
# one) return NULL if nobody fits; four of their callers (events 321, 366, 244 and the message at 0x5bb160) read
# through it without a test. Each gets one, in its own bytes (pop ecx twice instead of add esp,8).
# fmt: off
CRASH_PLACES = (
    (  # 321
        wild("6a0155e8........8bf083c408807e250a0f8e501b0000807e1f030f86461b000080bec0000000020f8c391b0000"),
        wild("6a0155e8........59599685f67415807e250a7e0f807e1f03760980bec0000000027d0ae93e1b00009090909090"),
    ),
    (  # 366
        wild("33f6b31e6a0155e8........8a481e83c4083acb760980b8c0000000017407466683fe057cde"),
        wild("33f6b31e6a0155e8........595985c0740e38581e760980b8c00000000174064683fe057cde"),
    ),
    (  # 244
        wild("6a0157e8........83c4088bf06a025668f40000006a6157e8........83c4146a5a6a4d56e8........83c40c"),
        wild("6a0157e8........59598bf085f674e26a025668f40000006a6157e8........6a5a6a4d56e8........83c420"),
    ),
    (  # the message (0x5bb160)
        wild("6a0fe8........83c40485c0751a6a0156e8........0fbf0083c408506a3d56e8........83c40c5f5e5d5bc3"),
        wild("6a0fe8........5985c0751c6a0156e8........595985c0740eff306a3d56e8........83c40c905f5e5d5bc3"),
    ),
)
# fmt: on


def crash_sites(image):
    return rewrites_sites(image, CRASH_PLACES)


# --- A referee's grudge hits the right club in the match's scenes (bug fix) ----------------------------
# A2G-Patch's RefereeGrudge: a referee's record holds at +7 the club he holds a grudge against, or -1; the
# match copies it to +22E. The cards compare it with the club's number, the scenes he decides (0x404ec0)
# with the number plus one and skip 0, so they hit the club with the next lower number. The patch drops
# both (no grudge, -1, never equals a number from 0 to 255):
#     mov ax,[ebx+22E] / test ax,ax / je / xor edx,edx / mov dl,[edi+102] / movsx eax,ax / inc edx / cmp / jne
#     ->  ... / test ax,ax / nop x2 / ... / nop / cmp eax,edx / jne
REFEREE_ORIGINAL = wild("668b832e0200006685c0742733d28a97020100000fbfc0423bc27517")
REFEREE_PATCHED = wild("668b832e0200006685c0909033d28a97020100000fbfc0903bc27517")


def referee_sites(image):
    return rewrite_sites(image, REFEREE_ORIGINAL, REFEREE_PATCHED)


# --- Trainers and managers in weak countries improve yearly (bug fix) ---------------------------------
# Generated from A2G-Patch's CompetenceBalance: the yearly balance of a country's competence (0x5cc740)
# with an average under 6 adds 1 or 2 points for every tenth person to the sum, but never stores the new
# value; the patch stores it (mov [edi],ax), in the same 36 bytes.
# fmt: off
COMPETENCE_ORIGINAL = wild(
    "668b1783c404400fbfca0fbfe803e983fd0f7e07b80f0000002bc20fbfc003d866ff044e"
)
COMPETENCE_PATCHED = wild(
    "0fbf1783c404400fbfc003c283f80f7e05b80f0000006689072bc203d80fbf0f66ff044e"
)
# fmt: on


def competence_sites(image):
    return rewrite_sites(image, COMPETENCE_ORIGINAL, COMPETENCE_PATCHED)


# --- Appearances without a mark kept out of the average (bug fix) -------------------------------------
# A2G-Patch's GradeAverage: the player's season average (0x4fbd60) and the fans' check for a hated
# player (0x639f70) test mark and cards together (test al,1F), so a short appearance with a card counts
# as mark 0. Both test the mark alone (bits 2-4), as the team statistics do:
#     test al,80 / je skip / test al,1F / je skip   ->   ... / test al,1C / ...
GRADE_CODE = bytes.fromhex("a8807410a81f740c")


def grade_sites(image):
    return opcode_sites(image, GRADE_CODE, 5, 0x1C, occurrences=2)


# --- The grade chart's axis reads "Noten/6" (bug fix) ---------------------------------------------------
# A2G-Patch's GradeChartLabel: the statistics' chart of the average marks per week (0x45ceb0, case 0x17)
# loads its axis label through 0x619c10 as text 5800 of RESDLL.dll, "Formpunkte/6", the form chart's.
# RESDLL.dll has no text for marks, so the patch assigns "Noten/6" from the exe, in the same 18 bytes; the
# call pushes the address behind it, which the add moves to the string in the 9 nops behind the function:
#     lea ecx,[esp+C] / push 16A8 / push ecx / call text / add esp,8
#     ->  call $+5 / add dword [esp],5C / lea ecx,[esp+10] / call CString::operator=(const char*)
# The next label (5801, "Woche") calls the same 0x619c10, whose first call is the assignment; both give
# the patch the targets in either state.
# fmt: off
GRADE_CHART_REST = (  # from the second label to the function's end, as in all three builds
    "8d54241068a916000052e8........83c404" "8d4424108bcc50e8........518d5424188bcc52e8........"
    "8b8efc050100e8........8d4c2410e8........8d4c240ce8........5f5e5b83c468c3"
)
GRADE_CHART_ORIGINAL = wild("8d4c240c68a816000051e8........83c408" + GRADE_CHART_REST + "90" * 9)
GRADE_CHART_PATCHED = wild("e800000000830424" "5c" "8d4c2410e8........" + GRADE_CHART_REST + b"Noten/6\0\x90".hex())
GRADE_CHART_LOADER = wild(  # 0x619c10: the text by its number into the CString, through CString::operator=
    "8b4c240881ec000200008d44240068000100005051e8........85c07518"
    "8b8c240402000068........e8........81c400020000c3"
)
# fmt: on
GRADE_CHART_TEXT_CALL, GRADE_CHART_ASSIGN_CALL, GRADE_CHART_NEXT_TEXT_CALL = 0x0A, 0x0D, 0x1C
GRADE_CHART_LOADER_ASSIGN_CALL = 0x2A


def grade_chart_sites(image):
    """[(offset, original, patched, is_patched)] of the label's 18 bytes and the string behind, or None. The
    call that changes reaches the text loader of the next label in the original, the loader's assignment
    patched."""
    site = rewrite_site(image, GRADE_CHART_ORIGINAL, GRADE_CHART_PATCHED)
    if site is None:
        return None
    at, original, patched, is_patched = site
    loader = call_target(image, at + GRADE_CHART_NEXT_TEXT_CALL)
    if loader < 0 or find_all(image[loader : loader + len(GRADE_CHART_LOADER)], GRADE_CHART_LOADER) != [0]:
        return None
    assign = call_target(image, loader + GRADE_CHART_LOADER_ASSIGN_CALL)
    original, patched = bytearray(original), bytearray(patched)
    call = GRADE_CHART_TEXT_CALL
    struct.pack_into("<i", original, call + 1, loader - (at + call + 5))
    call = GRADE_CHART_ASSIGN_CALL
    struct.pack_into("<i", patched, call + 1, assign - (at + call + 5))
    if image[at : at + len(original)] != (patched if is_patched else original):
        return None
    return [(at, bytes(original), bytes(patched), is_patched)]


# --- The club list of the most appearances takes new players after 50 (bug fix) ----------------------
# Generated from A2G-Patch's AppearancesList: a player's leaving clears his flag "at the club" in the goals
# list only, so once 50 players have appeared nobody new gets into the appearances list. Before each count
# (0x61ef70) a routine sets the flags of the appearances list anew from the squad and the players lent
# out; it goes in front of the list's sort, rewritten as a bubble sort (the same order) in 47 of its 139
# bytes. The two places lie 179 bytes apart in every build. A new player may also take the places from 21
# on instead of from 11.
# fmt: off
APPEARANCES_PLACES = (
    (  # the count's start: call the flags' routine
        wild("660fb6830401000083c408663d0200894424107e08c744241002000000"),
        wild("83c4080fb683040100003c027602b00289442410e89c00000090909090"),
    ),
    (  # the sort, the flags' routine in front
        wild("8d442434bd01000000894424106683fd328d55ff8bc57d260fbfcd8d0c898d748c3e0fbfca8d0c89668b4c8c3e663b0e"
             "7d028bd04083c614663d32007ce46685d27e330fbfc2b9050000008d7c24208d14808d4494348b5424108bf0f3a5b905"
             "0000008bf28bf8f3a5b9050000008d7424208bfaf3a58b5424104583c2148d45ff89542410663d31007c82"),
        wild("eb585657558d7424446a325d6683660800668b066685c074240fbf8be60000008dbb90090000e81c0000000fb68b190a"
             "00008dbb1c0a0000e80a00000083c6144d75c95d5f5ec3e3108b17663b027504c646080183c704e2f0c36a315a8d7424"
             "346a3159668b460a663b461e7d13516a05598b448efc87448e1089448efce2f25983c614e2de4a75d49090"),
    ),
    (  # a new player's first place: 11 -> 21
        wild("0fbfc88d0c8966837c8f0800740948663d0a007deb"),
        wild("0fbfc88d0c8966837c8f0800740948663d14007deb"),
    ),
)
# fmt: on


def appearances_sites(image):
    return rewrites_sites(image, APPEARANCES_PLACES)


# --- Fish poisoning: three weeks out, as the message says (balancing in A2G-Patch, a fix here) ---------
# Generated from A2G-Patch's FishPoisoning: the function at 0x633a60 enters the injury of the referee events, event 0
# the fish poisoning of text 732 ("fällt drei Wochen aus"), which the kinds' table gives 7 days. The patch
# gives event 0 21 days, whatever kind --events left in the table, in the function's bytes and 5 of the 10
# nops behind it.
# fmt: off
FISH_ORIGINAL = wild(
    "0fbf4424088b4c24048a1445........8851460fbf0445........8d0440660fb61445........6689514466a1......"
    "..66894142c39090909090"
)
FISH_PATCHED = wild(
    "0fbf4424088b4c24048a1445........88514685c00fbf0445........8d04400fb61445........7502b21566895144"
    "66a1........66894142c3"
)
# fmt: on


def fish_sites(image):
    return rewrite_sites(image, FISH_ORIGINAL, FISH_PATCHED)


# --- More events around the manager (balancing in A2G-Patch, a fix here) ---------------------------------
# Generated from A2G-Patch's ManagerEvents: the dispatcher of the manager's private life (0x55c900, 39
# cases) is built from the table of the other kind of events (0x6BD248, 14 pairs), so cases 15 to 39 never
# come; their own table lies 0x38 bytes behind it (39 pairs, referenced nowhere). The patch builds the
# dispatcher from it and passes the manager's name twice for case 32, whose text holds it twice.
# fmt: off
MANAGER_PLACES = (
    (  # the dispatcher's table
        wild("6aff68........6a0eb9........e8........c390909090909090909090909053565733f6b9........e8........8b"
             "d86685db0f8495000000668b15........33c06685d27e260fbfcb81c1606d0000"),
        wild("6affb8........83c038506a27b9........e8........c3909090909090909053565733f6b9........e8........8b"
             "d86685db0f8495000000668b15........33c06685d27e260fbfcb81c1606d0000"),
    ),
    (  # case 32: the name twice
        wild("8d480a515068........52e8........83c4108d4424048d8c24f8010000505651e8........8b94240c0400008b8c24"
             "0004000083c40c8d8424f8010000"),
        wild("8d480a515068........52e8........83c4108d4424045050568db4240402000056e8........8b9424100400008b8c"
             "240404000083c4108bc690909090"),
    ),
)
# fmt: on
# Six cases get code of their own: 13, 21, 35 and 39 have their texts but no code, 25 (an inheritance) builds
# its text but neither shows it nor books anything, 34 names "%s, der Sie eigentlich gar nicht leiden kann"
# with an empty string. A2G-Patch assembles the code (tools/manager_events.asm) into ManagerCode.cs, which
# src/a2managerbuild.py takes into src/a2manager.json. It goes into three functions of the game nothing
# refers to (the questions of 13, 21 and 35 behind the first, where the question dialog reaches them), and
# the switch's jump table leads there. The builds are known by the switch's address, its table and the import
# table entry of GetAsyncKeyState (GOG and the 2007 CD share the addresses, not the imports); taking the patch
# back puts the three functions' original bytes back.
MANAGER_CODE = os.path.join(HERE, "a2manager.json")
# movsx eax,word [esp+7F4] / dec eax / cmp eax,26 / ja return 1 / jmp [eax*4+table]
MANAGER_SWITCH = wild("0fbf8424f40700004883f8260f87........ff2485........")
MANAGER_TABLE_AT = 21
# The weights of cases 32 to 36 as A2G-Linux 0.2.0 (A2G-Patch 0.5.0) left them, case 34's set to 0, and as
# the game has them: the 4 goes back.
MANAGER_OLD_WEIGHTS = bytes.fromhex("1900200019002100000022000200230001002400")
MANAGER_WEIGHTS = bytes.fromhex("1900200019002100040022000200230001002400")
MANAGER_REGION_OF = (0, 0, 1, 2)  # the function each block goes into: MAIN and the questions into the first
MANAGER_QUESTION_SIZE = 0x2C  # an entry of the question table
MANAGER_FILL = 0xCC  # what the three functions hold where the code leaves room (int3)


def load_manager_code():
    """The code and the builds of src/a2manager.json."""
    with open(MANAGER_CODE) as f:
        return json.load(f)


def manager_link(code, build):
    """(the three functions with the code in place for build, where each case of code["cases"] now starts),
    as A2G-Patch's ManagerEvents.Link: MAIN at the first function's start, the questions behind it at the next
    place a whole number of question entries from the question table, KEYS and TABS at the other two, every
    field filled in with an address or a distance, the rest int3."""
    blocks = [bytes.fromhex(b) for b in code["blocks"]]
    regions = build["regions"]
    main_end = regions[0] + len(blocks[0])
    questions = main_end + (build["questions"] - main_end) % MANAGER_QUESTION_SIZE
    bases = [regions[0], questions, regions[1], regions[2]]
    first = (questions - build["questions"]) // MANAGER_QUESTION_SIZE
    values = bases + build["symbols"] + [first, first + 1, first + 2]
    out = [bytearray([MANAGER_FILL]) * (len(o) // 2) for o in build["originals"]]
    for b, data in enumerate(blocks):
        data = bytearray(data)
        for offset, relative, target, addend in code["fields"][b]:
            value = values[target] + addend
            if relative:
                value -= bases[b] + offset + 4
            struct.pack_into("<I", data, offset, value & 0xFFFFFFFF)
        region = MANAGER_REGION_OF[b]
        at = bases[b] - regions[region]
        out[region][at : at + len(data)] = data
    entries = [bases[block] + offset for block, offset in code["entries"]]
    return [bytes(o) for o in out], entries


def pe_imports(image, pe):
    """{name: address of its import address table entry} of the functions the exe imports by name, as A2G-Patch's
    PeFile.Imports; {} if the import directory can't be read."""
    imports = {}

    def at(rva):
        offset = pe.file_offset(pe.image_base + rva)
        if offset is None:
            raise ValueError(rva)
        return offset

    def u32(offset):
        return struct.unpack_from("<I", image, offset)[0]

    try:
        descriptor = at(u32(pe.optional + 104))
        while u32(descriptor + 12):
            lookup, table = at(u32(descriptor)), u32(descriptor + 16)
            i = 0
            while u32(lookup + 4 * i):
                entry = u32(lookup + 4 * i)
                if not entry & 0x80000000:  # not by ordinal
                    name = at(entry) + 2
                    imports[image[name : image.index(b"\0", name)].decode("latin-1")] = pe.image_base + table + 4 * i
                i += 1
            descriptor += 20
    except (ValueError, struct.error):
        return {}
    return imports


def manager_code_sites(image, pe, code, build):
    """The jump table's entries and the three functions for build, or None if one holds neither its original
    nor the code (A2G-Patch's ManagerEvents.CodeSites)."""
    regions, entries = manager_link(code, build)
    places = [
        (build["table"] + 4 * (case - 1), struct.pack("<I", old), struct.pack("<I", new))
        for case, old, new in zip(code["cases"], build["cases"], entries)
    ]
    places += [(va, bytes.fromhex(o), r) for va, o, r in zip(build["regions"], build["originals"], regions)]
    sites = []
    for va, original, patched in places:
        offset = pe.file_offset(va)
        now = None if offset is None else image[offset : offset + len(original)]
        if now not in (original, patched):
            return None
        sites.append((offset, original, patched, now == patched))
    return sites


def manager_sites(image, code=None):
    """[(offset, original, patched, is_patched)] of the two rewrites, the six entries of the jump table and the
    three functions of a known build, plus case 34's weight where A2G-Linux 0.2.0 set it to 0; or None."""
    places = [rewrite_site(image, original, patched) for original, patched in MANAGER_PLACES]
    switches = find_all(image, MANAGER_SWITCH)
    if None in places or image[:2] != b"MZ" or len(switches) != 1:
        return None
    pe = Pe(image)
    code = code or load_manager_code()
    at, table = pe.va_at(switches[0]), struct.unpack_from("<I", image, switches[0] + MANAGER_TABLE_AT)[0]
    keystate = pe_imports(image, pe).get("GetAsyncKeyState", 0)
    builds = [b for b in code["builds"].values() if (b["switch"], b["table"], b["keystate"]) == (at, table, keystate)]
    sites = manager_code_sites(image, pe, code, builds[0]) if builds else None
    if sites is None:
        return None
    sites = places + sites
    old = find_all(image, MANAGER_OLD_WEIGHTS)
    if len(old) == 1:
        sites.append((old[0], MANAGER_OLD_WEIGHTS, MANAGER_WEIGHTS, False))
    return sites


# --- The lawn care button without a bar under Wine (bug fix of A2G-Linux) ------------------------------
# The stadium's button "Rasen pflegen (%s)" (control 4446 of RESDLL.dll) gets its text from
# sprintf("%s\t%s", costs, state of the pitch) in two places (0x514330, 0x514e70 in the 1999 exe). The
# game's own static class draws it with DrawText without DT_EXPANDTABS: Windows leaves the tab out, Wine
# draws it as a bar ("(20.000 DM)|Optimal"). Both places push the game's own "%s\n%s" instead, so the
# state goes to a second line of the button, which is two lines high. The other 27 users of "%s\t%s" fill
# lists and controls that split their text at the tab into columns; they keep it.
# fmt: off
LAWN_PLACES = (
    # movzx dx,[ecx+89B] (state of the pitch) / push edx / push eax / call state text / mov ecx,[esp+18] /
    # add esp,8 / lea edx,[esp+40] / lea eax,[esp+108] / push ecx / push edx / push format / push eax /
    # call sprintf / add esp,10 / lea ecx,[esp+108] / lea edi,[ebx+1440] (the button)
    wild("660fb6919b0800005250e8........8b4c241883c4088d5424408d8424080100005152",
         "68........50e8........83c4108d8c24080100008dbb40140000"),
    # movzx ax,[edx+89B] / push eax / push ecx / call state text / mov edx,[esp+10] / add esp,8 /
    # lea eax,[esp+5A8] / lea ecx,[esp+738] / push edx / push eax / push format / push ecx / call sprintf /
    # add esp,10 / lea edi,[esi+1440] (the button)
    wild("660fb6829b0800005051e8........8b54241083c4088d8424a80500008d8c24380700005250",
         "68........51e8........83c4108dbe40140000"),
)
# fmt: on
LAWN_FORMAT_AT = (36, 39)  # the pushed address in each place
LAWN_TAB, LAWN_NEWLINE = b"\0%s\t%s\0", b"\0%s\n%s\0"


def lawn_sites(image):
    """[(offset, address of "%s\\t%s", address of "%s\\n%s", is_patched)] of the two pushes, or None."""
    if image[:2] != b"MZ":
        return None
    pe = Pe(image)
    strings = [find_all(image, s) for s in (LAWN_TAB, LAWN_NEWLINE)]
    if any(len(found) != 1 for found in strings):
        return None
    tab, newline = (pe.va_at(found[0] + 1) for found in strings)
    if tab is None or newline is None:
        return None
    original, patched = struct.pack("<I", tab), struct.pack("<I", newline)
    sites = []
    for pattern, at in zip(LAWN_PLACES, LAWN_FORMAT_AT):
        found = find_all(image, pattern)
        if len(found) != 1:
            return None
        current = image[found[0] + at : found[0] + at + 4]
        if current not in (original, patched):
            return None
        sites.append((found[0] + at, original, patched, current == patched))
    return sites


# --- Headers of a PE file, for the patches that add code -----------------------------------------
EXECUTE = 0x20000000  # IMAGE_SCN_MEM_EXECUTE
WRITABLE_CODE = 0xE0000020  # code, execute, read, write


def align_up(n, to):
    return (n + to - 1) // to * to


class Pe:
    """The headers of a 32-bit exe: image base, alignments and sections (name, vsize, va, rsize, raw, flags)."""

    def __init__(self, image):
        self.header = struct.unpack_from("<I", image, 0x3C)[0]
        self.optional = self.header + 24
        self.table = self.optional + struct.unpack_from("<H", image, self.header + 20)[0]
        self.image_base, self.section_alignment, self.file_alignment = struct.unpack_from(
            "<III", image, self.optional + 28
        )
        self.size_of_image = struct.unpack_from("<I", image, self.optional + 56)[0]
        count = struct.unpack_from("<H", image, self.header + 6)[0]
        self.sections = []
        for i in range(count):
            name, vsize, va, rsize, raw = struct.unpack_from("<8sIIII", image, self.table + 40 * i)
            flags = struct.unpack_from("<I", image, self.table + 40 * i + 36)[0]
            self.sections.append((name.rstrip(b"\0").decode("latin-1"), vsize, va, rsize, raw, flags))

    def va_at(self, offset):
        """The address the file offset is loaded at, or None outside every section."""
        for _, _, va, rsize, raw, _ in self.sections:
            if raw <= offset < raw + rsize:
                return self.image_base + va + offset - raw
        return None

    def file_offset(self, va):
        """Where the loaded address lies in the file, or None outside every section's data."""
        rva = va - self.image_base
        for _, vsize, sva, rsize, raw, _ in self.sections:
            if sva <= rva < sva + min(vsize, rsize):
                return raw + rva - sva
        return None

    def has_room_for_section(self):
        """Whether the section table has room for one more entry before the first section's data."""
        return self.table + 40 * (len(self.sections) + 1) <= min(s[4] for s in self.sections)


def add_section(image, name, data, characteristics=WRITABLE_CODE):
    """image with a section holding data (by default as writable code; characteristics are the section's
    flags), loaded right behind the image, as A2G-Patch's PeFile.AddSection does: the data goes behind
    everything in the file, and the 40 bytes the new header overwrites (GOG's run.exe has leftovers there)
    are kept right behind the data."""
    pe = Pe(image)
    raw = align_up(len(image), pe.file_alignment)
    raw_size = align_up(len(data) + 40, pe.file_alignment)
    result = bytearray(image) + bytes(raw + raw_size - len(image))
    result[raw : raw + len(data)] = data
    header = pe.table + 40 * len(pe.sections)
    result[raw + len(data) : raw + len(data) + 40] = image[header : header + 40]
    struct.pack_into(
        "<8sIIIIIIHHI",
        result,
        header,
        name.encode(),
        len(data),
        pe.size_of_image,
        raw_size,
        raw,
        0,
        0,
        0,
        0,
        characteristics,
    )
    struct.pack_into("<H", result, pe.header + 6, len(pe.sections) + 1)
    struct.pack_into("<I", result, pe.optional + 56, pe.size_of_image + align_up(len(data), pe.section_alignment))
    return result


def remove_last_section(image):
    """image without its last section, as before add_section (A2G-Patch's PeFile.RemoveLastSection): the file
    ends with the other sections' data or the signature behind it, and the 40 bytes kept behind the section's
    data go back to where its header was (zeros behind a section added by a2patch.py 0.1)."""
    pe = Pe(bytes(image))
    _, vsize, va, _, raw, _ = pe.sections[-1]
    others = pe.sections[:-1]
    cert_at, cert_size = struct.unpack_from("<II", image, pe.optional + 96 + 4 * 8)  # certificate table
    end = max(max(s[4] + s[3] for s in others), cert_at + cert_size)
    result = bytearray(image[:end])
    header = pe.table + 40 * len(others)
    result[header : header + 40] = (bytes(image[raw + vsize : raw + vsize + 40]) + bytes(40))[:40]
    struct.pack_into("<H", result, pe.header + 6, len(others))
    struct.pack_into("<I", result, pe.optional + 56, va)
    return result


# --- Interview answers take effect (balancing) ---------------------------------------------------
# The code of A2G-Trainer's InterviewEffectsFix byte for byte (as in A2G-Patch's InterviewEffects), for the
# addresses 0, the flag at +8 set; the trainer recognizes it by "A2GINT02" and switches it with the flag.
INTERVIEW_SECTION = ".a2int"
INTERVIEW_STUB_SIZE, INTERVIEW_APPLY_ENTRY, INTERVIEW_MORALE_ENTRY = 0x100, 0x20, 0xC0
INTERVIEW_ENGINE_BEFORE_CONTEXT, INTERVIEW_MONEY_FACTOR_BEHIND_CONTEXT = 0xC8, 0xC258
CUP_DRAW_HELPER_SIZE = 177  # A2G-Patch's cup draw helper goes at the end of the last executable section
# fmt: off
INTERVIEW_STUB = (
    b"A2GINT02\x01" + bytes(INTERVIEW_APPLY_ENTRY - 9)
    + bytes.fromhex(
        "803d0800000000746d"            # cmp byte [flag],0 / je zero
        "a10000000085c07464"            # mov eax,[engine] / test / je zero
        "8b801c01000085c0745a"          # mov eax,[eax+11C] (the copy) / test / je zero
        "8b48148b5018"                  # first pair: mov ecx,[eax+14] / mov edx,[eax+18]
        "83f90c750e"                    # cmp ecx,12 / jne morale
        "81e2ffffff0081ca00000040"      # and edx,FFFFFF / or edx,40000000 (marked fine)
        "eb07"                          # jmp store
        "83f90a7502b10c"                # morale: cmp ecx,10 / jne store / mov cl,12
        "890d14000000891518000000"      # store: mov [context+14],ecx / mov [context+18],edx
        "8b481c8b5020"                  # second pair, the same
        "83f90c750e"
        "81e2ffffff0081ca00000040"
        "eb07"
        "83f90a7502b10c"
        "890d1c000000891520000000"
        "eb1a"                          # jmp done
        "31c9"                          # zero: xor ecx,ecx
        "890d14000000890d18000000"      # mov [context+14..20],ecx
        "890d1c000000890d20000000"
        "b800000000ffe0"                # done: mov eax,apply / jmp eax
    )
    + bytes(INTERVIEW_MORALE_ENTRY - 0xB7)
    + bytes.fromhex(
        "807c240b407527"                # cmp byte [esp+B],40 (marked?) / jne morale
        "8b44240825ffffff00"            # mov eax,[esp+8] / and eax,FFFFFF (DM)
        "0faf0500000000"                # imul eax,[money factor]
        "99b964000000f7f9"              # cdq / mov ecx,100 / idiv ecx
        "8b54240485d27406"              # mov edx,[esp+4] (club) / test / je return
        "01828c030000"                  # add [edx+38C],eax (other costs)
        "c3"                            # return: ret
        "b800000000ffe0"                # morale: mov eax,morale / jmp eax
    )
    + bytes(INTERVIEW_STUB_SIZE - 0xF5)
)
# fmt: on
INTERVIEW_FLAG_REF, INTERVIEW_ENGINE_REF, INTERVIEW_APPLY_REF = 0x22, 0x2A, 0xB1
INTERVIEW_MONEY_FACTOR_REF, INTERVIEW_MORALE_REF = 0xD3, 0xEF
INTERVIEW_CONTEXT_REFS = (0x5E, 0x64, 0x8A, 0x90, 0x9A, 0xA0, 0xA6, 0xAC)
# mov ecx,[engine] / push eax / call (store the answer) / push context / call apply / mov eax,[context+10]
INTERVIEW_APPLY_CALL = [0x8B, 0x0D, None, None, None, None, 0x50, 0xE8, None, None, None, None]
INTERVIEW_APPLY_CALL += [0x68, None, None, None, None, 0xE8, None, None, None, None, 0xA1, None, None, None, None]
INTERVIEW_ENGINE_AT, INTERVIEW_CONTEXT_AT, INTERVIEW_CALL_AT, INTERVIEW_CONTEXT_FIELD_AT = 2, 13, 17, 23
# case 12: mov ecx,[esp+50] / mov edx,[esp+5C] / push ecx / push edx / call morale / add esp,8 / pop edi / pop esi /
# add esp,40 / ret
INTERVIEW_MORALE_CALL = [0x8B, 0x4C, 0x24, 0x50, 0x8B, 0x54, 0x24, 0x5C, 0x51, 0x52, 0xE8, None, None, None, None]
INTERVIEW_MORALE_CALL += [0x83, 0xC4, 0x08, 0x5F, 0x5E, 0x83, 0xC4, 0x40, 0xC3]
INTERVIEW_MORALE_CALL_AT = 10
INTERVIEW_APPLY_HEAD = bytes.fromhex("5355568b742410576 68b467450e8".replace(" ", ""))
INTERVIEW_MORALE_HEAD = bytes.fromhex("8b4c24048b442408660fb6919c00000003c2663dc800")


def interview_stub(stub, engine, context, apply, money_factor, morale):
    """INTERVIEW_STUB with its own address stub and the game's addresses added to their references."""
    code = bytearray(INTERVIEW_STUB)

    def add(at, value):
        struct.pack_into("<I", code, at, (struct.unpack_from("<I", code, at)[0] + value) & 0xFFFFFFFF)

    add(INTERVIEW_FLAG_REF, stub)
    add(INTERVIEW_ENGINE_REF, engine)
    for at in INTERVIEW_CONTEXT_REFS:
        add(at, context)
    add(INTERVIEW_APPLY_REF, apply)
    add(INTERVIEW_MONEY_FACTOR_REF, money_factor)
    add(INTERVIEW_MORALE_REF, morale)
    return bytes(code)


def interview_locate(image):
    """dict with the two calls, the game's addresses and the stub's file offset (None while off), or None."""
    u32 = lambda at: struct.unpack_from("<I", image, at)[0]  # noqa: E731
    applies = [
        at
        for at in find_all(image, INTERVIEW_APPLY_CALL)
        if u32(at + INTERVIEW_CONTEXT_FIELD_AT) == u32(at + INTERVIEW_CONTEXT_AT) + 0x10
    ]
    morales = find_all(image, INTERVIEW_MORALE_CALL)
    if len(applies) != 1 or len(morales) != 1:
        return None
    pe = Pe(image)
    p = {
        "pe": pe,
        "apply_call": applies[0] + INTERVIEW_CALL_AT,
        "morale_call": morales[0] + INTERVIEW_MORALE_CALL_AT,
        "engine": u32(applies[0] + INTERVIEW_ENGINE_AT),
        "context": u32(applies[0] + INTERVIEW_CONTEXT_AT),
        "stub": None,
    }
    apply_va, morale_va = pe.va_at(p["apply_call"]), pe.va_at(p["morale_call"])
    if p["engine"] != p["context"] - INTERVIEW_ENGINE_BEFORE_CONTEXT or apply_va is None or morale_va is None:
        return None

    def target(call, va):
        return (va + 5 + struct.unpack_from("<i", image, call + 1)[0]) & 0xFFFFFFFF

    def holds(va, head):
        at = pe.file_offset(va)
        return at is not None and image[at : at + len(head)] == head

    apply, morale = target(p["apply_call"], apply_va), target(p["morale_call"], morale_va)
    if holds(apply, INTERVIEW_APPLY_HEAD) and holds(morale, INTERVIEW_MORALE_HEAD):
        p["apply"], p["morale"] = apply, morale
        return p
    # On: both calls lead into one stub, which leads on to the two functions.
    stub = apply - INTERVIEW_APPLY_ENTRY
    at = pe.file_offset(stub)
    if morale != stub + INTERVIEW_MORALE_ENTRY or at is None:
        return None
    found = bytes(image[at : at + INTERVIEW_STUB_SIZE])
    if len(found) != INTERVIEW_STUB_SIZE:
        return None
    p["apply"] = struct.unpack_from("<I", found, INTERVIEW_APPLY_REF)[0]
    p["morale"] = struct.unpack_from("<I", found, INTERVIEW_MORALE_REF)[0]
    money_factor = p["context"] + INTERVIEW_MONEY_FACTOR_BEHIND_CONTEXT
    expected = interview_stub(stub, p["engine"], p["context"], p["apply"], money_factor, p["morale"])
    if (
        found != expected
        or not holds(p["apply"], INTERVIEW_APPLY_HEAD)
        or not holds(p["morale"], INTERVIEW_MORALE_HEAD)
    ):
        return None
    p["stub"] = at
    return p


def interview_room(image, pe):
    """Where the stub goes: right in front of the place of A2G-Patch's cup draw helper at the end of the last
    executable section (apart from added ones) if that is zero, else -1 for a section of its own, None if
    no section header fits. Unlike A2G-Patch, a section is also possible when .a2v101 is the last one
    (the unpacked 2007 run.exe has no room and gets 1.01 first): apply_interviews then puts it in front."""
    own = (V101_SECTION.rstrip(b"\0").decode(), INTERVIEW_SECTION)
    executable = [s for s in pe.sections if s[5] & EXECUTE and s[0] not in own]
    if executable:
        _, _, _, rsize, raw, _ = executable[-1]
        at = ((raw + rsize - CUP_DRAW_HELPER_SIZE) & ~15) - INTERVIEW_STUB_SIZE
        if at >= raw and not any(image[at : at + INTERVIEW_STUB_SIZE]):
            return at
    return -1 if pe.has_room_for_section() else None


def interview_state(image):
    """ "patched", "original" or None (unknown exe or no room)."""
    p = interview_locate(image)
    if p is None:
        return None
    if p["stub"] is not None:
        return "patched"
    return "original" if interview_room(image, p["pe"]) is not None else None


def apply_interviews(image):
    """image with the stub added and the two calls sent there. If the stub needs a section of its own and
    1.01's section is the last one, 1.01 is taken out and added again behind the stub's section: A2G-Patch
    recognizes 1.01 only as the last section."""
    pe = Pe(bytes(image))
    if interview_room(bytes(image), pe) == -1 and pe.sections[-1][0] == V101_SECTION_NAME:
        return apply_v101(apply_interviews(remove_v101(image)))
    p = interview_locate(bytes(image))
    pe = p["pe"]
    at = interview_room(bytes(image), pe)
    stub = pe.va_at(at) if at >= 0 else pe.image_base + pe.size_of_image
    money_factor = p["context"] + INTERVIEW_MONEY_FACTOR_BEHIND_CONTEXT
    code = interview_stub(stub, p["engine"], p["context"], p["apply"], money_factor, p["morale"])
    if at >= 0:
        image[at : at + len(code)] = code
    else:
        image = add_section(bytes(image), INTERVIEW_SECTION, code)
    for call, entry in ((p["apply_call"], INTERVIEW_APPLY_ENTRY), (p["morale_call"], INTERVIEW_MORALE_ENTRY)):
        struct.pack_into("<i", image, call + 1, stub + entry - (pe.va_at(call) + 5))
    return image


# --- CD checks of the 2007 release (GOG, 2007 CD) -------------------------------------
DISC_CHECKS = 11
ADD_ESP_4 = bytes([0x83, 0xC4, 0x04])
MOV_FROM_EAX = {0xF0: 6, 0xD8: 3, 0xF8: 7}  # ModR/M of "mov esi|ebx|edi, eax" -> register number


def disc_check_sites(image):
    """The 11 checks after calls of the signature routine, or None if the exe doesn't match."""
    found = {}
    for m in re.finditer(re.compile(b"\xe8(....)(?:\x8b([\xf0\xd8\xf8]))?\x83\xc4\x04", re.DOTALL), image):
        target = m.start() + 5 + struct.unpack("<i", m.group(1))[0]
        after = m.end()
        modrm = m.group(2)
        if modrm:  # mov r32,eax: 6 bytes "sub r32, imm32" follow
            register, length = MOV_FROM_EAX[modrm[0]], 6
        else:  # eax itself: 5 bytes "sub eax, imm32" follow
            register, length = 0, 5
        current = image[after : after + length]
        patched = bytes([0x31, 0xC0 + register * 9]) + bytes([NOP] * (length - 2))  # xor r32,r32
        # sub r32,imm32 (2007 CD) or the NOPs GOG put there
        sub = bytes([0x81, 0xE8 + register]) if modrm else bytes([0x2D])
        if current in (bytes([NOP] * length), patched) or current.startswith(sub):
            found.setdefault(target, []).append((after, current, patched, current == patched))
    sites = [v for v in found.values() if len(v) == DISC_CHECKS]
    return sites[0] if len(sites) == 1 else None


# --- Patch 1.01 for run.exe (GOG, 2007 CD) ---------------------------------------------
V101_SECTION = b".a2v101\0"
V101_SECTION_NAME = V101_SECTION.rstrip(b"\0").decode()
V101_PREBUILT = os.path.join(HERE, "a2v101.json")  # src/a2v101.S assembled by src/a2v101build.py
JMP_REL32 = 0xE9
# (address in run.exe, original bytes, symbol in a2v101.S or None for an in-place change, new bytes)
# fmt: off
V101_HOOKS = [
    (0x412DD0, "81ecf8090000", "fix_412dd0", None),             # sub esp,0x9f8 (whole function)
    (0x415F96, "74338a4e04", "fix_415f96", None),               # je / mov cl,[esi+4]
    (0x4160BD, "74328a066a01", "fix_4160bd", None),             # je / mov al,[esi] / push 1
    (0x501DCF, "7454", None, "eb54"),                           # je -> jmp: message 0xa41 is gone
    (0x557E3F, "808eae00000001", "fix_557e3f", None),           # or byte ptr [esi+0xae],1
    (0x557E64, "668b4e6083c4146601 4e5e", None, "83c41466ff465e90909090"),  # +=[esi+0x60] -> inc
    (0x568CA0, "83ec085355", "fix_568ca0", None),               # whole function
    (0x5A0BF7, "6a008d8c2478030000", "fix_5a0bf7", None),       # push 0 / lea ecx,[esp+0x378]
    (0x5A0F95, "e816d00c00", "fix_5a0f95", None),               # call 0x66dfb0 (DoModal)
    (0x5A2836, "33c98a4e208a91585a6c00885621", "fix_5a2836", None),  # alternative position
    (0x5A2FC0, "568b742408", "fix_5a2fc0", None),               # whole function
    (0x5BD540, "b86c9f0000", "fix_5bd540", None),               # mov eax,0x9f6c (wrapped)
    (0x468A4E, "688c097000", None, "6870097000"),               # movelist.dat: CD path -> game folder
]
# fmt: on


def pe_layout(image):
    """(PE header, section count, optional header, section table, [(name, vsize, rva, rsize, raw)])."""
    pe = struct.unpack_from("<I", image, 0x3C)[0]
    nsec = struct.unpack_from("<H", image, pe + 6)[0]
    opt = pe + 24
    table = opt + struct.unpack_from("<H", image, pe + 20)[0]
    sections = [struct.unpack_from("<8sIIII", image, table + 40 * i) for i in range(nsec)]
    return pe, nsec, opt, table, sections


def va_offset(sections, va):
    """File offset of the virtual address va, or None if no section holds it in the file."""
    rva = va - 0x400000
    for _, vsize, vaddr, rsize, raw in sections:
        if vaddr <= rva < vaddr + min(vsize, rsize):
            return raw + rva - vaddr
    return None


def load_v101(address):
    """(code, {symbol: address}) of the prebuilt src/a2v101.json, moved to address."""
    with open(V101_PREBUILT) as f:
        return relocate(json.load(f), address)


def v101_state(image):
    """ "patched", "original" or None (unknown exe)."""
    _, _, _, _, sections = pe_layout(image)
    if any(name == V101_SECTION for name, *_ in sections):
        return "patched"
    for va, original, _, _ in V101_HOOKS:
        at = va_offset(sections, va)
        want = bytes.fromhex(original.replace(" ", ""))
        if at is None or image[at : at + len(want)] != want:
            return None
    return "original"


def apply_v101(image):
    """image with the section added as A2G-Patch adds it (add_section) and the places redirected to it. In
    GOG's run.exe the code lands at 0xcbd000 as in A2G-Patch's Patch101, so both give the same bytes."""
    pe = Pe(bytes(image))
    if not pe.has_room_for_section():
        sys.exit("no room for another section header")
    sections = pe_layout(bytes(image))[4]
    code, symbols = load_v101(pe.image_base + pe.size_of_image)
    image = add_section(bytes(image), V101_SECTION_NAME, code)
    for hook_va, original, symbol, new in V101_HOOKS:
        at = va_offset(sections, hook_va)
        length = len(bytes.fromhex(original.replace(" ", "")))
        if symbol:
            rel = symbols[symbol] - (hook_va + 5)
            patch = bytes([JMP_REL32]) + struct.pack("<i", rel) + bytes([NOP] * (length - 5))
        else:
            patch = bytes.fromhex(new)
        if len(patch) != length:
            sys.exit(f"1.01: patch at {hook_va:#x} has {len(patch)} bytes instead of {length}")
        image[at : at + length] = patch
    return image


def remove_v101(image):
    """image without the 1.01 section (the last one) and with the places restored, as A2G-Patch's
    Patch101.RemoveProgram does."""
    sections = pe_layout(bytes(image))[4]
    for va, original, _, _ in V101_HOOKS:
        want = bytes.fromhex(original.replace(" ", ""))
        at = va_offset(sections, va)
        image[at : at + len(want)] = want
    return remove_last_section(image)


# --- Integrity values of run.exe (GOG, 2007 CD) -------------------------------------------
# Code self-checks: a stub "sub esp,0xc0 / push ebx,ebp,esi,edi / mov ebp,esp" right after a
# descriptor {CRC, ?, length}; the checked code starts at the stub.
SELF_CHECK_STUB = bytes.fromhex("81ecc0000000535556578bec")
SELF_CHECKS = 5
FILE_CRC_AT = 0x7C


def crc32_raw(data):
    """CRC32 without the final inversion, as the game computes it (start value 0xffffffff)."""
    import zlib

    return zlib.crc32(data) ^ 0xFFFFFFFF


def integrity_sites(image):
    """File offsets of the code self-check descriptors, or None if this is not run.exe of 2007 (GOG, CD)."""
    _, _, _, _, sections = pe_layout(image)
    text = sections[0]
    code = image[text[4] : text[4] + min(0x2B0000, text[3])]
    found = [m.start() + text[4] - 0xC for m in re.finditer(re.escape(SELF_CHECK_STUB), code)]
    return found if len(found) == SELF_CHECKS else None


def fix_integrity(image):
    """Stores the CRC values the integrity checks of run.exe expect; returns the image."""
    for desc in integrity_sites(bytes(image)):
        length = struct.unpack_from("<I", image, desc + 8)[0]
        struct.pack_into("<I", image, desc, crc32_raw(bytes(image[desc + 0xC : desc + 0xC + length])))
    import zlib

    struct.pack_into("<I", image, FILE_CRC_AT, zlib.crc32(bytes(image[0x80:])))  # must come last
    return image


PATCHES = {
    "sound": ("default sound device", sound_sites),
    "goals": ("goal limits lifted", goal_sites),
    "arrows": ("arrow buttons repeat while held", arrow_sites),
    "video": ("undecodable videos skipped", video_sites),
    "freeze": ("no freeze after 24.9 days of uptime", freeze_sites),
    "disk": ("no false disk space warning", disk_sites),
    "squad": ("squad limited to 30 players", squad_sites),
    "investments": ("investment growth kept off the bank balance", invest_sites),
    "money": ("club ledger stops at 2 billion DM", money_sites),
    "events": ("random events take the effect their message gives them", event_sites),
    "crashes": ("no crash on events without a fitting player", crash_sites),
    "referee": ("a referee's grudge hits the right club in the match's scenes", referee_sites),
    "competence": ("trainers and managers in weak countries improve yearly", competence_sites),
    "grades": ("appearances without a mark kept out of the average", grade_sites),
    "grade_chart": ("grade chart labelled Noten/6", grade_chart_sites),
    "appearances": ("club list of the most appearances takes new players after 50", appearances_sites),
    "negotiation": ("negotiation lock wears off monthly", negotiation_sites),
    "speeches": ("unfitting speeches weaken the team", speech_sites),
    "coaches": ("former players become trainers from 33, others with competence 3 to 11", coach_sites),
    "fish": ("fish poisoning keeps a player out for three weeks", fish_sites),
    "manager": ("all events around the manager's private life", manager_sites),
    "lawn": ("lawn care button without a bar under Wine", lawn_sites),
    "disc_check": ("CD checks of the 2007 release pass", disc_check_sites),
}
# Patches that add code to the file, in the order they are applied (1.01's section stays last where possible).
FILE_PATCHES = {
    "interviews": ("interview answers take effect", interview_state, apply_interviews),
    "v101": ("program changes of 1.01", v101_state, apply_v101),
}
# the bug fixes, applied on every install
FIXES = (
    "sound",
    "arrows",
    "video",
    "freeze",
    "disk",
    "squad",
    "investments",
    "money",
    "events",
    "crashes",
    "referee",
    "competence",
    "grades",
    "grade_chart",
    "appearances",
    "fish",
    "manager",
    "lawn",
)
# balancing patches the installer applies on every install as well, behind --fixes
ALWAYS = ("interviews",)
# the balancing patches, in the order the installer asks for them (A2G-Patch's order)
BALANCING = ("negotiation", "goals", "speeches", "coaches")


def main():
    """Applies the selected patches to the exe, all or none: if one does not fit, nothing is written. Keeps
    the first original as backup, stores the integrity values of run.exe of 2007 and replaces the file
    through a temporary one."""
    ap = argparse.ArgumentParser(description="Patches anstoss2.exe or run.exe (ports from A2G-Patch).")
    ap.add_argument("--sound", action="store_true", help="play sound on the default audio device")
    ap.add_argument("--arrows", action="store_true", help="arrow buttons keep counting while held down")
    ap.add_argument("--video", action="store_true", help="skip videos that can't be decoded instead of crashing")
    ap.add_argument("--freeze", action="store_true", help="no freeze after 24.9 days of uptime")
    ap.add_argument("--disk", action="store_true", help="no false 'disk almost full' warning when saving")
    ap.add_argument("--squad", action="store_true", help="squads never grow past 30 players")
    ap.add_argument("--investments", action="store_true", help="growth of investments not taken off the balance")
    ap.add_argument("--money", action="store_true", help="the club's ledger stops at 2 billion DM")
    ap.add_argument("--events", action="store_true", help="random events take the effect their message gives them")
    ap.add_argument("--crashes", action="store_true", help="no crash on events without a fitting player")
    ap.add_argument("--referee", action="store_true", help="a referee's grudge hits the right club")
    ap.add_argument("--competence", action="store_true", help="trainers in weak countries improve yearly")
    ap.add_argument("--grades", action="store_true", help="appearances without a mark kept out of the average")
    ap.add_argument("--grade-chart", action="store_true", help="the grade chart's axis reads Noten/6")
    ap.add_argument("--appearances", action="store_true", help="the most appearances list takes new players")
    ap.add_argument("--fish", action="store_true", help="fish poisoning keeps a player out 3 weeks")
    ap.add_argument("--manager", action="store_true", help="all events around the manager")
    ap.add_argument("--lawn", action="store_true", help="lawn care button without a bar under Wine")
    ap.add_argument("--fixes", action="store_true", help="all bug fixes: " + " ".join("--" + k for k in FIXES))
    ap.add_argument("--interviews", action="store_true", help="interview answers take effect (always applied)")
    ap.add_argument("--negotiation", action="store_true", help="balancing: negotiation lock wears off monthly")
    ap.add_argument("--goals", action="store_true", help="balancing: lift the goal limits")
    ap.add_argument("--speeches", action="store_true", help="balancing: unfitting speeches weaken the team")
    ap.add_argument("--coaches", action="store_true", help="balancing: better newcomers in the trainer pool")
    ap.add_argument("--disc-check", action="store_true", help="run.exe of 2007 (GOG, CD): let the CD checks pass")
    ap.add_argument("--v101", action="store_true", help="run.exe of 2007 (GOG, CD): program changes of patch 1.01")
    ap.add_argument("exe")
    a = ap.parse_args()
    if a.fixes:
        for key in FIXES:
            setattr(a, key, True)
    wanted = [k for k in PATCHES if getattr(a, k)]
    wanted_files = [k for k in FILE_PATCHES if getattr(a, k)]
    if not wanted and not wanted_files:
        ap.error("no patch selected")

    image = bytearray(open(a.exe, "rb").read())
    changes = []
    for key in wanted:
        name, find = PATCHES[key]
        sites = find(bytes(image))
        if sites is None:
            sys.exit(f"{a.exe}: unknown version, patch '{name}' does not fit. Nothing was changed.")
        if all(s[3] for s in sites):
            print(f"{a.exe}: {name}: already patched")
        else:
            changes += sites
            print(f"{a.exe}: {name}: patched")
    to_apply = []
    for key in wanted_files:
        name, state_of, apply = FILE_PATCHES[key]
        state = state_of(bytes(image))
        if state is None:
            sys.exit(f"{a.exe}: unknown version, patch '{name}' does not fit. Nothing was changed.")
        if state == "patched":
            print(f"{a.exe}: {name}: already patched")
        else:
            to_apply.append(apply)
            print(f"{a.exe}: {name}: patched")
    gog = disc_check_sites(bytes(image)) is not None and integrity_sites(bytes(image)) is not None
    if not changes and not to_apply and not (gog and bytes(fix_integrity(bytearray(image))) != bytes(image)):
        return
    if not os.path.exists(a.exe + BACKUP_SUFFIX):
        shutil.copy2(a.exe, a.exe + BACKUP_SUFFIX)
    for offset, _, patched, _ in changes:
        image[offset : offset + len(patched)] = patched
    for apply in to_apply:
        image = apply(image)
    if gog:
        image = fix_integrity(image)
        print(f"{a.exe}: integrity values updated")
    tmp = a.exe + ".tmp"
    with open(tmp, "wb") as f:
        f.write(image)
    shutil.copymode(a.exe, tmp)
    os.replace(tmp, a.exe)
    print(f"Backup of the original: {os.path.basename(a.exe) + BACKUP_SUFFIX}")


if __name__ == "__main__":
    main()

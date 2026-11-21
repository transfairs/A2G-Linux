#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Changes names and terms in the texts of Anstoss 2 Gold: RESDLL.dll, the event texts and the tips.

    a2texts.py [--euro] [--centre-back] [--cups] [--leagues] [--groups] [--contracts] [--typos] [--off]
               <game folder>

A port of A2G-Patch's text switches (GameTexts.cs, TextPatches.cs), with the same texts, the same order
and the same bytes, so A2G-Patch recognizes the result and can take it back. They need no code of the exe
and work the same for every release (1999 CD, GOG, 2007 CD):

--euro         "Euro statt DM": the three money formats every amount the game shows goes through, the
               amounts in 79 dialogs, a sentence with "Mark", four event texts and the tips. The numbers
               stay: 1 DM shows as 1 €. "DM" alone, the defensive midfielder, stays.
--centre-back  "Innenverteidiger": centre-back (IV) instead of man-marker (MD), in the strings, dialogs
               and the message about a player's new main position.
--cups         "Europapokale": UEFA-Cup, Cup der Pokalsieger, Weltcup and ECL-Cup instead of UEFA-Pokal,
               Pokal der Pokalsieger, Weltpokal and UI-Cup.
--leagues      "Liganamen": the leagues' names of today (1. and 2. Bundesliga, Regionalliga West,
               Championship, League One, Ligue 1 and 2).
--groups       "Gruppen A bis H": the groups of the cups and championships by letter instead of 1 to 8.
--contracts    "Vertragsbegriffe": Grundgehalt, Ausstiegsklausel and Rekordtransfers instead of
               Festgehalt, Freigabeklausel or fixed transfer fee, and Supertransfers.
--typos        "Tippfehler" (a bug fix, one of the game's bugs in A2G-Patch): punctuation and typing errors,
               e.g. "rechter Verteidiger.." in the message about a new main position, a doubled "mehr",
               "das" for "daß", "UEFA - Pokals" and the cut heading "Europäischer Superc.".
--off          takes the named switches back instead.

In the strings, dialogs and tips a text is replaced as a whole word ("Gruppe 1" leaves "Gruppe 10" alone);
event texts are replaced whole, and each switch keeps the length of the event file, which the game reads
only at its length to the byte. A longer text doesn't fit into RESDLL.dll in place: the string table blocks
and dialogs the switches change go into a section ".a2gtxt" at the end of the file, built anew from the
original for the switches that are on, and the resource directory points there. With none on, the files
are the originals to the byte again; no backups are written.

A switch is applied only if every string and dialog it changes holds the game's text; otherwise (a
RESDLL.dll that isn't the game's, e.g. from a data set) it is left out with a message, and the exit status
stays 0, so the installer goes on. Exit status 1 if the game folder has no RESDLL.dll.
"""

import argparse
import os
import struct
import sys
import unicodedata
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from a2import import match  # noqa: E402
from a2patch import Pe, add_section, remove_last_section  # noqa: E402

RESOURCE_FILE = "RESDLL.dll"
TIPS_FILE = "TEXTE/tips.txt"
# the event files the releases read: the 1999 exe EreigGld.saq, GOG's and the 2007 CD's EreigGold.saq
EVENT_FILES = ("TEXTE/EreigGld.saq", "TEXTE/EreigGold.saq")
SECTION = ".a2gtxt"
MARKER = b"A2GPatchTexts\0"
STRING_TYPE, DIALOG_TYPE = 6, 5
READ_ONLY_DATA = 0x40000040  # IMAGE_SCN_CNT_INITIALIZED_DATA | MEM_READ

STRING, DIALOG, EVENT, TIPS = "string", "dialog", "event", "tips"


# --- changes ----------------------------------------------------------------------------------------------

Change = namedtuple("Change", "source frm to ids")


def strings(frm, to, *ids):
    """frm becomes to in the strings ids of RESDLL.dll."""
    return Change(STRING, frm, to, ids)


def dialogs(frm, to, *ids):
    """frm becomes to in the dialogs ids of RESDLL.dll (caption and controls)."""
    return Change(DIALOG, frm, to, ids)


def event(number, frm, to):
    """The event text number, frm, replaced whole by to."""
    return Change(EVENT, frm, to, (number,))


def tips(frm, to):
    """frm becomes to in the tips."""
    return Change(TIPS, frm, to, ())


def word_char(c):
    """Whether c is a letter or a digit (.NET's char.IsLetterOrDigit)."""
    category = unicodedata.category(c)
    return category[0] == "L" or category == "Nd"


def positions(text, word):
    """Where whole-word word starts in text, not overlapping."""
    at = text.find(word)
    while at >= 0:
        end = at + len(word)
        if (not word_char(word[0]) or at == 0 or not word_char(text[at - 1])) and (
            not word_char(word[-1]) or end == len(text) or not word_char(text[end])
        ):
            yield at
            at = end - 1
        at = text.find(word, at + 1)


def replace(text, frm, to):
    """text with every whole-word frm replaced by to."""
    out, done = [], 0
    for at in positions(text, frm):
        out += [text[done:at], to]
        done = at + len(frm)
    return "".join(out) + text[done:]


def apply(change, text, on):
    """text changed (on) or changed back."""
    frm, to = (change.frm, change.to) if on else (change.to, change.frm)
    if change.source == EVENT:
        return to if text == frm else text
    return replace(text, frm, to)


def is_in(change, text, on):
    """Whether text holds the text as the game has it (on False) or as changed."""
    wanted = change.to if on else change.frm
    if change.source == EVENT:
        return text == wanted
    return next(positions(text, wanted), None) is not None


# --- the switches (A2G-Patch's TextPatches.cs) -------------------------------------------------------------

Patch = namedtuple("Patch", "key option title changes")

# fmt: off
PATCHES = (
    Patch("Currency", "euro", "Euro statt DM", (
        strings(" DM", " €", 2162, 2163, 2164),
        strings("eine weitere Mark", "einen weiteren Euro", 1764),
        dialogs(" DM", " €", 116, 131, 132, 136, 193, 198, 199, 207, 208, 209, 210, 212, 213, 214, 215, 216, 217, 220,
                234, 236, 237, 238, 239, 241, 242, 243, 244, 245, 248, 259, 263, 265, 270, 271, 276, 279, 281, 283, 286,
                293, 294, 299, 311, 337, 376, 377, 378, 389, 403, 434, 440, 452, 474, 482, 492, 510, 513, 516, 522, 528,
                533, 546, 547, 549, 559, 570, 577, 578, 581, 582, 583, 588, 589, 593, 595, 605, 612, 620, 628),
        event(229,
              "Ein Wettbüro bietet Ihrem Verein %s DM für eine Niederlage im nächsten Spiel gegen %s.",
              "Ein Wettbüro bietet Ihrem Verein %s € für eine Niederlage im nächsten Spiel gegen %s. "),
        event(258,
              "Ein Medizinmann aus Afrika bietet Ihnen gegen eine einmalige Gebühr von 300.000 DM an, alle Formwerte "
              "Ihrer Mannschaft um fünf Punkte zu erhöhen. Nehmen Sie an?",
              "Ein Medizinmann aus Afrika bietet Ihnen gegen eine einmalige Gebühr von 300.000 € an, alle Formwerte "
              "Ihrer Mannschaft um fünf Punkte zu erhöhen. Nehmen Sie an? "),
        event(286,
              "Die Existenz Ihrer schwarzen Kasse ist leider den Finanzbehörden zu Ohren gekommen. Sie werden zu einer "
              "Strafe von 200.000 DM verdonnert. Außerdem muß das Geld sofort versteuert werden, so daß weitere %s "
              "abgeführt werden müssen. Der Rest wandert direkt auf das Vereinskonto.",
              "Die Existenz Ihrer schwarzen Kasse ist leider den Finanzbehörden zu Ohren gekommen. Sie werden zu einer "
              "Strafe von 200.000 € verdonnert. Außerdem muß das Geld sofort versteuert werden, so daß weitere %s "
              "abgeführt werden müssen. Der Rest wandert direkt auf das Vereinskonto. "),
        event(330,
              "Ihr Spieler %s fordert eine Sonderprämie in Höhe von 100.000 DM, da er ein lukratives Auslandsangebot "
              "vorliegen habe. Sind Sie einverstanden?",
              "Ihr Spieler %s fordert eine Sonderprämie in Höhe von 100.000 €, da er ein lukratives Auslandsangebot "
              "vorliegen habe. Sind Sie einverstanden? "),
        event(501,
              "Weil Sie unbedingt noch die Anstoß 2-Partie vom Abend zuvor fertig spielen mußten, erscheinen Sie zu "
              "spät zum Training und müssen 1.000 Mark in die Mannschaftskasse zahlen.",
              "Weil Sie unbedingt noch die Anstoß 2-Partie vom Abend zuvor fertig spielen mußten, erscheinen Sie zu "
              "spät zum Training und müssen 1.000 € in die Mannschaftskasse zahlen.   "),
        tips(" DM", " €"),
    )),
    Patch("CentreBack", "centre_back", "Innenverteidiger", (
        strings("MD", "IV", 1144),
        strings("Manndecker", "Innenverteidiger", 1174, 1370),
        dialogs("MD", "IV", 200, 396, 609),
        dialogs("Manndecker", "Innenverteidiger", 291),
        event(906,
              "Ihr Spieler %s hat eine neue Hauptposition gelernt, er ist nun %s.",
              "Ihr Spieler %s hat eine neue Hauptposition gelernt: %s.     "),
        event(909, "Manndecker", "Innenverteidiger"),
    )),
    Patch("CupNames", "cups", "Europapokale", (
        strings("Pokal der Pokalsieger", "Cup der Pokalsieger", 1556, 1561, 1869, 2032, 2488, 2497, 2500, 2503, 5390,
                5648),
        strings("Pokals der Pokalsieger", "Cups der Pokalsieger", 2643),
        dialogs("Pokal der Pokalsieger", "Cup der Pokalsieger", 509, 626),
        dialogs("Europapokal der Pokalsieger", "Cup der Pokalsieger", 274),
        strings("UEFA-Pokal", "UEFA-Cup", 1557, 1562, 1870, 2033, 2489, 2498, 2501, 2504, 5391, 5649, 5761, 6282),
        strings("UEFA-Pokalplatz", "UEFA-Cup-Platz", 1077),
        strings("UEFA - Pokals", "UEFA-Cups", 2642),
        dialogs("UEFA-Pokal", "UEFA-Cup", 241, 270, 271, 281, 626, 629),
        strings("Weltpokal", "Weltcup", 2490, 5653, 5763, 5970),
        dialogs("Weltpokal", "Weltcup", 626),
        strings("UI-Cup", "ECL-Cup", 1558, 1879, 2034, 2492, 5393, 5655, 6352),
        strings("UIC", "ECL", 5972),
        dialogs("UI-Cup", "ECL-Cup", 274),
        dialogs("UIC", "ECL", 274),
    )),
    Patch("LeagueNames", "leagues", "Liganamen", (
        strings("Bundesliga", "1. Bundesliga", 1019),
        strings("2. Liga", "2. Bundesliga", 1020),
        strings("2. Liga", "2. B.liga", 5584),
        strings("Regionalliga West/Südwest", "Regionalliga West", 1024),
        strings("RL W./SW..", "RL West", 5588),
        dialogs("Regionalliga West-Südwest", "Regionalliga West", 275),
        dialogs("West-Südwest", "West", 189),
        strings("Division One", "Championship", 1026),
        strings("Division Two", "League One", 1027),
        strings("Division 1", "Champions.", 5590),
        strings("Division 2", "League One", 5591),
        strings("Division 1", "Ligue 1", 1028, 5592),
        strings("Division 2", "Ligue 2", 1029, 5593),
        strings("1a Division", "Primera D.", 5595),
    )),
    Patch("GroupLetters", "groups", "Gruppen A bis H", (
        strings("Gruppe 1", "Gruppe A", 6032),
        strings("Gruppe 2", "Gruppe B", 6033),
        strings("Gruppe 3", "Gruppe C", 6034),
        strings("Gruppe 4", "Gruppe D", 6035),
        strings("Gruppe 5", "Gruppe E", 6036),
        strings("Gruppe 6", "Gruppe F", 6037),
        strings("Gruppe 7", "Gruppe G", 6038),
        strings("Gruppe 8", "Gruppe H", 6039),
        strings("Gruppen 1/2", "Gruppen A/B", 2132),
        strings("Gruppen 3/4", "Gruppen C/D", 2133),
        strings("Gruppen 5/6", "Gruppen E/F", 2134),
        strings("Gruppen 7/8", "Gruppen G/H", 6052),
    )),
    Patch("ContractTerms", "contracts", "Vertragsbegriffe", (
        strings("Festgehalt", "Grundgehalt", 2658),
        dialogs("Festgehalt", "Grundgehalt", 209, 210, 279, 293, 294, 311, 389, 490, 612),
        dialogs("Freigabeklausel", "Ausstiegsklausel", 221, 401, 402),
        dialogs("Fixe Ablöse vereinbart", "Ausstiegsklausel", 293, 294, 311),
        strings("Fixe Ablöse", "Ausstiegsklausel", 2410),
        dialogs("Fixe Ablöse", "Ausstiegsklausel", 200, 568),
        strings("Ausstieg bei Angebot möglich", "Ausstiegsklausel", 2664),
        dialogs("Ausstieg bei Angebot möglich", "Ausstiegsklausel", 279),
        dialogs("Ausstieg bei Angebot", "Ausstiegsklausel", 210),
        strings("Supertransfers", "Rekordtransfers", 2153),
    )),
    # one of the game's bugs in A2G-Patch; its changes come last (they share "UEFA - Pokals" with CupNames)
    Patch("TextTypos", "typos", "Tippfehler", (
        strings(", und er ist", "und er ist", 1201),
        strings("harter Spieler.", "harter Spieler", 1333),
        strings("Spiele gewonnen", "Spiele gewonnen.", 1120),
        strings("sehr zufrieden", "sehr zufrieden.", 1750, 1751),
        strings("Meinung, das es", "Meinung, daß es", 1754),
        strings("des Nationalen Pokals", "des nationalen Pokals", 2641),
        strings("UEFA - Pokals", "UEFA-Pokals", 2642),
        strings("Europäischer Superc.", "Europ. Supercup", 2035),
        strings("E.Supercup", "E. Supercup", 5762),
        event(911, "rechter Verteidiger.", "rechter Verteidiger"),
        event(912, "rechter Mittelfeldspieler.", "rechter Mittelfeldspieler"),
        event(913, "linker Mittelfeldspieler.", "linker Mittelfeldspieler"),
        event(899,
              "Ihr Verein teilt Ihnen mit, daß ab dem Saisonende kein Interesse mehr an einer weiteren Zusammenarbeit "
              "mehr besteht. Es müßten neue Impulse kommen, um den Verein in eine gute Zukunft zu steuern. ",
              "Ihr Verein teilt Ihnen mit, daß ab dem Saisonende kein Interesse mehr an einer weiteren Zusammenarbeit "
              "besteht. Es müßten neue Impulse kommen, um den Verein in eine gute Zukunft zu steuern. "),
        event(905,
              "Ein Teil Ihres Stadions wurde fertiggestellt.",
              "Ein Teil Ihres Stadions wurde fertiggestellt.        "),
    )),
)
# fmt: on
KEYS = tuple(p.key for p in PATCHES)
# The installer: --typos every time (a bug fix), then one page per question, in this order, with the switches
# it applies; --contracts only on the command line.
ALWAYS = ("typos",)
QUESTIONS = {"EURO": ("euro",), "CENTREBACK": ("centre_back",), "NAMES": ("cups", "leagues", "groups")}
COMMAND_LINE_ONLY = ("contracts",)


def changes_in(patch, source):
    """The patch's changes of one source, in order."""
    return [c for c in patch.changes if c.source == source]


# --- files ------------------------------------------------------------------------------------------------


def ansi_decode(data):
    """Windows-1252 text (the event texts and the tips), undefined bytes kept as they are."""
    return data.decode("cp1252", errors="surrogateescape")


def ansi_encode(text):
    return text.encode("cp1252", errors="surrogateescape")


def read_events(data):
    """The texts of an event file (TEXTE/*.saq: the block's length and the number of texts, then the block,
    each byte XORed with the byte before it as stored, the first with the length's low byte; each text ended
    by a NUL); None if it isn't one."""
    if data is None or len(data) < 9 or struct.unpack_from("<i", data, 0)[0] != len(data) - 8:
        return None
    plain, key = bytearray(), data[0]
    for b in data[8:]:
        plain.append(key ^ b)
        key = b
    texts = ansi_decode(bytes(plain)).split("\0")
    if plain[-1] != 0 or len(texts) != struct.unpack_from("<i", data, 4)[0] + 1:
        return None
    return texts[:-1]


def write_events(original, texts):
    """texts as an event file, the number of texts as in original."""
    plain = ansi_encode("".join(t + "\0" for t in texts))
    result = bytearray(struct.pack("<i", len(plain)) + original[4:8])
    key = result[0]
    for p in plain:
        key = p ^ key
        result.append(key)
    return bytes(result)


def change_events(data, changes, on):
    """The event file with the changes made (on) or taken back."""
    texts = read_events(data)
    for change in changes:
        texts[change.ids[0]] = apply(change, texts[change.ids[0]], on)
    return write_events(data, texts)


def utf16(text):
    return text.encode("utf-16le", errors="surrogatepass")


def read_strings(data):
    """The 16 strings of a string table block (each its length in UTF-16 units and the units); None if it
    isn't one."""
    out, at = [], 0
    for _ in range(16):
        if data is None or at + 2 > len(data):
            return None
        length = struct.unpack_from("<H", data, at)[0]
        if at + 2 + 2 * length > len(data):
            return None
        out.append(data[at + 2 : at + 2 + 2 * length].decode("utf-16le", errors="surrogatepass"))
        at += 2 + 2 * length
    return out


def write_strings(table, original):
    """The block holding the 16 strings of table; what original has behind its strings stays."""
    out, end = bytearray(), 0
    for text in table:
        units = utf16(text)
        out += struct.pack("<H", len(units) // 2) + units
        end += 2 + 2 * struct.unpack_from("<H", original, end)[0]
    return bytes(out) + original[end:]


ITEM = object()  # where a dialog's item starts, aligned to 4 bytes


def align4(at):
    return (at + 3) & ~3


class Dialog:
    """A dialog template (DLGTEMPLATE or DLGTEMPLATEEX with its items) split into the texts that may change
    (the caption and the controls' texts) and the bytes around them, which stay. Written back, each item
    starts on a 4-byte boundary again, padded with zeros."""

    def __init__(self, data):
        """Raises ValueError if data isn't a dialog template."""
        self.parts = []  # bytes, a text (str) or ITEM
        self.data, self.done = data, 0
        ex = self.u16(0) == 1 and self.u16(2) == 0xFFFF
        style = struct.unpack_from("<I", data, 12 if ex else 0)[0]
        items, at = self.u16(16 if ex else 8), 26 if ex else 18
        at = self.skip_name(self.skip_name(at))  # menu, class
        self.raw(at)
        at = self.text(at)  # caption
        if style & 0x40:  # DS_SETFONT: size (weight, italic, charset), face
            at = self.skip_text(at + (6 if ex else 2))
        for _ in range(items):
            self.raw(at)
            self.done = at = align4(at)
            self.parts.append(ITEM)
            at = self.skip_name(at + (24 if ex else 18))  # fixed part, class
            self.raw(at)
            if self.u16(at) == 0xFFFF:
                at += 4  # a resource number, no text
            else:
                at = self.text(at)
            at += 2 + self.u16(at)  # creation data: its size, then the bytes
        if at > len(data):
            raise ValueError("dialog ends early")
        self.raw(len(data))
        del self.data

    def u16(self, at):
        if at + 2 > len(self.data):
            raise ValueError("dialog ends early")
        return struct.unpack_from("<H", self.data, at)[0]

    def skip_text(self, at):
        """Behind the NUL that ends the text at at."""
        while self.u16(at):
            at += 2
        return at + 2

    def skip_name(self, at):
        """Behind the name or number (FFFF and a word) at at."""
        return at + 4 if self.u16(at) == 0xFFFF else self.skip_text(at)

    def raw(self, end):
        self.parts.append(self.data[self.done : end])
        self.done = end

    def text(self, at):
        end = self.skip_text(at)
        self.parts.append(self.data[at : end - 2].decode("utf-16le", errors="surrogatepass"))
        self.done = end
        return end

    @property
    def texts(self):
        """The caption and the controls' texts."""
        return [p for p in self.parts if isinstance(p, str)]

    def change(self, function):
        """Changes every text by function."""
        self.parts = [function(p) if isinstance(p, str) else p for p in self.parts]

    def write(self):
        out = bytearray()
        for part in self.parts:
            if part is ITEM:
                out += bytes(align4(len(out)) - len(out))
            elif isinstance(part, str):
                out += utf16(part + "\0")
            else:
                out += part
        return bytes(out)


def read_dialog(data):
    """The dialog template data; None if it isn't one."""
    try:
        return None if data is None else Dialog(data)
    except (ValueError, struct.error):
        return None


def resource_key(rtype, rid):
    return (rtype, rid)


class Resources:
    """The string tables and dialogs of RESDLL.dll and the section the text switches add to it: ".a2gtxt",
    holding "A2GPatchTexts\\0", the number of switches applied and their names (each ended by a NUL), the
    number of resources moved and for each where its data entry is in the file and the address and size it
    had, then the moved resources' data. The resource directory points there. Without the section and with
    the entries back, the file is the original to the byte."""

    def __init__(self, data, pe, rsrc):
        self.data, self.pe = data, pe
        self.entries = {}  # (type, id): where its data entry is in the file (the first language)
        self.moved = {}  # data entry moved into the section: (address, size) it had
        self.applied = []  # the switches applied (Patch.key)
        root = self.offset(rsrc)
        for rtype, tdir in self.directory(root, root):
            for rid, ldir in self.directory(root, tdir):
                for _, entry in list(self.directory(root, ldir))[:1]:  # RESDLL.dll has only German
                    self.entries[(rtype, rid)] = entry
        name, _, _, _, raw, _ = pe.sections[-1]
        if name != SECTION:
            return
        if self.bytes(raw, len(MARKER)) != MARKER:
            raise ValueError("section of another program")
        at = raw + len(MARKER) + 4
        for _ in range(self.u32(at - 4)):
            end = self.data.index(b"\0", at)
            self.applied.append(self.data[at:end].decode("latin-1"))
            at = end + 1
        for _ in range(self.u32(at)):
            entry, address, size = struct.unpack("<III", self.bytes(at + 4, 12))
            self.moved[entry] = (address, size)
            at += 12

    @classmethod
    def read(cls, data):
        """The resources of the DLL data; None if it isn't a DLL with resources or its text section isn't
        A2G-Patch's."""
        try:
            if data is None or data[:2] != b"MZ" or data[struct.unpack_from("<I", data, 0x3C)[0] :][:4] != b"PE\0\0":
                return None
            pe = Pe(data)
            rsrc = struct.unpack_from("<I", data, pe.optional + 112)[0]
            return cls(data, pe, rsrc) if rsrc else None
        except (ValueError, struct.error, IndexError):
            return None

    def bytes(self, at, count):
        if at < 0 or at + count > len(self.data):
            raise ValueError("outside the file")
        return self.data[at : at + count]

    def u32(self, at):
        return struct.unpack("<I", self.bytes(at, 4))[0]

    def offset(self, rva):
        """Where the address rva (relative to the image base) lies in the file."""
        at = self.pe.file_offset(self.pe.image_base + rva)
        if at is None:
            raise ValueError("outside the sections")
        return at

    def directory(self, root, at):
        """The numbered entries of the resource directory at at: id and where its subdirectory or data
        entry is."""
        named, numbered = struct.unpack("<HH", self.bytes(at + 12, 4))
        for i in range(numbered):
            rid, target = struct.unpack("<II", self.bytes(at + 16 + 8 * (named + i), 8))
            yield rid, root + (target & 0x7FFFFFFF)

    def original_entry(self, entry):
        """The address and size the data entry at entry has in the original file."""
        return self.moved.get(entry) or (self.u32(entry), self.u32(entry + 4))

    def original(self, rtype, rid):
        """The original data of a resource; None if there is none."""
        entry = self.entries.get((rtype, rid))
        if entry is None:
            return None
        address, size = self.original_entry(entry)
        return self.bytes(self.offset(address), size)

    def original_string(self, sid):
        table = read_strings(self.original(STRING_TYPE, sid // 16 + 1))
        return None if table is None else table[sid % 16]

    def original_dialog(self, did):
        return read_dialog(self.original(DIALOG_TYPE, did))

    def write(self, applied, changed):
        """The file with the switches applied listed and the resources changed ({(type, id): data}) moved into
        the section; the original file if both are empty."""
        original = bytearray(self.data)
        for entry, (address, size) in self.moved.items():
            struct.pack_into("<II", original, entry, address, size)
        if self.pe.sections[-1][0] == SECTION:
            original = remove_last_section(original)
        if not applied and not changed:
            return bytes(original)
        pe = Pe(bytes(original))
        if not pe.has_room_for_section():
            raise ValueError("no room for another section header")
        data = bytearray(MARKER) + struct.pack("<i", len(applied))
        for name in applied:
            data += name.encode("latin-1") + b"\0"
        data += struct.pack("<i", len(changed))
        resources = [(self.entries[key], value) for key, value in changed.items()]
        for entry, _ in resources:
            data += struct.pack("<III", entry, *self.original_entry(entry))
        at = []
        for _, value in resources:
            data += bytes(-len(data) % 4)
            at.append(pe.size_of_image + len(data))
            data += value
        result = add_section(bytes(original), SECTION, bytes(data), READ_ONLY_DATA)
        for (entry, value), address in zip(resources, at):
            struct.pack_into("<II", result, entry, address, len(value))
        return bytes(result)


# --- switching --------------------------------------------------------------------------------------------


def build(res, keys):
    """RESDLL.dll with the changes of the switches in keys, made on the original in PATCHES' order."""
    patches = [p for p in PATCHES if p.key in keys]
    changed = {}
    string_changes = [c for p in patches for c in changes_in(p, STRING)]
    for block in dict.fromkeys(sid // 16 + 1 for c in string_changes for sid in c.ids):
        original = res.original(STRING_TYPE, block)
        table = read_strings(original)
        for change in string_changes:
            for sid in change.ids:
                if sid // 16 + 1 == block:
                    table[sid % 16] = apply(change, table[sid % 16], True)
        changed[resource_key(STRING_TYPE, block)] = write_strings(table, original)
    dialog_changes = [c for p in patches for c in changes_in(p, DIALOG)]
    for did in dict.fromkeys(did for c in dialog_changes for did in c.ids):
        dialog = res.original_dialog(did)
        for change in dialog_changes:
            if did in change.ids:
                dialog.change(lambda text, c=change: apply(c, text, True))
        changed[resource_key(DIALOG_TYPE, did)] = dialog.write()
    return res.write([p.key for p in patches], changed)


def fits(patch, res):
    """Whether every string and dialog the patch changes is in the original resources, with its text."""
    for change in changes_in(patch, STRING):
        for sid in change.ids:
            text = res.original_string(sid)
            if text is None or not is_in(change, text, False):
                return False
    for change in changes_in(patch, DIALOG):
        for did in change.ids:
            dialog = res.original_dialog(did)
            if dialog is None or not any(is_in(change, t, False) for t in dialog.texts):
                return False
    return True


DataFile = namedtuple("DataFile", "name is_on off on")


def data_files(patch, files):
    """The event files and the tips as far as the patch changes them; files that hold neither the game's
    texts nor the patch's are left out."""
    events = changes_in(patch, EVENT)
    for name in EVENT_FILES if events else ():
        data = files.read(name)
        texts = read_events(data)
        for on in (False, True):
            if texts is not None and all(c.ids[0] < len(texts) and is_in(c, texts[c.ids[0]], on) for c in events):
                other = change_events(data, events, not on)
                yield DataFile(name, on, other if on else data, data if on else other)
    tip_changes = changes_in(patch, TIPS)
    data = files.read(TIPS_FILE) if tip_changes else None
    if data is not None:
        text = ansi_decode(data)
        for on in (False, True):
            if all(is_in(c, text, on) and not is_in(c, text, not on) for c in tip_changes):
                other = text
                for c in tip_changes:
                    other = apply(c, other, not on)
                other = ansi_encode(other)
                yield DataFile(TIPS_FILE, on, other if on else data, data if on else other)


def state(patch, files):
    """ "on", "off" or None (the files aren't the game's)."""
    res = Resources.read(files.read(RESOURCE_FILE))
    if res is None or any(k not in KEYS for k in res.applied) or not fits(patch, res):
        return None
    on = patch.key in res.applied and all(d.is_on for d in data_files(patch, files))
    return "on" if on else "off"


def switch(patch, files, on):
    """Switches the patch on or off in files."""
    res = Resources.read(files.read(RESOURCE_FILE))
    if (patch.key in res.applied) != on:
        keys = set(res.applied) - {patch.key} | ({patch.key} if on else set())
        files.write(RESOURCE_FILE, build(res, keys))
    for d in list(data_files(patch, files)):
        if d.is_on != on:
            files.write(d.name, d.on if on else d.off)


def plain_resources(dll):
    """RESDLL.dll without the switches' changes (the data itself if it isn't readable): how a2resdll.py
    knows the file by its SHA-256."""
    res = Resources.read(dll)
    return dll if res is None else res.write([], {})


def with_texts_of(dll, plain):
    """plain, RESDLL.dll without text changes, with those of the switches applied in dll."""
    res = Resources.read(dll)
    if res is None or not res.applied:
        return plain
    return build(Resources.read(plain), set(res.applied))


def plain_events(data):
    """The event file with every switch's changes taken back (the data itself if none is in it, or it isn't
    an event file): how a2data101.py knows the file by its SHA-256."""
    texts = read_events(data)
    if texts is None:
        return data
    found = [
        c for p in PATCHES for c in changes_in(p, EVENT) if c.ids[0] < len(texts) and is_in(c, texts[c.ids[0]], True)
    ]
    return change_events(data, found, False) if found else data


class GameFiles:
    """The files of the game folder as they are or will be; names with "/", in any case on disk."""

    def __init__(self, folder):
        self.folder = folder
        self.files = {}  # name: bytes or None (missing), read once
        self.changed = []
        self.writes = 0  # how many times a file was written

    def path(self, name):
        path = self.folder
        for part in name.split("/"):
            path = os.path.join(path, match(path, part))
        return path

    def read(self, name):
        if name not in self.files:
            path = self.path(name)
            self.files[name] = None
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    self.files[name] = f.read()
        return self.files[name]

    def write(self, name, data):
        self.files[name] = data
        self.writes += 1
        if name not in self.changed:
            self.changed.append(name)

    def save(self):
        """Writes the changed files, each through a temporary file."""
        for name in self.changed:
            path = self.path(name)
            with open(path + ".tmp", "wb") as f:
                f.write(self.files[name])
            os.replace(path + ".tmp", path)
        self.changed = []


def main():
    """Switches the selected text patches on (or off with --off) in the game folder."""
    ap = argparse.ArgumentParser(description="Changes names and terms in the texts (ports from A2G-Patch).")
    ap.add_argument("--euro", action="store_true", help="amounts in € instead of DM, the numbers stay")
    ap.add_argument("--centre-back", action="store_true", help="Innenverteidiger (IV) instead of Manndecker (MD)")
    ap.add_argument("--cups", action="store_true", help="UEFA-Cup, Weltcup, ECL-Cup instead of UEFA-Pokal etc.")
    ap.add_argument("--leagues", action="store_true", help="today's league names")
    ap.add_argument("--groups", action="store_true", help="groups A to H instead of 1 to 8")
    ap.add_argument("--contracts", action="store_true", help="Grundgehalt, Ausstiegsklausel, Rekordtransfers")
    ap.add_argument("--typos", action="store_true", help="punctuation and typing errors in the game's texts")
    ap.add_argument("--off", action="store_true", help="take the named switches back")
    ap.add_argument("folder")
    a = ap.parse_args()
    selected = [p for p in PATCHES if getattr(a, p.option)]
    if not selected:
        ap.error("no switch selected")
    files = GameFiles(a.folder)
    if files.read(RESOURCE_FILE) is None:
        sys.exit(f"{a.folder}: no {RESOURCE_FILE}")
    wanted = "off" if a.off else "on"
    for patch in selected:
        if state(patch, files) is None:
            print(f"{patch.title}: {RESOURCE_FILE} doesn't hold the game's texts, left unchanged")
            continue
        # also when "off" only because a data file lost its changes: the list in RESDLL.dll goes as well
        before = files.writes
        switch(patch, files, not a.off)
        print(f"{patch.title}: {wanted}" if files.writes != before else f"{patch.title}: already {wanted}")
    files.save()


if __name__ == "__main__":
    main()

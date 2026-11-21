"""a2texts.py on synthetic game files: RESDLL.dll with string tables and dialogs, event files, tips."""

import runpy
import struct
import sys

import pytest

import a2patch
import a2texts as t

IMAGE_BASE, RSRC_RVA = 0x10000000, 0x1000
PE_AT, OPTIONAL_AT = 0x40, 0x40 + 24
SECTIONS_AT = OPTIONAL_AT + 0xE0


def align(n, to):
    return (n + to - 1) & -to


def rsrc_section(resources, named):
    """The resource directory (types, ids, one language each), the data entries, then the data;
    resources are (type, id, data)."""
    types = sorted({r[0] for r in resources})
    by_type = {k: [r for r in resources if r[0] == k] for k in types}
    root = 16 + 8 * (len(types) + named)
    type_dirs = sum(16 + 8 * len(v) for v in by_type.values())
    id_dirs, entries = 24 * len(resources), 16 * len(resources)
    data_at = align(root + type_dirs + id_dirs + entries, 4)
    s = bytearray(data_at + sum(align(len(r[2]), 4) for r in resources))
    s[12], s[14] = named, len(types)
    next_type, next_id = root, root + type_dirs
    next_entry, next_data, root_entry = next_id + id_dirs, data_at, 16
    if named:
        struct.pack_into("<II", s, root_entry, 0x80000000 | next_entry, 0x80000000 | root)  # never read
        root_entry += 8
    for rtype in types:
        struct.pack_into("<II", s, root_entry, rtype, 0x80000000 | next_type)
        root_entry += 8
        s[next_type + 14] = len(by_type[rtype])
        type_entry = next_type + 16
        next_type += 16 + 8 * len(by_type[rtype])
        for _, rid, data in by_type[rtype]:
            struct.pack_into("<II", s, type_entry, rid, 0x80000000 | next_id)
            type_entry += 8
            s[next_id + 14] = 1
            struct.pack_into("<II", s, next_id + 16, 1031, next_entry)
            next_id += 24
            struct.pack_into("<II", s, next_entry, RSRC_RVA + next_data, len(data))
            next_entry += 16
            s[next_data : next_data + len(data)] = data
            next_data += align(len(data), 4)
    return bytes(s)


def dll(resources, named=False, section_name=b".rsrc", resource_rva=RSRC_RVA, first=0x400):
    """A DLL whose only section (its data at first) holds the resources."""
    section = rsrc_section(list(resources), named)
    raw_size = align(len(section), 0x200)
    image = bytearray(first + raw_size)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, PE_AT)
    image[PE_AT : PE_AT + 4] = b"PE\0\0"
    struct.pack_into("<HH", image, PE_AT + 4, 0x14C, 1)
    struct.pack_into("<H", image, PE_AT + 20, 0xE0)
    struct.pack_into("<H", image, OPTIONAL_AT, 0x10B)
    struct.pack_into("<III", image, OPTIONAL_AT + 28, IMAGE_BASE, 0x1000, 0x200)
    struct.pack_into("<II", image, OPTIONAL_AT + 56, RSRC_RVA + align(len(section), 0x1000), first)
    struct.pack_into("<I", image, OPTIONAL_AT + 92, 16)
    struct.pack_into("<II", image, OPTIONAL_AT + 112, resource_rva, len(section))
    struct.pack_into("<8sIIII", image, SECTIONS_AT, section_name, len(section), RSRC_RVA, raw_size, first)
    struct.pack_into("<I", image, SECTIONS_AT + 36, 0x40000040)
    image[first : first + len(section)] = section
    return bytes(image)


def string_block(strings):
    """A block of 16 strings ({index: text}), the rest empty."""
    out = b""
    for i in range(16):
        text = strings.get(i, "").encode("utf-16le")
        out += struct.pack("<H", len(text) // 2) + text
    return out


def dialog(caption, *controls):
    """A DIALOGEX with font, the caption and a static control for each text."""
    d = bytearray([1, 0, 0xFF, 0xFF] + [0] * 8) + struct.pack("<IH", 0x80C800C0, len(controls)) + bytes(8 + 4)
    d += (caption + "\0").encode("utf-16le") + bytes([8, 0, 0, 0, 0, 1]) + "MS Sans Serif\0".encode("utf-16le")
    for control in controls:
        d += bytes(-len(d) % 4)
        d += struct.pack("<IIIhhhhI", 0, 0x200, 0x50020301, 0, 0, 0, 0, 0xFFFFFFFF) + b"\xff\xff\x82\x00"
        d += (control + "\0").encode("utf-16le") + bytes(2)
    return bytes(d)


def all_changes():
    return [c for p in t.PATCHES for c in p.changes]


def resources(change=lambda source, rid, text: text, without=-1):
    """The game's RESDLL.dll as far as the switches look at it: each string and dialog they change holding the
    texts they look for (change may alter them), and string 1147 "DM"; dialog without left out."""
    strings = {}
    for c in all_changes():
        if c.source == t.STRING:
            for sid in c.ids:
                strings.setdefault(sid, [])
                if c.frm not in strings[sid]:
                    strings[sid].append(c.frm)
    strings = {sid: change(t.STRING, sid, " | ".join(texts)) for sid, texts in strings.items()}
    strings[1147] = "DM"
    blocks = {}
    for sid, text in strings.items():
        blocks.setdefault(sid // 16 + 1, {})[sid % 16] = text
    out = [(t.STRING_TYPE, block, string_block(texts)) for block, texts in blocks.items()]
    dialogs = {}
    for c in all_changes():
        if c.source == t.DIALOG:
            for did in c.ids:
                text = change(t.DIALOG, did, c.frm)
                dialogs.setdefault(did, [])
                if text not in dialogs[did]:
                    dialogs[did].append(text)
    out += [(t.DIALOG_TYPE, did, dialog("ANSTOSS 2", *texts)) for did, texts in dialogs.items() if did != without]
    return dll(out)


def events(change=None, count=1000):
    """An event file of count texts, "Text n" except where a switch looks for its text."""
    texts = [f"Text {i}" for i in range(count)]
    for c in all_changes():
        if c.source == t.EVENT and c.ids[0] < count:
            texts[c.ids[0]] = c.frm
    if change:
        texts = [change(i, text) for i, text in enumerate(texts)]
    return t.write_events(struct.pack("<ii", 0, len(texts)), texts)


TIPS = "Kaufen Sie für 1 Million DM.\r\nOder 300.000 DM?\r\n".encode("cp1252")


def game(folder, res=None, ev=None, tips=TIPS, names=("TEXTE/EreigGld.saq", "TEXTE/EreigGold.saq")):
    """RESDLL.dll, the event files and the tips in folder; files with None are left out."""
    (folder / "TEXTE").mkdir(exist_ok=True)
    (folder / "RESDLL.dll").write_bytes(resources() if res is None else res)
    for name in names:
        (folder / name).write_bytes(events() if ev is None else ev)
    if tips is not None:
        (folder / "TEXTE" / "tips.txt").write_bytes(tips)
    return folder


def files_of(folder):
    """{name: bytes} of the files in folder."""
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def resource_now(data, rtype, rid):
    """The current data of a resource, following the directory."""
    res = t.Resources.read(data)
    address, size = struct.unpack_from("<II", data, res.entries[(rtype, rid)])
    return data[res.offset(address) : res.offset(address) + size]


def string_now(data, sid):
    return t.read_strings(resource_now(data, t.STRING_TYPE, sid // 16 + 1))[sid % 16]


def dialog_now(data, did):
    return t.read_dialog(resource_now(data, t.DIALOG_TYPE, did)).texts


def patch(key):
    return next(p for p in t.PATCHES if p.key == key)


# --- changes ----------------------------------------------------------------------------------------------


def test_the_switches_in_their_order():
    assert t.KEYS == ("Currency", "CentreBack", "CupNames", "LeagueNames", "GroupLetters", "ContractTerms", "TextTypos")
    assert [p.title for p in t.PATCHES] == [
        "Euro statt DM",
        "Innenverteidiger",
        "Europapokale",
        "Liganamen",
        "Gruppen A bis H",
        "Vertragsbegriffe",
        "Tippfehler",
    ]


def test_event_changes_keep_the_length_each_switch_on_its_own():
    for p in t.PATCHES:
        changes = t.changes_in(p, t.EVENT)
        assert sum(len(t.ansi_encode(c.frm)) for c in changes) == sum(len(t.ansi_encode(c.to)) for c in changes)


def test_replace_takes_whole_words_only():
    assert t.replace("1 DM und 2 DM. 3 DMX", " DM", " €") == "1 € und 2 €. 3 DMX"
    assert t.replace("MD, XMD, MD", "MD", "IV") == "IV, XMD, IV"
    assert t.replace("Gruppe 1, Gruppe 10", "Gruppe 1", "Gruppe A") == "Gruppe A, Gruppe 10"
    assert t.replace("keins", "MD", "IV") == "keins"
    assert t.word_char("ü") and t.word_char("7") and not t.word_char("²") and not t.word_char(".")


def test_changes_go_both_ways():
    words, whole = t.strings("MD", "IV", 1), t.event(1, "Manndecker", "Innenverteidiger")
    assert t.apply(words, "MD", True) == "IV" and t.apply(words, "IV", False) == "MD"
    assert t.apply(whole, "Manndecker", True) == "Innenverteidiger"
    assert t.apply(whole, "Innenverteidiger", False) == "Manndecker"
    assert t.apply(whole, "Torwart", True) == "Torwart"
    assert t.is_in(words, "ein MD", False) and not t.is_in(words, "ein MD", True)
    assert t.is_in(whole, "Innenverteidiger", True) and not t.is_in(whole, "Innenverteidiger x", True)
    assert t.tips("a", "b") == (t.TIPS, "a", "b", ())


# --- files ------------------------------------------------------------------------------------------------


def test_event_file_reads_and_writes_the_texts():
    data = events()
    texts = t.read_events(data)
    assert len(texts) == 1000 and texts[909] == "Manndecker" and texts[0] == "Text 0"
    assert t.write_events(data, texts) == data
    texts[909] = "Innenverteidiger"
    assert t.read_events(t.write_events(data, texts))[909] == "Innenverteidiger"
    undefined = t.write_events(data, ["\udc81"] + texts[1:])  # a byte cp1252 leaves undefined
    assert t.read_events(undefined)[0] == "\udc81"


@pytest.mark.parametrize("broken", ["none", "short", "length", "end", "count"])
def test_event_file_is_none_for_other_files(broken):
    data = bytearray(events(count=3))
    if broken == "none":
        data = None
    elif broken == "short":
        data = data[:8]
    elif broken == "length":
        data += b"x"
    elif broken == "end":
        data[-1] = data[-2] ^ ord("x")  # the last plain byte becomes "x" instead of the NUL
    else:
        struct.pack_into("<i", data, 4, 4)
    assert t.read_events(None if data is None else bytes(data)) is None


def test_string_table_reads_sixteen_strings_and_keeps_what_follows():
    block = string_block({3: "Manndecker", 15: "Ende"}) + b"\x01\x02"
    table = t.read_strings(block)
    assert table[3] == "Manndecker" and table[15] == "Ende" and table[0] == ""
    table[3] = "Innenverteidiger"
    out = t.write_strings(table, block)
    assert t.read_strings(out)[3] == "Innenverteidiger" and out.endswith(b"\x01\x02")
    assert t.read_strings(None) is None
    assert t.read_strings(block[:4]) is None  # too few strings
    assert t.read_strings(struct.pack("<H", 5) + b"ab") is None  # a string longer than the block


def test_dialog_changes_only_the_texts_and_realigns_the_items():
    data = dialog("Titel DM", "1 DM", "Zwei")
    d = t.read_dialog(data)
    assert d.texts == ["Titel DM", "1 DM", "Zwei"]
    assert d.write() == data
    d.change(lambda text: t.replace(text, " DM", " Euro"))
    out = d.write()
    assert t.read_dialog(out).texts == ["Titel Euro", "1 Euro", "Zwei"]
    assert out.count(struct.pack("<I", 0x50020301)) == 2
    second = out.rindex(struct.pack("<I", 0x50020301)) - 8
    assert second % 4 == 0


def old_dialog():
    """A DLGTEMPLATE without font: a control with a numbered text and creation data, one with a class by name."""
    d = struct.pack("<IIH4h", 0x80000000, 0, 2, 0, 0, 10, 10) + b"\0\0\0\0" + "Alt\0".encode("utf-16le")
    d += bytes(-len(d) % 4) + struct.pack("<II5h", 0x50000000, 0, 0, 0, 1, 1, 7)
    d += b"\xff\xff\x82\x00" + b"\xff\xff\x05\x00" + struct.pack("<H", 2) + b"\xaa\xbb"
    d += bytes(-len(d) % 4) + struct.pack("<II5h", 0x50000000, 0, 0, 0, 1, 1, 8)
    d += "Button\0".encode("utf-16le") + "OK\0".encode("utf-16le") + b"\0\0"
    return d


def test_dialog_reads_old_templates_with_numbers_and_creation_data():
    d = t.read_dialog(old_dialog())
    assert d.texts == ["Alt", "OK"]
    assert d.write() == old_dialog()


def test_dialog_is_none_for_other_data():
    assert t.read_dialog(None) is None
    assert t.read_dialog(old_dialog()[:-6]) is None  # inside the last text
    assert t.read_dialog(old_dialog()[:-2]) is None  # without the creation data's size
    longer = bytearray(old_dialog())
    struct.pack_into("<H", longer, len(longer) - 2, 4)  # creation data behind the end
    assert t.read_dialog(bytes(longer)) is None


def test_resources_find_the_originals():
    res = t.Resources.read(resources())
    assert res.applied == [] and res.moved == {}
    assert res.original_string(1174) == "Manndecker" and res.original_string(1147) == "DM"
    assert res.original_string(16 * 1000) is None
    assert res.original_dialog(274).texts[0] == "ANSTOSS 2"
    assert res.original_dialog(1) is None
    assert t.Resources.read(dll([(6, 1, string_block({}))], named=True)).original_string(0) == ""


@pytest.mark.parametrize(
    "data",
    [
        None,
        b"MZ",
        b"XX" + bytes(0x200),
        dll([(6, 1, b"")])[:0x40] + b"NE" + dll([(6, 1, b"")])[0x42:],
        dll([(6, 1, b"")], resource_rva=0),
        dll([(6, 1, b"")], resource_rva=0x9000),  # outside the sections
        dll([(6, 1, b"")], section_name=t.SECTION.encode()),  # a text section of another program
    ],
)
def test_resources_are_none_for_other_files(data):
    assert t.Resources.read(data) is None


def test_resources_outside_the_file():
    res = t.Resources.read(resources())
    with pytest.raises(ValueError):
        res.bytes(len(res.data) - 2, 4)


def test_resources_need_room_for_their_section():
    tight = dll([(6, 1, string_block({0: "MD"}))], first=SECTIONS_AT + 40)
    res = t.Resources.read(tight)
    with pytest.raises(ValueError, match="no room"):
        res.write(["x"], {})
    assert res.write([], {}) == tight


# --- switching --------------------------------------------------------------------------------------------


def test_each_switch_changes_its_texts_and_back_to_the_byte(tmp_path):
    folder = game(tmp_path)
    original = files_of(folder)
    for p in t.PATCHES:
        files = t.GameFiles(str(folder))
        assert t.state(p, files) == "off"
        t.switch(p, files, True)
        assert t.state(p, files) == "on"
        files.save()
        assert t.state(p, t.GameFiles(str(folder))) == "on"
        assert t.Resources.read(files.read("RESDLL.dll")).applied == [p.key]
        t.switch(p, files, False)
        assert t.state(p, files) == "off"
        files.save()
        assert files_of(folder) == original, p.key


def test_all_switches_change_the_texts_in_any_order(tmp_path):
    folder = game(tmp_path)
    original = files_of(folder)
    for order in (t.PATCHES, t.PATCHES[::-1]):
        files = t.GameFiles(str(folder))
        for p in order:
            t.switch(p, files, True)
        dll_now = files.read("RESDLL.dll")
        assert t.Resources.read(dll_now).applied == list(t.KEYS)
        assert string_now(dll_now, 2162) == " €" and string_now(dll_now, 1147) == "DM"
        assert string_now(dll_now, 1144) == "IV" and string_now(dll_now, 1174) == "Innenverteidiger"
        # the cup names first, then the typing errors: "UEFA - Pokals" becomes "UEFA-Cups"
        assert string_now(dll_now, 2642) == "UEFA-Cups"
        assert "Cup der Pokalsieger" in dialog_now(dll_now, 274) and "ECL" in dialog_now(dll_now, 274)
        ev = t.read_events(files.read("TEXTE/EreigGold.saq"))
        assert ev[909] == "Innenverteidiger" and ev[911] == "rechter Verteidiger"
        assert len(files.read("TEXTE/EreigGld.saq")) == len(events())
        assert files.read("TEXTE/tips.txt") == "Kaufen Sie für 1 Million €.\r\nOder 300.000 €?\r\n".encode("cp1252")
        for p in order:
            t.switch(p, files, False)
        files.save()
        assert files_of(folder) == original


def test_data_files_in_another_state_are_left_out(tmp_path):
    other = events(lambda i, text: "anders" if i == 909 else text)
    folder = game(tmp_path, ev=other, tips=b"Ohne Waehrung", names=("TEXTE/EreigGld.saq",))
    files = t.GameFiles(str(folder))
    back = patch("CentreBack")
    assert list(t.data_files(back, files)) == []
    t.switch(back, files, True)
    assert t.state(back, files) == "on" and files.changed == ["RESDLL.dll"]
    assert [d.name for d in t.data_files(patch("Currency"), files)] == ["TEXTE/EreigGld.saq"]  # no tips
    assert list(t.data_files(patch("GroupLetters"), files)) == []  # no event or tips changes
    (folder / "TEXTE" / "EreigGld.saq").write_bytes(b"kein Ereignis")
    assert list(t.data_files(back, t.GameFiles(str(folder)))) == []


def test_switching_on_completes_the_data_files(tmp_path):
    folder = game(tmp_path)
    files = t.GameFiles(str(folder))
    euro = patch("Currency")
    t.switch(euro, files, True)
    files.save()
    (folder / "TEXTE" / "tips.txt").write_bytes(TIPS)  # e.g. from a data set
    files = t.GameFiles(str(folder))
    assert t.state(euro, files) == "off"
    t.switch(euro, files, True)
    assert files.changed == ["TEXTE/tips.txt"] and t.state(euro, files) == "on"


def test_unknown_switch_in_the_file_makes_all_unknown(tmp_path):
    res = t.Resources.read(resources())
    folder = game(tmp_path, res=res.write(["Unbekannt"], {}))
    files = t.GameFiles(str(folder))
    assert all(t.state(p, files) is None for p in t.PATCHES)


def test_switches_that_dont_fit_are_unknown(tmp_path):
    files = t.GameFiles(str(game(tmp_path, res=resources(without=274))))
    assert t.state(patch("CupNames"), files) is None and t.state(patch("Currency"), files) == "off"
    changed = resources(lambda source, rid, text: "anders" if source == t.DIALOG and rid == 200 else text)
    files = t.GameFiles(str(game(tmp_path, res=changed)))
    assert t.state(patch("CentreBack"), files) is None
    changed = resources(lambda source, rid, text: "anders" if source == t.STRING and rid == 6032 else text)
    files = t.GameFiles(str(game(tmp_path, res=changed)))
    assert t.state(patch("GroupLetters"), files) is None
    files = t.GameFiles(str(game(tmp_path, res=dll([(6, 1, string_block({}))]))))
    assert t.state(patch("GroupLetters"), files) is None  # string missing
    files = t.GameFiles(str(game(tmp_path, res=b"kein PE")))
    assert t.state(patch("GroupLetters"), files) is None


def test_plain_events_takes_the_changes_back(tmp_path):
    data = events()
    assert t.plain_events(data) == data and t.plain_events(b"x") == b"x"
    files = t.GameFiles(str(game(tmp_path)))
    for p in t.PATCHES:
        t.switch(p, files, True)
    assert t.plain_events(files.read("TEXTE/EreigGold.saq")) == data


def test_plain_resources_and_with_texts_of():
    plain = resources()
    files_dll = t.build(t.Resources.read(plain), {"Currency", "TextTypos"})
    assert t.plain_resources(files_dll) == plain and t.plain_resources(b"x") == b"x"
    assert t.with_texts_of(plain, b"anders") == b"anders" and t.with_texts_of(b"x", b"anders") == b"anders"
    assert t.with_texts_of(files_dll, plain) == files_dll
    assert t.Resources.read(t.with_texts_of(files_dll, plain)).applied == ["Currency", "TextTypos"]


def test_section_like_a2g_patch():
    """The section holds the marker, the switches and the moved resources with their original entries."""
    plain = resources()
    data = t.build(t.Resources.read(plain), {"GroupLetters"})
    pe = a2patch.Pe(data)
    name, vsize, va, _, raw, flags = pe.sections[-1]
    assert (name, flags, va) == (t.SECTION, t.READ_ONLY_DATA, a2patch.Pe(plain).size_of_image)
    assert data[raw : raw + 14] == t.MARKER
    assert struct.unpack_from("<i", data, raw + 14)[0] == 1 and data[raw + 18 : raw + 31] == b"GroupLetters\0"
    res = t.Resources.read(data)
    blocks = sorted({sid // 16 + 1 for c in patch("GroupLetters").changes for sid in c.ids})
    assert sorted(res.moved) == sorted(res.entries[(t.STRING_TYPE, b)] for b in blocks)
    # taken back, the 40 bytes behind the section headers are as before
    assert t.plain_resources(data) == plain


def test_game_files_read_once_and_keep_the_case(tmp_path):
    (tmp_path / "texte").mkdir()
    (tmp_path / "texte" / "TIPS.TXT").write_bytes(b"a")
    files = t.GameFiles(str(tmp_path))
    assert files.read("TEXTE/tips.txt") == b"a"
    (tmp_path / "texte" / "TIPS.TXT").write_bytes(b"b")
    assert files.read("TEXTE/tips.txt") == b"a" and files.read("RESDLL.dll") is None
    files.write("TEXTE/tips.txt", b"c")
    files.write("TEXTE/tips.txt", b"d")
    files.save()
    assert (tmp_path / "texte" / "TIPS.TXT").read_bytes() == b"d" and files.changed == [] and files.writes == 2
    assert sorted(p.name for p in (tmp_path / "texte").iterdir()) == ["TIPS.TXT"]


# --- command line -----------------------------------------------------------------------------------------


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["a2texts.py", *map(str, args)])
    t.main()


def test_main_switches_on_and_off(tmp_path, monkeypatch, capsys):
    folder = game(tmp_path)
    original = files_of(folder)
    run_main(monkeypatch, "--euro", "--typos", folder)
    assert capsys.readouterr().out == "Euro statt DM: on\nTippfehler: on\n"
    assert t.Resources.read((folder / "RESDLL.dll").read_bytes()).applied == ["Currency", "TextTypos"]
    run_main(monkeypatch, "--euro", "--cups", folder)
    assert capsys.readouterr().out == "Euro statt DM: already on\nEuropapokale: on\n"
    options = ["--euro", "--centre-back", "--cups", "--leagues", "--groups", "--contracts", "--typos"]
    run_main(monkeypatch, "--off", *options, folder)
    out = capsys.readouterr().out
    assert "Innenverteidiger: already off" in out and "Europapokale: off" in out
    assert files_of(folder) == original


def test_main_takes_the_list_back_when_a_data_file_lost_its_changes(tmp_path, monkeypatch, capsys):
    folder = game(tmp_path)
    original = files_of(folder)
    run_main(monkeypatch, "--euro", folder)
    (folder / "TEXTE" / "tips.txt").write_bytes(TIPS)
    run_main(monkeypatch, "--off", "--euro", folder)
    assert capsys.readouterr().out.endswith("Euro statt DM: off\n")
    assert files_of(folder) == original


def test_main_leaves_other_files_alone(tmp_path, monkeypatch, capsys):
    folder = game(tmp_path, res=resources(without=274))
    original = files_of(folder)
    run_main(monkeypatch, "--cups", folder)
    assert capsys.readouterr().out == "Europapokale: RESDLL.dll doesn't hold the game's texts, left unchanged\n"
    assert files_of(folder) == original


def test_main_without_resdll(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="no RESDLL.dll"):
        run_main(monkeypatch, "--typos", tmp_path)


def test_main_usage(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["a2texts.py", "x"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(t.__file__, run_name="__main__")
    assert e.value.code == 2

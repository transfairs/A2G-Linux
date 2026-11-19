"""a2resdll.py on synthetic dialog templates."""

import runpy
import struct
import sys

import pytest

import a2resdll as r


def text(s):
    return s.encode("utf-16le") + b"\0\0"


def template(style, title="Titel", font=None, controls=()):
    """DLGTEMPLATE (not extended); controls are (style, exstyle)."""
    b = struct.pack("<IIH4h", style, 0, len(controls), 0, 0, 100, 50) + b"\0\0" + b"\0\0" + text(title)
    if font:
        b += struct.pack("<H", 8) + text(font)
    for st, exst in controls:
        b += bytes(-len(b) % 4)
        b += struct.pack("<II4hH", st, exst, 0, 0, 10, 10, 1) + b"\xff\xff\x80\x00" + text("OK") + b"\0\0"
    return bytearray(b)


def ex_template(style, font, charset=0, controls=()):
    """DLGTEMPLATEEX with a font; controls are (style, exstyle, id)."""
    style |= 0x40  # DS_SETFONT
    b = struct.pack("<HHIIIH4h", 1, 0xFFFF, 0, 0, style, len(controls), 0, 0, 100, 50) + b"\0\0" + b"\0\0"
    b += text("Titel") + struct.pack("<HHBB", 8, 400, 0, charset) + text(font)
    for st, exst, cid in controls:
        b += bytes(-len(b) % 4)
        b += struct.pack("<III4hI", 0, exst, st, 0, 0, 10, 10, cid) + b"\xff\xff\x80\x00" + text("OK") + b"\0\0"
    return bytearray(b)


def test_string_end():
    b = text("ab") + b"\xff\xff\x05\x00"
    assert r.string_end(b, 0) == 6
    assert r.string_end(b, 6) == 10


def test_put():
    b = bytearray(4)
    r.put(b, 0, "<I", 0, 7)
    assert struct.unpack("<I", b)[0] == 7
    with pytest.raises(r.Mismatch):
        r.put(b, 0, "<I", 0, 8)


def test_dialog_gets_a_title_bar():
    b = template(0x80000000)
    r.fix_dialog(b, 0, r.DE, 1)
    assert struct.unpack_from("<I", b, 0)[0] == 0x80000000 | r.WS_CAPTION


def test_captionless_dialog_stays_without_title_bar():
    did = r.CAPTIONLESS[r.DE][0]
    b = template(0x80000000)
    r.fix_dialog(b, 0, r.DE, did)
    assert struct.unpack_from("<I", b, 0)[0] == 0x80000000


def test_styles_table():
    (gog, cd), table = next(iter(r.STYLES.items()))
    lang, ids = next(iter(table.items()))
    b = template(gog, font="x")  # the style has DS_SETFONT
    r.fix_dialog(b, 0, lang, ids[0])
    assert struct.unpack_from("<I", b, 0)[0] == cd
    with pytest.raises(r.Mismatch):
        r.fix_dialog(template(gog ^ 1, font="x"), 0, lang, ids[0])


def test_quotes_in_title():
    lang, did = r.QUOTES[0]
    b = template(r.WS_CAPTION, title="'Hallo'")
    r.fix_dialog(b, 0, lang, did)
    assert text('"Hallo"') in b
    with pytest.raises(r.Mismatch):
        r.fix_dialog(template(r.WS_CAPTION, title="Hallo"), 0, lang, did)


def test_font_name_and_charset():
    b = ex_template(r.WS_CAPTION, r.FACE_GOG, controls=[(0, 0, 1)])
    r.fix_dialog(b, 0, r.DE, 1)
    assert text(r.FACE) in b and text(r.FACE_GOG) not in b
    assert b[b.index(text(r.FACE)) - 1] == r.DEFAULT_CHARSET
    plain = template(r.WS_CAPTION | 0x40, font=r.FACE_GOG)
    r.fix_dialog(plain, 0, r.DE, 1)
    assert text(r.FACE) in plain


def test_controls_get_their_frame_back():
    did, indexes = next(
        (did, ix)
        for did, ix in r.CLIENTEDGE[r.DE].items()
        if not any(r.in_table(t, r.DE, did) for t in [r.CAPTIONLESS, *r.STYLES.values()])
        and (r.DE, did) not in r.EX_STYLES
    )
    controls = [(0, 0)] * (max(indexes) + 1)
    b = template(r.WS_CAPTION, controls=controls)
    r.fix_dialog(b, 0, r.DE, did)
    count_at, p = 8, r.string_end(b, r.string_end(b, r.string_end(b, 18)))
    for i in range(struct.unpack_from("<H", b, count_at)[0]):
        p = (p + 3) & ~3
        exst = struct.unpack_from("<I", b, p + 4)[0]
        assert bool(exst & r.WS_EX_CLIENTEDGE) == (i in indexes)
        p = r.string_end(b, r.string_end(b, p + 18))
        p += 2 + struct.unpack_from("<H", b, p)[0]


def test_ex_control_ids_become_32_bit():
    b = ex_template(r.WS_CAPTION, "x", controls=[(0, 0, 0xFFFF)])
    r.fix_dialog(b, 0, r.DE, 1)
    assert struct.pack("<I", 0xFFFFFFFF) in b


def pe_file(templates, rva_shift=0):
    """Minimal PE32 DLL with one .rsrc section; templates are (lang, dialog id, bytes)."""
    peo, optsize, raw, va = 0x40, 0xE0, 0x200, 0x1000
    rsrc = bytearray()

    def directory(entries):
        at = len(rsrc)
        rsrc.extend(struct.pack("<IIHHHH", 0, 0, 0, 0, 0, len(entries)) + bytes(8 * len(entries)))
        return at

    root = directory([0, 0])
    other = directory([])
    dialog_dir = directory(templates)
    struct.pack_into("<II", rsrc, root + 16, 3, 0x80000000 | other)  # RT_STRING, skipped
    struct.pack_into("<II", rsrc, root + 24, 5, 0x80000000 | dialog_dir)
    for i, (lang, did, tpl) in enumerate(templates):
        lang_dir = directory([0])
        data = len(rsrc)
        rsrc.extend(bytes(16))
        struct.pack_into("<II", rsrc, dialog_dir + 16 + 8 * i, did, 0x80000000 | lang_dir)
        struct.pack_into("<II", rsrc, lang_dir + 16, lang, data)
        rsrc.extend(bytes(-len(rsrc) % 4))
        struct.pack_into("<II", rsrc, data, va + len(rsrc) + rva_shift, len(tpl))
        rsrc.extend(tpl)
    b = bytearray(raw)
    struct.pack_into("<I", b, 0x3C, peo)
    b[peo : peo + 4] = b"PE\0\0"
    struct.pack_into("<HH", b, peo + 6, 1, 0)
    struct.pack_into("<H", b, peo + 20, optsize)
    struct.pack_into("<II", b, peo + 24 + 96 + 16, va, len(rsrc))
    struct.pack_into("<IIII", b, peo + 24 + optsize + 8, len(rsrc), va, len(rsrc), raw)
    return bytes(b + rsrc)


def test_dialogs_lists_only_dialog_templates():
    a, b = template(0x80000000), template(r.WS_CAPTION, title="Zwei")
    pe = pe_file([(r.DE, 7, a), (r.GB, 8, b)])
    found = list(r.dialogs(pe))
    assert [(lang, did, size) for lang, did, _, size in found] == [(r.DE, 7, len(a)), (r.GB, 8, len(b))]
    assert [pe[o : o + size] for _, _, o, size in found] == [a, b]


def test_restore_changes_the_dialogs():
    pe = pe_file([(r.DE, 7, template(0x80000000))])
    result = r.restore(pe)
    assert len(result) == len(pe)
    ((_, _, o, _),) = r.dialogs(result)
    assert struct.unpack_from("<I", result, o)[0] == 0x80000000 | r.WS_CAPTION


def test_restore_refuses_unexpected_files(capsys):
    (gog, _), table = next(iter(r.STYLES.items()))
    lang, ids = next(iter(table.items()))
    assert r.restore(pe_file([(lang, ids[0], template(gog ^ 1, font="x"))])) is None
    assert r.restore(pe_file([(r.DE, 7, template(0x80000000))], rva_shift=0x10000)) is None
    out = capsys.readouterr().out
    assert "instead of" in out and "outside the sections" in out


def test_ex_style_removed():
    (lang, did), (old, new) = next(iter(r.EX_STYLES.items()))
    gog = next(g for (g, _), table in r.STYLES.items() if r.in_table(table, lang, did))
    b = template(gog, font="x")
    struct.pack_into("<I", b, 4, old)
    r.fix_dialog(b, 0, lang, did)
    assert struct.unpack_from("<I", b, 4)[0] == new


def test_charset_already_default():
    b = ex_template(r.WS_CAPTION, r.FACE, charset=r.DEFAULT_CHARSET)
    before = bytes(b)
    r.fix_dialog(b, 0, r.DE, 1)
    assert bytes(b) == before


def control_styles(b):
    """(style, exstyle) of the controls of a non-extended template."""
    count, p = struct.unpack_from("<H", b, 8)[0], r.string_end(b, r.string_end(b, r.string_end(b, 18)))
    if struct.unpack_from("<I", b, 0)[0] & 0x40:
        p = r.string_end(b, p + 2)
    for _ in range(count):
        p = (p + 3) & ~3
        yield struct.unpack_from("<II", b, p)
        p = r.string_end(b, r.string_end(b, p + 18))
        p += 2 + struct.unpack_from("<H", b, p)[0]


def test_transparent_controls():
    (lang, did), indexes = next(iter(r.TRANSPARENT.items()))
    b = template(r.WS_CAPTION, controls=[(0, 0)] * (max(indexes) + 2))
    r.fix_dialog(b, 0, lang, did)
    for i, (_, exst) in enumerate(control_styles(b)):
        assert bool(exst & r.WS_EX_TRANSPARENT) == (i in indexes)


def test_border_replaced_by_sunken_frame():
    (lang, did), indexes = next(iter(r.BORDER_INSTEAD.items()))
    b = template(r.WS_CAPTION, controls=[(r.WS_BORDER, 0)] * (max(indexes) + 1))
    r.fix_dialog(b, 0, lang, did)
    for i, (st, exst) in enumerate(control_styles(b)):
        assert bool(st & r.WS_BORDER) == (i not in indexes)
        assert bool(exst & r.WS_EX_CLIENTEDGE) == (i in indexes)


@pytest.fixture
def game(tmp_path, monkeypatch):
    """Game folder with a synthetic RESDLL.dll whose hashes are the expected ones."""
    src = pe_file([(r.DE, 7, template(0x80000000)), (r.GB, 8, template(r.WS_CAPTION))])
    (tmp_path / "resdll.dll").write_bytes(src)
    monkeypatch.setattr(r, "GOG", r.sha(src))
    monkeypatch.setattr(r, "RESULT", r.sha(r.restore(src)))
    return tmp_path, src


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["a2resdll.py", *map(str, args)])
    r.main()


def test_main_restores_and_keeps_the_original(game, monkeypatch, capsys):
    folder, src = game
    dll, backup = folder / "resdll.dll", folder / ("resdll.dll" + r.BACKUP_SUFFIX)
    run_main(monkeypatch, folder)
    assert dll.read_bytes() == r.restore(src) and backup.read_bytes() == src
    run_main(monkeypatch, folder)
    assert "already there" in capsys.readouterr().out
    dll.write_bytes(b"broken")
    run_main(monkeypatch, folder)
    assert dll.read_bytes() == r.restore(src) and backup.read_bytes() == src
    assert capsys.readouterr().out == "RESDLL.dll: dialog styles of 1999\n"


def test_main_refuses_other_files(game, monkeypatch, capsys):
    folder, src = game
    monkeypatch.setattr(r, "GOG", "0" * 64)
    with pytest.raises(SystemExit) as e:
        run_main(monkeypatch, folder)
    assert e.value.code == 1
    assert "not the file of the GOG version" in capsys.readouterr().out
    assert (folder / "resdll.dll").read_bytes() == src
    assert not (folder / ("resdll.dll" + r.BACKUP_SUFFIX)).exists()


@pytest.mark.parametrize("broken", ["hash", "template"])
def test_main_unexpected_result(game, monkeypatch, capsys, broken):
    folder, src = game
    if broken == "hash":
        monkeypatch.setattr(r, "RESULT", "0" * 64)
    else:
        monkeypatch.setattr(r, "restore", lambda pe: None)
    with pytest.raises(SystemExit) as e:
        run_main(monkeypatch, folder)
    assert e.value.code == 1
    assert "unexpected result" in capsys.readouterr().out
    assert (folder / "resdll.dll").read_bytes() == src


def test_main_missing_file(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="RESDLL.dll: missing"):
        run_main(monkeypatch, tmp_path)


def test_main_usage(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["a2resdll.py"])
    with pytest.raises(SystemExit, match="a2resdll.py <game folder>"):
        runpy.run_path(r.__file__, run_name="__main__")

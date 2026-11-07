"""a2resdll.py on synthetic dialog templates."""

import struct

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

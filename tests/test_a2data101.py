"""a2data101.py and a2movelist.py: event texts, LAENDER.SAV and MoveList.dat."""

import struct
import sys

import pytest

import a2data101 as d
import a2movelist


def encrypt(plain):
    """The event file format: length, count, then each byte XOR the previous encrypted byte."""
    key, out = len(plain) & 0xFF, bytearray()
    for b in plain:
        key ^= b
        out.append(key)
    return struct.pack("<ii", len(plain), plain.count(b"\0")) + bytes(out)


def events(last=b":"):
    texts = [f"Text {i}".encode() for i in range(60)]
    for i in d.EVENT_TEXTS:
        texts[i] += last
    return encrypt(b"\0".join(texts) + b"\0") + b"trailer"


def test_events_101_changes_only_the_two_texts():
    result = d.events_101(events())
    assert result == events(last=b".")
    assert result.endswith(b"trailer")


def test_events_101_unexpected_text():
    assert d.events_101(events(last=b"!")) is None


def test_laender_101():
    data = bytes(d.LAENDER_AT) + bytes([d.LAENDER_OLD]) + b"rest"
    result = d.laender_101(data)
    assert result[d.LAENDER_AT] == d.LAENDER_NEW and len(result) == len(data)
    assert d.laender_101(result) is None
    assert d.laender_101(b"short") is None


def test_movelist_matches_its_hash():
    data = a2movelist.build()
    assert d.sha(data) == d.MOVELIST
    assert struct.unpack_from("<H", data, 0)[0] == len(a2movelist.PATH)


def test_homography_maps_the_corners():
    corners = ((0, 0), (16 * 100, 0), (16 * 100, 16 * 30), (0, 16 * 30))
    a, b, c, e, f, g, h, i = a2movelist.homography(corners)
    for (x, y), (u, v) in zip(((0, 0), (100, 30)), ((-0.5, -0.5), (127.5, 31.5))):
        den = h * x + i * y + 1
        assert (a * x + b * y + c) / den == pytest.approx(u)
        assert (e * x + f * y + g) / den == pytest.approx(v)


def test_frame_without_sign_is_empty():
    assert a2movelist.frame(3, 2, None) == [0] * 6


def test_game_path_keeps_the_case(tmp_path):
    (tmp_path / "texte").mkdir()
    assert d.game_path(str(tmp_path), "TEXTE/EreigGld.saq") == str(tmp_path / "texte" / "EreigGld.saq")


def game_with_laender(tmp_path):
    data = bytes(d.LAENDER_AT) + bytes([d.LAENDER_OLD])
    for folder in ("data.def", "DATA.VER"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "laender.sav").write_bytes(data)
    return data, (d.sha(data), d.sha(d.laender_101(data)))


RELS = ["DATA.DEF/LAENDER.SAV", "DATA.VER/LAENDER.SAV"]


def test_change_writes_all_names_and_keeps_the_original(tmp_path, capsys):
    data, hashes = game_with_laender(tmp_path)
    assert d.change(str(tmp_path), RELS, d.laender_101, hashes, "LAENDER.SAV")
    for folder in ("data.def", "DATA.VER"):
        assert (tmp_path / folder / "laender.sav").read_bytes() == d.laender_101(data)
        assert (tmp_path / folder / ("laender.sav" + d.BACKUP_SUFFIX)).read_bytes() == data
    assert d.change(str(tmp_path), RELS, d.laender_101, hashes, "LAENDER.SAV")
    assert "already applied" in capsys.readouterr().out


def test_change_from_backup_after_a_partial_run(tmp_path):
    data, hashes = game_with_laender(tmp_path)
    d.change(str(tmp_path), RELS, d.laender_101, hashes, "x")
    (tmp_path / "DATA.VER" / "laender.sav").write_bytes(b"broken")
    assert d.change(str(tmp_path), RELS, d.laender_101, hashes, "x")
    assert (tmp_path / "DATA.VER" / "laender.sav").read_bytes() == d.laender_101(data)


def test_change_refuses_unknown_files(tmp_path, capsys):
    data, hashes = game_with_laender(tmp_path)
    assert not d.change(str(tmp_path), ["NOPE/X.SAV"], d.laender_101, hashes, "x")
    assert not d.change(str(tmp_path), RELS, d.laender_101, ("0" * 64, hashes[1]), "x")
    assert not d.change(str(tmp_path), RELS, d.laender_101, (hashes[0], "0" * 64), "x")
    assert not d.change(str(tmp_path), RELS, lambda _: None, hashes, "x")
    assert (tmp_path / "DATA.VER" / "laender.sav").read_bytes() == data
    assert "missing" in capsys.readouterr().out


def test_main_without_game_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["a2data101.py", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        d.main()
    assert e.value.code == 1
    movelist = tmp_path / "ARCHIVES" / "MoveList.dat"
    assert d.sha(movelist.read_bytes()) == d.MOVELIST
    with pytest.raises(SystemExit):
        d.main()
    assert "MoveList.dat already there" in capsys.readouterr().out


def test_main_usage(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["a2data101.py"])
    with pytest.raises(SystemExit, match="a2data101.py <game folder>"):
        d.main()

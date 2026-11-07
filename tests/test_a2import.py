"""a2import.py: case-insensitive merge of data sets and save games."""

import sys
import zipfile

import pytest

import a2import as imp


def tree(root, files):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_match(tmp_path):
    (tmp_path / "DATA.DEF").mkdir()
    assert imp.match(str(tmp_path), "data.def") == "DATA.DEF"
    assert imp.match(str(tmp_path), "new") == "new"
    assert imp.match(str(tmp_path / "missing"), "x") == "x"


def test_merge_keeps_or_overwrites(tmp_path):
    src, game = tmp_path / "src", tmp_path / "game"
    tree(src, {"data.def/a.sav": "new", "data.def/b.sav": "new"})
    tree(game, {"DATA.DEF/A.SAV": "old"})
    counts = {"added": 0, "replaced": 0, "kept": 0}
    imp.merge(str(src), str(game), False, counts)
    assert counts == {"added": 1, "replaced": 0, "kept": 1}
    assert (game / "DATA.DEF" / "A.SAV").read_text() == "old"
    assert (game / "DATA.DEF" / "b.sav").read_text() == "new"
    counts = {"added": 0, "replaced": 0, "kept": 0}
    imp.merge(str(src), str(game), True, counts)
    assert counts == {"added": 0, "replaced": 2, "kept": 0}
    assert (game / "DATA.DEF" / "A.SAV").read_text() == "new"
    assert sorted(p.name for p in game.iterdir()) == ["DATA.DEF"]


def test_unwrap(tmp_path):
    src, game = tmp_path / "src", tmp_path / "game"
    tree(src, {"Spielstaende/1.sav": "x", "__MACOSX/._1.sav": "x"})
    game.mkdir()
    assert imp.unwrap(str(src), str(game)) == str(src / "Spielstaende")
    (game / "spielstaende").mkdir()
    assert imp.unwrap(str(src), str(game)) == str(src)


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["a2import.py", *map(str, args)])
    imp.main()


def test_main_zip(tmp_path, monkeypatch, capsys):
    archive, game = tmp_path / "set.zip", tmp_path / "game"
    game.mkdir()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Datensatz/DATA.DEF/X.SAV", "x")
    run_main(monkeypatch, "zip", game, archive)
    assert (game / "DATA.DEF" / "X.SAV").read_text() == "x"
    assert "1 added" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["../evil.sav", "/evil.sav", "a\\..\\evil.sav"])
def test_main_zip_rejects_unsafe_paths(tmp_path, monkeypatch, name):
    archive, game = tmp_path / "set.zip", tmp_path / "game"
    game.mkdir()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(name, "x")
    with pytest.raises(SystemExit, match="unsafe path"):
        run_main(monkeypatch, "zip", game, archive)


def test_main_dir_and_none(tmp_path, monkeypatch):
    src, game = tmp_path / "src", tmp_path / "game"
    tree(src, {"a.sav": "x"})
    game.mkdir()
    run_main(monkeypatch, "none", game)
    assert not (game / "a.sav").exists()
    run_main(monkeypatch, "dir", game, src)
    assert (game / "a.sav").exists()


def test_main_cancelled(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(imp, "pick", lambda mode, title: "")
    run_main(monkeypatch, "zip", tmp_path)
    assert "Import skipped" in capsys.readouterr().out


class Result:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_zenity_cleans_the_environment(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen.update(args=args, env=kw["env"])
        return Result(0, "/some/file.zip\n")

    monkeypatch.setattr(imp.subprocess, "run", fake_run)
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "GSETTINGS_SCHEMA_DIR", "GSFIX_TITLE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("HOME_TEST_KEEP", "1")
    assert imp.pick("zip", "Titel") == "/some/file.zip"
    assert seen["args"][:4] == ["zenity", "--file-selection", "--title", "Titel"]
    assert "--file-filter" in seen["args"]
    assert seen["env"].get("HOME_TEST_KEEP") == "1"
    assert not {"LD_LIBRARY_PATH", "LD_PRELOAD", "GSETTINGS_SCHEMA_DIR", "GSFIX_TITLE"} & set(seen["env"])


def test_zenity_cancel_and_failure(monkeypatch):
    monkeypatch.setattr(imp.subprocess, "run", lambda *a, **k: Result(1))
    assert imp.pick("dir", "x") == ""
    monkeypatch.setattr(imp.subprocess, "run", lambda *a, **k: Result(1, stderr="error while loading shared libs"))
    with pytest.raises(SystemExit, match="zenity failed"):
        imp.zenity([])

    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(imp.subprocess, "run", missing)
    with pytest.raises(SystemExit, match="zenity is missing"):
        imp.zenity([])

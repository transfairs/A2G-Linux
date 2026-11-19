"""a2movelist.py: the command line (the table itself is tested in test_a2data101.py)."""

import runpy
import sys

import pytest

import a2movelist


def test_main_writes_the_file(tmp_path, monkeypatch):
    out = tmp_path / "MoveList.dat"
    monkeypatch.setattr(sys, "argv", ["a2movelist.py", str(out)])
    a2movelist.main()
    assert out.read_bytes() == a2movelist.build()


@pytest.mark.parametrize("argv", [[], ["a", "b"]])
def test_main_needs_exactly_one_argument(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["a2movelist.py"] + argv)
    with pytest.raises(SystemExit) as e:
        a2movelist.main()
    assert e.value.code == "a2movelist.py <output file>"


def test_runs_as_a_script(tmp_path, monkeypatch):
    out = tmp_path / "MoveList.dat"
    monkeypatch.setattr(sys, "argv", ["a2movelist.py", str(out)])
    runpy.run_path(a2movelist.__file__, run_name="__main__")
    assert out.read_bytes() == a2movelist.build()

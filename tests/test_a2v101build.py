"""a2v101build.py: the prebuilt src/a2v101.json against a fresh build of src/a2v101.S."""

import json
import runpy
import shutil
import struct
import sys

import pytest

import a2patch as p
import a2v101build as b

needs_binutils = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("as", "ld", "objcopy", "nm")), reason="GNU binutils missing"
)


def prebuilt():
    with open(b.OUTPUT) as f:
        return json.load(f)


def test_relocate_moves_only_the_listed_places():
    data = prebuilt()
    code, symbols = b.relocate(data, data["base"])
    assert code == bytes.fromhex("".join(data["code"]))
    assert symbols["fix_412dd0"] == data["base"] + data["symbols"]["fix_412dd0"]
    moved, _ = b.relocate(data, data["base"] + 0x1000)
    changed = {i for i in range(len(code)) if code[i] != moved[i]}
    assert changed <= {at + k for at in data["absolute"] + data["relative"] for k in range(4)}


def test_every_hook_has_its_symbol():
    names = prebuilt()["symbols"]
    assert all(symbol in names for _, _, symbol, _ in p.V101_HOOKS if symbol)


@needs_binutils
def test_prebuilt_is_up_to_date():
    assert b.dumps(b.build()) == open(b.OUTPUT).read()


@needs_binutils
@pytest.mark.parametrize("address", [0x401000 + 0x8CA000, 0x7FFF0000])
def test_relocate_matches_as_and_ld(address):
    assert b.relocate(prebuilt(), address) == b.assemble(b.SOURCE, address)


# --- build and main on a small synthetic source ------------------------------------------------

TINY = """\
.text
.globl _start
_start:
    movl $data, %eax
    call 0x401000
other:
    ret
data:
    .long _start
"""


@pytest.fixture
def tiny(tmp_path):
    source = tmp_path / "tiny.S"
    source.write_text(TINY)
    return str(source)


@needs_binutils
def test_build_finds_absolute_and_relative_places(tiny):
    data = b.build(tiny)
    code = bytes.fromhex("".join(data["code"]))
    assert data["base"] == b.BASE and len(code) == 15
    assert data["absolute"] == [1, 11]  # movl $data / .long _start
    assert data["relative"] == [6]  # call into the game
    assert data["symbols"].items() >= {"_start": 0, "other": 10, "data": 11}.items()  # plus ld's own (_end, ...)
    assert b.relocate(data, 0x500000) == b.assemble(tiny, 0x500000)


def test_assemble_needs_binutils(monkeypatch):
    monkeypatch.setattr(b.shutil, "which", lambda tool: None if tool == "nm" else "/usr/bin/" + tool)
    with pytest.raises(SystemExit, match="nm .GNU binutils. is missing"):
        b.assemble("unused.S", b.BASE)


def test_build_code_that_changes_its_size(monkeypatch):
    monkeypatch.setattr(b, "assemble", lambda source, address: (bytes(4 if address == b.BASE else 8), {}))
    with pytest.raises(SystemExit, match="changes its size or layout"):
        b.build("unused.S")


def test_build_code_that_moves_its_symbols(monkeypatch):
    monkeypatch.setattr(b, "assemble", lambda source, address: (bytes(4), {"f": address + (address - b.BASE)}))
    with pytest.raises(SystemExit, match="changes its size or layout"):
        b.build("unused.S")


def test_build_code_that_relocates_differently(monkeypatch):
    def assemble(source, address):
        # moves with the address at BASE and BASE + DELTA only, so the third address shows it
        value = address if address in (b.BASE, b.BASE + b.DELTA) else 0
        return struct.pack("<I", value), {"_start": address}

    monkeypatch.setattr(b, "assemble", assemble)
    with pytest.raises(SystemExit, match="relocating the code does not give"):
        b.build("unused.S")


@pytest.fixture
def output(tmp_path, monkeypatch, tiny):
    path = tmp_path / "a2v101.json"
    monkeypatch.setattr(b, "OUTPUT", str(path))
    build = b.build
    monkeypatch.setattr(b, "build", lambda: build(tiny))
    return path


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["a2v101build.py", *args])
    b.main()


@needs_binutils
def test_main_writes_and_checks(output, tiny, monkeypatch, capsys):
    run_main(monkeypatch)
    assert output.read_text() == b.dumps(b.build())
    assert json.loads(output.read_text())["relative"] == [6]
    assert "written" in capsys.readouterr().out
    run_main(monkeypatch, "--check")
    assert "is up to date" in capsys.readouterr().out
    output.write_text("{}\n")
    with pytest.raises(SystemExit, match="is out of date"):
        run_main(monkeypatch, "--check")
    assert output.read_text() == "{}\n"


def test_main_usage(output, monkeypatch):
    with pytest.raises(SystemExit) as e:
        run_main(monkeypatch, "--bogus")
    assert e.value.code == b.__doc__ and not output.exists()


def test_runs_as_a_script(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["a2v101build.py", "--bogus"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(b.__file__, run_name="__main__")
    assert e.value.code == b.__doc__

"""a2v101build.py: the prebuilt src/a2v101.json against a fresh build of src/a2v101.S."""

import json
import shutil

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

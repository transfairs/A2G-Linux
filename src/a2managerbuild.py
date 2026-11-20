#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Takes the code of A2G-Patch's manager events from its ManagerCode.cs into src/a2manager.json.

    a2managerbuild.py [--check] <path to A2G-Patch's ManagerCode.cs>

A2G-Patch (https://github.com/transfairs/A2G-Patcher, GPLv3) assembles tools/manager_events.asm with
MASM into ManagerCode.cs: the six cases of the manager's private life that have no working code in the
game. a2patch.py --manager links that code into three functions of the game nothing refers to, as
A2G-Patch's ManagerEvents.Link does. Since MASM doesn't run here, the assembled code is taken from
ManagerCode.cs as it is and stored as JSON:

- "blocks":  MAIN, ASKS (the questions), KEYS, TABS, hex, with their fields zeroed
- "fields":  per block, [offset, 1 for a distance or 0 for an address, target, addend]; the target is a
             block, or the number of blocks plus one of "symbols"
- "symbols": the game's symbols, then the numbers of the three questions
- "cases", "entries": the cases the patch takes over and where their code starts (block, offset)
- "builds":  the builds of the game it knows, with the switch, its jump table, the question table, the
             import table entry of GetAsyncKeyState, the cases' original targets, the three functions
             (address and original bytes, hex) and the addresses of the game's symbols

Run it after A2G-Patch changed ManagerCode.cs; --check only compares src/a2manager.json with it (exit code
1 if it differs).
"""

import base64
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, "a2manager.json")
BUILD_NAMES = ("1999", "gog", "2007")  # the order of ManagerCode.Builds


def base64_list(text):
    """The byte strings of the Convert.FromBase64String(...) calls in text, in order."""
    calls = re.findall(r"Convert\.FromBase64String\((.*?)\)", text, re.S)
    return [base64.b64decode("".join(re.findall(r'"([^"]*)"', call))) for call in calls]


def numbers(text):
    """The integers (0x.., -0x.., decimal) in text, in order."""
    return [int(n, 0) for n in re.findall(r"-?(?:0x[0-9A-Fa-f]+|\d+)", text)]


def between(text, start, end):
    """The text from behind start up to the next end."""
    at = text.index(start) + len(start)
    return text[at : text.index(end, at)]


def parse(source):
    """The data of ManagerCode.cs as stored in src/a2manager.json."""
    blocks = base64_list(between(source, "byte[][] Blocks =", "};"))
    fields = [numbers(row) for row in re.findall(r"new\[\] \{([^}]*)\}", between(source, "int[][] Fields =", "};"))]
    builds = {}
    parts = between(source, "ManagerBuild[] Builds =", "\n        };").split("new ManagerBuild")[1:]
    if len(parts) != len(BUILD_NAMES):
        sys.exit(f"ManagerCode.cs has {len(parts)} builds, expected {len(BUILD_NAMES)}")
    for name, part in zip(BUILD_NAMES, parts):
        builds[name] = {
            "switch": int(re.search(r"Switch = (\w+)", part)[1], 0),
            "table": int(re.search(r"Table = (\w+)", part)[1], 0),
            "questions": int(re.search(r"Questions = (\w+)", part)[1], 0),
            "keystate": int(re.search(r"KeyState = (\w+)", part)[1], 0),
            "cases": numbers(between(part, "Cases = new uint[] {", "}")),
            "regions": numbers(between(part, "Regions = new uint[] {", "}")),
            "originals": [b.hex() for b in base64_list(part)],
            "symbols": numbers(between(part, "Symbols = new uint[] {", "}")),
        }
    return {
        "blocks": [b.hex() for b in blocks],
        "fields": [[row[i : i + 4] for i in range(0, len(row), 4)] for row in fields],
        "symbols": re.findall(r'"(\w+)"', between(source, "string[] Symbols =", ";")),
        "cases": numbers(between(source, "int[] Cases =", ";")),
        "entries": [numbers(e) for e in re.findall(r"new\[\] \{([^}]*)\}", between(source, "int[][] Entries =", ";"))],
        "builds": builds,
    }


def dump(data):
    """data as the text of src/a2manager.json: one line per key, and per build in "builds"."""
    lines = [f" {json.dumps(k)}: {json.dumps(v)}" for k, v in data.items() if k != "builds"]
    builds = [f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in data["builds"].items()]
    return "{\n" + ",\n".join(lines + [' "builds": {\n' + ",\n".join(builds) + "\n }"]) + "\n}\n"


def main():
    """Writes src/a2manager.json from ManagerCode.cs, or with --check compares the two."""
    args = sys.argv[1:]
    check = "--check" in args
    paths = [a for a in args if a != "--check"]
    if len(paths) != 1:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    with open(paths[0], encoding="utf-8") as f:
        text = dump(parse(f.read()))
    if check:
        with open(OUTPUT, encoding="utf-8") as f:
            if f.read() != text:
                sys.exit("src/a2manager.json differs from ManagerCode.cs, run src/a2managerbuild.py")
        print("src/a2manager.json is up to date")
        return
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()

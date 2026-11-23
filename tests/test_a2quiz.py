"""a2quiz.py on synthetic quiz files: every question the switches change, spread over the three levels."""

import runpy
import struct
import sys

import pytest

import a2quiz as q


def questions(on=False):
    """Every question the answers switch changes, as the game has it (on False) or as changed, in the levels 0,
    1, 2 in turn, and one more question in each level that stays."""
    found = [[i % 3, *(c.to if on else c.frm)] for i, c in enumerate(q.ANSWERS)]
    return found + [[level, f"Frage {level}", "richtig,falsch,falsch,falsch"] for level in range(3)]


def game(tmp_path, data=None):
    (tmp_path / "TEXTE").mkdir()
    (tmp_path / "TEXTE" / "fort.saq").write_bytes(q.write(questions()) if data is None else data)
    return tmp_path


def quiz(folder):
    return (folder / "TEXTE" / "fort.saq").read_bytes()


# --- the file ---------------------------------------------------------------------------------------------


def test_file_reads_and_writes_back_to_the_byte():
    data = q.write(questions())
    counts = struct.unpack_from("<5I", data)
    assert counts[:3] == (27, 27, 26) and counts[3] == 2 * 80 and counts[4] == len(data) - 20 - 4 * 160
    # the block inverted, the texts one behind the other, each ended by a NUL
    first = bytes(b ^ 0xFF for b in data[20 + 4 * 160 :]).split(b"\0")[0]
    assert first == q.ANSWERS[0].frm[0].encode("cp1252") and struct.unpack_from("<I", data, 20)[0] == 0
    assert q.read(data) == sorted(questions(), key=lambda x: x[0])
    assert q.write(q.read(data)) == data


@pytest.mark.parametrize(
    "spoil",
    [
        lambda d: None,
        lambda d: d[:19],
        lambda d: d[:-1],  # the block shorter than the header says
        lambda d: d[:12] + struct.pack("<I", 4) + d[16:],  # two texts per question
        lambda d: d[:-1] + b"\0",  # the last text not ended
        lambda d: d[:-2] + b"\xff" + d[-1:],  # one text more than the header says
        lambda d: d[:24] + struct.pack("<I", 1) + d[28:],  # the second text not behind the first
    ],
)
def test_file_is_not_read_when_it_does_not_hold_what_its_header_says(spoil):
    assert q.read(spoil(q.write(questions()))) is None


# --- the switches -----------------------------------------------------------------------------------------


def test_changes_keep_four_answers_and_fit_the_games_buffer():
    """The game takes the first answer as the right one and two of the next three; it copies the answers into
    a buffer of 500 bytes."""
    for change in q.ANSWERS + q.NEW:
        assert len(change.to[1].split(",")) >= 4 and len(change.to[1].encode("cp1252")) < 500, change.to[0]
        assert change.frm != change.to
    assert len(q.ANSWERS) == 77 and len(q.NEW) == 150
    assert all(c.frm is None and len(c.to[1].split(",")) == 4 for c in q.NEW)
    assert [sum(c.level == level for c in q.NEW) for level in range(3)] == [46, 59, 45]
    # each question as the game has it and as changed, and each new one, is found only once
    texts = [t for c in q.ANSWERS for t in (c.frm, c.to)] + [c.to for c in q.NEW]
    assert len(set(texts)) == len(texts)
    assert len({c.to[0] for c in q.NEW}) == len(q.NEW)


def test_state_follows_the_questions():
    answers, new = q.PATCHES
    assert [q.state(p, questions()) for p in q.PATCHES] == ["off", "off"]
    assert q.state(answers, questions(on=True)) == "on"
    assert q.state(answers, questions()[1:]) is None  # a question missing: not the game's quiz
    half = questions()
    half[0][1:] = q.ANSWERS[0].to
    assert q.state(answers, half) is None
    assert q.state(answers, None) is None
    some = questions() + [[0, *q.NEW[0].to]]
    assert q.state(new, some) is None and q.state(new, some + [[c.level, *c.to] for c in q.NEW[1:]]) == "on"


def test_switch_changes_the_questions_and_back_to_the_byte():
    answers = q.PATCHES[0]
    original = q.write(questions())
    found = q.read(original)
    assert q.switch(answers, found, True) and not q.switch(answers, found, True)
    assert q.write(found) == q.write(questions(on=True))
    assert q.switch(answers, found, False) and q.write(found) == original


def test_new_questions_go_to_the_end_of_their_level_and_away_again():
    new = q.PATCHES[1]
    original = q.write(questions())
    found = q.read(original)
    q.switch(new, found, True)
    for level in range(3):
        mine = [tuple(x[1:]) for x in found if x[0] == level]
        theirs = [c.to for c in q.NEW if c.level == level]
        assert mine[-len(theirs) - 1 :] == [(f"Frage {level}", "richtig,falsch,falsch,falsch")] + theirs
    data = q.write(found)
    assert q.state(new, q.read(data)) == "on"
    found = q.read(data)
    q.switch(new, found, False)
    assert q.write(found) == original


def test_both_switches_change_the_file_independently():
    answers, new = q.PATCHES
    one, other = q.read(q.write(questions())), q.read(q.write(questions()))
    q.switch(answers, one, True)
    q.switch(new, one, True)
    q.switch(new, other, True)
    q.switch(answers, other, True)
    assert q.write(one) == q.write(other)
    q.switch(new, one, False)
    assert q.write(one) == q.write(questions(on=True))


# --- command line -----------------------------------------------------------------------------------------


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["a2quiz.py", *map(str, args)])
    q.main()


def test_main_sets_the_switches(tmp_path, monkeypatch, capsys):
    folder = game(tmp_path)
    original = quiz(folder)
    run_main(monkeypatch, "both", folder)
    assert capsys.readouterr().out == "Quizfragen: on\nNeue Quizfragen: on\n"
    run_main(monkeypatch, "status", folder)
    assert capsys.readouterr().out == "Quizfragen: on\nNeue Quizfragen: on\n"
    run_main(monkeypatch, "new", folder)
    assert capsys.readouterr().out == "Quizfragen: off\nNeue Quizfragen: already on\n"
    run_main(monkeypatch, "answers", folder)
    assert capsys.readouterr().out == "Quizfragen: on\nNeue Quizfragen: off\n"
    run_main(monkeypatch, "original", folder)
    assert capsys.readouterr().out == "Quizfragen: off\nNeue Quizfragen: already off\n"
    assert quiz(folder) == original


def test_main_writes_nothing_when_nothing_changes(tmp_path, monkeypatch, capsys):
    folder = game(tmp_path)
    monkeypatch.setattr(q, "write", None)
    run_main(monkeypatch, "original", folder)
    assert capsys.readouterr().out == "Quizfragen: already off\nNeue Quizfragen: already off\n"


def test_main_leaves_another_quiz_alone(tmp_path, monkeypatch, capsys):
    other = q.write(questions()[1:])
    folder = game(tmp_path, other)
    run_main(monkeypatch, "both", folder)
    assert capsys.readouterr().out == (
        "Quizfragen: TEXTE/fort.saq doesn't hold the game's questions, left unchanged\nNeue Quizfragen: on\n"
    )
    run_main(monkeypatch, "original", folder)
    assert capsys.readouterr().out.endswith("Neue Quizfragen: off\n")
    assert quiz(folder) == other
    (folder / "TEXTE" / "fort.saq").write_bytes(b"kein Quiz")
    run_main(monkeypatch, "status", folder)
    assert capsys.readouterr().out.count("doesn't hold the game's questions") == 2


def test_main_without_quiz(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="no TEXTE/fort.saq"):
        run_main(monkeypatch, "both", tmp_path)


def test_main_usage(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["a2quiz.py", "x"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(q.__file__, run_name="__main__")
    assert e.value.code == 2

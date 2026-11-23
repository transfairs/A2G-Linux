#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Brings the manager course quiz of Anstoss 2 Gold up to date and adds new questions (TEXTE/fort.saq).

    a2quiz.py original|answers|both|new|status <game folder>

A port of A2G-Patch's quiz switches (QuizPatches.cs, QuizQuestions.cs), with the same questions, the same
order and the same bytes, so A2G-Patch recognizes the result and can take it back. They need no code of the
exe and work the same for every release (1999 CD, GOG, 2007 CD):

"Quizfragen"       answers  77 of the 633 questions on the state of November 2026: titles, records and rules
                            of today, people in office, four answers that were wrong already in 1998 (the
                            UEFA's seat, Rangers' colours, a city without two Bundesliga clubs, the last
                            double); questions about a time that is over name their year. The questions keep
                            their place and level.
"Neue Quizfragen"  new      150 more questions, 46, 59 and 45 at the end of the three levels, from the World
                            Cup 1998 to the World Cup 2026.

The first argument sets the quiz as a whole: "original" both switches off, "answers" or "new" one of them,
"both" both; "status" only shows them. With both off the file is the original to the byte; no backup is
written.

The file holds the number of questions of each of the three levels, the number of texts (two per question)
and the length of the text block (all 32 bit), a table of where each text starts in the block, then the
block: each question followed by its answers, separated by commas, the right one first, each text ended by
a NUL, every byte inverted. The game reads the counts and sizes from the header and makes room for them,
so texts may change length.

A switch is applied only if the file holds every question it changes, either as the game has it or as
changed; otherwise (a quiz that isn't the game's, e.g. from a data set) it is left out with a message, and
the exit status stays 0, so the installer goes on. Exit status 1 if the game folder has no quiz file.
"""

import argparse
import os
import struct
import sys
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from a2texts import GameFiles, ansi_decode, ansi_encode  # noqa: E402

QUIZ_FILE = "TEXTE/fort.saq"
LEVELS = 3
HEADER = struct.Struct("<5I")  # the questions of each level, the texts, the length of the block


# --- the file ---------------------------------------------------------------------------------------------


def read(data):
    """The questions of the quiz file data, in their order, as [level, question, answers]; None if it isn't
    one."""
    if data is None or len(data) < HEADER.size:
        return None
    counts = HEADER.unpack_from(data)
    texts, block = counts[LEVELS], counts[LEVELS + 1]
    table_end = HEADER.size + 4 * texts
    if texts != 2 * sum(counts[:LEVELS]) or table_end + block != len(data):
        return None
    plain = ansi_decode(bytes(b ^ 0xFF for b in data[table_end:]))
    parts = plain.split("\0")
    if len(parts) != texts + 1 or parts[-1]:
        return None
    # each text starts right behind the one before it
    at = 0
    for i, text in enumerate(parts[:-1]):
        if struct.unpack_from("<I", data, HEADER.size + 4 * i)[0] != at:
            return None
        at += len(ansi_encode(text)) + 1
    questions, nxt = [], 0
    for level in range(LEVELS):
        for _ in range(counts[level]):
            questions.append([level, parts[nxt], parts[nxt + 1]])
            nxt += 2
    return questions


def write(questions):
    """The quiz file holding questions, each level's in their order."""
    ordered = sorted(questions, key=lambda q: q[0])  # stable: the order within a level stays
    table, block = bytearray(), bytearray()
    for _, question, answers in ordered:
        for text in (question, answers):
            table += struct.pack("<I", len(block))
            block += ansi_encode(text) + b"\0"
    counts = [sum(q[0] == level for q in ordered) for level in range(LEVELS)]
    header = HEADER.pack(*counts, 2 * len(ordered), len(block))
    return header + bytes(table) + bytes(b ^ 0xFF for b in block)


# --- changes ----------------------------------------------------------------------------------------------

# One question as the game has it (frm, None for one the patch adds) and as the patch makes it (to), each
# (question, answers); level: for a question the patch adds, the level at whose end it goes.
Change = namedtuple("Change", "frm to level")


def answers(question, frm, to):
    """The question with other answers."""
    return Change((question, frm), (question, to), 0)


def question(frm, to, answers):
    """The question rephrased; its answers stay."""
    return Change((frm, answers), (to, answers), 0)


def both(frm_question, frm_answers, to_question, to_answers):
    """The question rephrased, with other answers."""
    return Change((frm_question, frm_answers), (to_question, to_answers), 0)


def new(level, question, answers):
    """A question the patch adds to the end of level (0 to 2)."""
    return Change(None, (question, answers), level)


def find(questions, text):
    """The question of questions that reads as text (question, answers); None if none."""
    return next((q for q in questions if (q[1], q[2]) == text), None)


def is_in(change, questions, on):
    """Whether questions are as the game has them (on False) or as changed, as far as change goes."""
    if change.frm is None and not on:
        return find(questions, change.to) is None
    return find(questions, change.to if on else change.frm) is not None


def make(change, questions, on):
    """Makes change in questions (on) or takes it back; they are the other way round."""
    if change.frm is None and on:
        questions.append([change.level, *change.to])
    elif change.frm is None:
        questions.remove(find(questions, change.to))
    else:
        found = find(questions, change.frm if on else change.to)
        found[1:] = change.to if on else change.frm


# --- the switches (A2G-Patch's QuizPatches.cs and QuizQuestions.cs) ----------------------------------------

# fmt: off
ANSWERS = (
    # Rules: the ball touching the referee, the goalkeeper's steps, coin tosses, kick-off and goal kick in play
    # once kicked.
    both(
        ("Ein Spieler schießt eine Ecke, die vom Schiedsrichter (aus Versehen) unhaltbar für den Torwart ins Tor "
         "geköpft wird. Entscheidung?"),
        "Tor,Profivertrag,Abstoß,Wiederholung der Ecke",
        ("Ein Spieler schießt eine Ecke, die vom Schiedsrichter (aus Versehen) unhaltbar für den Torwart ins Tor "
         "geköpft wird. Entscheidung (Stand November 2026)?"),
        "Schiedsrichterball,Tor,Profivertrag,Wiederholung der Ecke",
    ),
    question(
        "Wie heißt das größte Fußballstadion der Welt?",
        "Welches Stadion war bei seiner Eröffnung 1950 das größte Fußballstadion der Welt?",
        "Maracana,Ibrox Park,Zentralstadion,Estadio Kolumbia",
    ),
    both(
        "Nach Abschluß einer Saison steigen aus der 1. Bundesliga in Deutschland wie viele Mannschaften ab?",
        "3,1,keine,2",
        "Wie viele Mannschaften stiegen im November 2026 nach einer Saison direkt aus der 1. Bundesliga ab?",
        "2 (der 16. muß in die Relegation),3,1,keine",
    ),
    both(
        "Wie lautet der Stadionname von Schalke 04?",
        "Parkstadion,Gartenstadion,Ruhrpottstadion,Königsblaustadion",
        "Wie hieß das Stadion von Schalke 04 im November 2026?",
        "Veltins-Arena,Parkstadion,Ruhrpottstadion,Königsblaustadion",
    ),
    both(
        "In welcher Stadt steht das größte deutsche Stadion?",
        "Leipzig,Berlin,München,Düsseldorf",
        "In welcher Stadt stand im November 2026 das größte deutsche Stadion?",
        "Dortmund,Leipzig,Berlin,München",
    ),
    both(
        "Wie heißt der amtierende Präsident des Deutschen Fußballbundes?",
        "Egidius Braun,Gerhard Mayer-Vorfelder,Horst Hilpert,Franz Beckenbauer",
        "Wer war im November 2026 Präsident des Deutschen Fußballbundes?",
        "Bernd Neuendorf,Fritz Keller,Reinhard Grindel,Franz Beckenbauer",
    ),
    question(
        "Helmut Kohl und Rudolf Scharping sind Fans welcher Mannschaft?",
        "Helmut Kohl und Rudolf Scharping galten als Fans welcher Mannschaft?",
        "1.FC Kaiserslautern,Bayern München,Waldhof Mannheim,1.FC Saarbrücken",
    ),
    question(
        "Wie wird das finale Hallenturnier in der Winterpause bezeichnet?",
        "Wie hieß bis 2001 das finale Hallenturnier in der Winterpause?",
        "Hallen-Masters,Grand Slam Cup,Golden Four,Challenger Cup",
    ),
    both(
        "Wie heißt der Manager von Bayern München?",
        "Uli Hoeneß,Felix Magath,Rainer Calmund,Willi Lemke",
        "Wer war im November 2026 Sportvorstand von Bayern München?",
        "Max Eberl,Uli Hoeneß,Rainer Calmund,Rudi Völler",
    ),
    question(
        "Welcher aktuelle Bundesligaspieler trägt den Beinamen \"Tiger\"?",
        "Welcher Bundesligaspieler trug den Beinamen \"Tiger\"?",
        "Stefan Effenberg,Karl-Heinz Riedle,Bruno Labbadia,Fredi Bobic",
    ),
    both(
        "Welcher Spieler hält mit 40 Toren in einer Saison den BL-Rekord?",
        "Gerd Müller,Klaus Allofs,Jupp Heynckes,K.-H. Rummenigge",
        "Welcher Spieler hielt im November 2026 mit 41 Toren in einer Saison den BL-Rekord?",
        "Robert Lewandowski,Gerd Müller,Harry Kane,K.-H. Rummenigge",
    ),
    both(
        "Wie oft war Bayern München Deutscher Meister?",
        "14mal,Kann mich nicht erinnern.,Muß Jahre her sein.,Ist mir doch egal.",
        "Wie oft war Bayern München bis November 2026 Deutscher Meister?",
        "35mal,Kann mich nicht erinnern.,Muß Jahre her sein.,Ist mir doch egal.",
    ),
    both(
        "Wie viele Schritte darf ein Torwart mit dem Ball in der Hand machen?",
        "vier,keinen,fünf,unbegrenzt",
        "Wie viele Schritte darf ein Torwart mit dem Ball in der Hand machen (Stand November 2026)?",
        "unbegrenzt,vier,keinen,fünf",
    ),
    both(
        "Der Schiedsrichter fälscht einen Schuß ab. Dieser führt zum Torerfolg. Entscheidung?",
        "reguläres Tor,kein Tor,Freistoß,Hochball",
        "Der Schiedsrichter fälscht einen Schuß ab. Dieser führt zum Torerfolg. Entscheidung (Stand November 2026)?",
        "Schiedsrichterball,reguläres Tor,Freistoß,Abstoß",
    ),
    both(
        "Wie viele Mannschaften nehmen in Zukunft an der Endrunde einer Weltmeisterschaft teil?",
        "32,24,20,16",
        "Wie viele Mannschaften nahmen 2026 an der Endrunde der Weltmeisterschaft teil?",
        "48,32,40,64",
    ),
    question(
        "Welcher dieser Herren ist kein FIFA-Schiedsrichter?",
        "Welcher dieser Herren war 1998 kein FIFA-Schiedsrichter?",
        "Michael Malbranc,Georg Dardenne,Edgar Steinborn,Bernd Heynemann",
    ),
    question(
        "Welchem Beruf geht Schiedsrichter Markus Merk im täglichen Leben nach?",
        "Welchen Beruf übte Schiedsrichter Markus Merk neben dem Pfeifen aus?",
        "Zahnarzt,Lehrer,Sopransänger,Buchmacher",
    ),
    both(
        "Welcher Spieler von Bayern München hat die meisten Europapokaleinsätze?",
        "Matthäus,Helmer,Kahn,Lizarazu",
        "Welcher Spieler hatte bis November 2026 die meisten Europapokaleinsätze für Bayern München?",
        "Müller,Matthäus,Kahn,Lahm",
    ),
    both(
        "Welche Bedeutung hat es, wenn der Spielführer die Wahl vor Beginn eines Elfmeterschießens gewinnt?",
        ("seine Mannschaft hat den ersten Schuß,die gegnerische Mannschaft hat den ersten Schuß,er bestimmt wer "
         "zuerst schießt,er darf sich ein Tor aussuchen (auf das dann geschossen wird)"),
        ("Welche Bedeutung hat es, wenn der Spielführer die Wahl vor Beginn eines Elfmeterschießens gewinnt (Stand "
         "November 2026)?"),
        ("er bestimmt wer zuerst schießt,seine Mannschaft hat den ersten Schuß,die gegnerische Mannschaft hat den "
         "ersten Schuß,er darf sich ein Tor aussuchen (auf das dann geschossen wird)"),
    ),
    both(
        "Was kann der Spielführer entscheiden, wenn er den Münzwurf zu Anfang des Spieles gewinnt?",
        ("auf welcher Seite er zunächst spielen will,ob er den Anstoß hat,auf welcher Seite die Linienrichter "
         "stehen,mit welchem Ball gespielt wird"),
        ("Was kann der Spielführer entscheiden, wenn er den Münzwurf zu Anfang des Spieles gewinnt (Stand November "
         "2026)?"),
        ("auf welcher Seite er zunächst spielen will oder ob er den Anstoß hat,nur ob er den Anstoß hat,auf welcher "
         "Seite die Linienrichter stehen,mit welchem Ball gespielt wird"),
    ),
    question(
        "Wie heißt der derzeit amtierende Chef des Ligaausschusses?",
        "Wer war 1998 Chef des Ligaausschusses?",
        "Gerhard Mayer-Vorfelder,Egidius Braun,Horst Hilpert,Franz Beckenbauer",
    ),
    both(
        "Welcher Spieler absolvierte die meisten Länderspiele für Schweden?",
        "Ravelli,Hellström,Skoglund,Hamrin",
        "Welcher Spieler absolvierte bis November 2026 die meisten Länderspiele für Schweden?",
        "Anders Svensson,Ravelli,Hellström,Hamrin",
    ),
    question(
        "Welcher Spieler wurde bisher wegen einer Schwalbe als einziger nachträglich gesperrt?",
        "Welcher Spieler wurde bis 1998 als einziger wegen einer Schwalbe nachträglich gesperrt?",
        "Andreas Möller,Thomas Häßler,Lothar Matthäus,Maurizio Gaudino",
    ),
    both(
        "Wie heißt das größte deutsche Stadion?",
        "Zentralstadion,Olympiastadion,Sportpalast,Sachsenstadion",
        "Welches war im November 2026 das größte deutsche Stadion?",
        "Westfalenstadion (Signal Iduna Park),Olympiastadion Berlin,Allianz Arena,Sachsenstadion",
    ),
    question(
        "Welcher Trainer war die längste Zeit ununterbrochen beim gleichen Bundesligaverein tätig?",
        "Welcher Trainer war bis 1998 die längste Zeit ununterbrochen beim gleichen Bundesligaverein tätig?",
        "Otto Rehhagel,Winfried Schäfer,Hennes Weisweiler,Christoph Daum",
    ),
    # Cologne had two: 1. FC Köln and Fortuna Köln in 1973/74.
    both(
        "Welche der folgenden Städte hatte noch nie zwei Erstligisten in einer Saison?",
        "Köln,Stuttgart,München,Hamburg",
        "Welche dieser Städte hatte bis November 2026 noch nie zwei Vereine in derselben Bundesligasaison?",
        "Frankfurt,Stuttgart,München,Hamburg",
    ),
    both(
        "Sepp Blatter ist der derzeit amtierende...?",
        "FIFA-Generalsekretär,FIFA-Präsident,Chef der Ideenkommission der FIFA,UEFA-Vorsitzende",
        "Welches Amt hatte Sepp Blatter, bevor er 1998 FIFA-Präsident wurde?",
        "FIFA-Generalsekretär,UEFA-Präsident,Chef der Ideenkommission der FIFA,Schweizer Nationaltrainer",
    ),
    both(
        "Wie viele Vereine spielen derzeit in der Serie A in Italien?",
        "18,20,22,16",
        "Wie viele Vereine spielten im November 2026 in der Serie A in Italien?",
        "20,18,22,16",
    ),
    both(
        "Wie oft wurde der VfB Stuttgart bislang Deutscher Meister?",
        "4mal,3mal,8mal,1mal",
        "Wie oft wurde der VfB Stuttgart bis November 2026 Deutscher Meister?",
        "5mal,4mal,3mal,8mal",
    ),
    both(
        "Wie oft wurde der VfB Stuttgart bislang Deutscher Pokalsieger?",
        "3mal,4mal,8mal,1mal",
        "Wie oft wurde der VfB Stuttgart bis November 2026 Deutscher Pokalsieger?",
        "4mal,3mal,8mal,1mal",
    ),
    both(
        "Wie oft wurde Borussia Dortmund bislang Deutscher Pokalsieger?",
        "2mal,4mal,3mal,1mal",
        "Wie oft wurde Borussia Dortmund bis November 2026 Deutscher Pokalsieger?",
        "5mal,2mal,4mal,3mal",
    ),
    both(
        "Wie oft wurde der FC Schalke 04 bislang Deutscher Pokalsieger?",
        "2mal,4mal,3mal,1mal",
        "Wie oft wurde der FC Schalke 04 bis November 2026 Deutscher Pokalsieger?",
        "5mal,2mal,4mal,3mal",
    ),
    both(
        "Welcher Spieler erzielte die meisten Tore bei Weltmeisterschaften?",
        "Müller,Maradona,Fontaine,Pele",
        "Welcher Spieler erzielte bis November 2026 die meisten Tore bei Weltmeisterschaften?",
        "Mbappé,Messi,Klose,Müller",
    ),
    question(
        "Welcher Trainer einer Bundesligamannschaft arbeitet derzeit am längsten beim gleichen Verein?",
        "Welcher Trainer einer Bundesligamannschaft arbeitete 1998 am längsten beim gleichen Verein?",
        "Winfried Schäfer,Otto Rehhagel,Erich Ribbeck,Hannes Bongartz",
    ),
    question(
        "Werder Bremen hatte in der Saison 1987/88 die wenigsten Gegentore kassiert (Bundesligarekord). Wie viele?",
        ("Werder Bremen hatte in der Saison 1987/88 die wenigsten Gegentore kassiert (damals Bundesligarekord). Wie "
         "viele?"),
        "22 Gegentreffer,12 Gegentreffer,9 Gegentreffer,28 Gegentreffer",
    ),
    answers(
        "Wie viele Vereine waren seit Beginn der Bundesliga immer dabei?",
        "zwei,fünf,drei,acht",
        "keiner,zwei,fünf,drei",
    ),
    question(
        "Welche Mannschaft der BL mußte bislang die meisten Platzverweise einstecken?",
        "Welche Mannschaft der BL mußte bis 1998 die meisten Platzverweise einstecken?",
        "1.FC Kaiserslautern,1.FC Köln,VfB Stuttgart,1.FC Nürnberg",
    ),
    question(
        "Welcher Spieler der Bundesliga ist der körperlich größte?",
        "Welcher Spieler der Bundesliga war 1998 der körperlich größte?",
        "Golz,Gehrke,Brasas,Bäron",
    ),
    question(
        "Wie viele Länder dürfen vier Mannschaften für den UEFA-Cup melden?",
        "Wie viele Länder durften 1997/98 vier Mannschaften für den UEFA-Cup melden?",
        "drei,acht,fünf,vier",
    ),
    question(
        "Welcher Verein schoß in der Saison 1971/72 101 Tore (Bundesligarekord)?",
        "Welcher Verein schoß in der Saison 1971/72 101 Tore (damals Bundesligarekord)?",
        "Bayern München,Werder Bremen,Borussia Dortmund,Hamburger SV",
    ),
    both(
        "Wie viele Jahre spielte Eintracht Braunschweig bislang in der Bundesliga?",
        "20 Jahre,10 Jahre,2 Jahre,Braunschweig? Nie.",
        "Wie viele Jahre spielte Eintracht Braunschweig bis November 2026 in der Bundesliga?",
        "21 Jahre,10 Jahre,2 Jahre,Braunschweig? Nie.",
    ),
    both(
        "Welche Mannschaft hält mit 36 Spielen in Folge ohne Niederlage den BL-Rekord?",
        "Hamburger SV,Bayern München,Borussia M'gladbach,1.FC Köln",
        "Welche Mannschaft hielt im November 2026 mit 53 Spielen in Folge ohne Niederlage den BL-Rekord?",
        "Bayern München,Hamburger SV,Bayer Leverkusen,Borussia M'gladbach",
    ),
    question(
        "In welchem Jahr erreichte die Bundesliga mit mehr als 29.000 Zuschauern pro Spiel den besten Schnitt?",
        ("In welchem Jahr erreichte die Bundesliga bis 1998 mit mehr als 29.000 Zuschauern pro Spiel den besten "
         "Schnitt?"),
        "1995/96,1964/65,1977/78,1992/93",
    ),
    both(
        "Wann gilt ein Ball nach einem Anstoß als \"im Spiel\"?",
        ("wenn er sich in Richtung des gegnerischen Spielfeldes bewegt hat,nach der Berührung durch einen Spieler,"
         "nach der zweiten Berührung durch einen Spieler,nach dem Schiripfiff"),
        "Wann gilt ein Ball nach einem Anstoß als \"im Spiel\" (Stand November 2026)?",
        ("wenn er mit dem Fuß gespielt wurde und sich eindeutig bewegt,wenn er sich in Richtung des gegnerischen "
         "Spielfeldes bewegt hat,nach der zweiten Berührung durch einen Spieler,nach dem Schiripfiff"),
    ),
    question(
        "Wieviel bekommt ein Bundesligaschiedsrichter für die Leitung einer Partie?",
        "Wieviel bekam 1998 ein Bundesligaschiedsrichter für die Leitung einer Partie?",
        "4.000 DM,72 DM,2.500 DM,1.000 DM",
    ),
    both(
        "Welcher Spieler erzielte nach Gerd Müller bislang die zweitmeisten Bundesligatore?",
        "Fischer,Heynckes,Burgsmüller,K. Allofs",
        "Welcher Spieler erzielte bis November 2026 nach Gerd Müller die zweitmeisten Bundesligatore?",
        "Lewandowski,Fischer,Heynckes,Burgsmüller",
    ),
    question(
        "Wie heißt der schwerste Spieler bei Bayern München?",
        "Wer war 1998 der schwerste Spieler bei Bayern München?",
        "Carsten Jancker,Oliver Kahn,Bernd Dreher,Dennis Grassow",
    ),
    question(
        "Wie heißt der größte Spieler von Borussia Dormund?",
        "Wer war 1998 der größte Spieler von Borussia Dortmund?",
        "Julio Cesar,Heiko Herrlich,Wolfgang de Beer,Rene Schneider",
    ),
    question(
        "Wie heißt der Präsident des FC Schalke 04?",
        "Wer war 1998 Präsident des FC Schalke 04?",
        "Gerd Rehberg,Dr. Armin Langhorst,Peter Peters,Hubert Neu",
    ),
    question(
        "Welche dieser Mannschaften war bisher nur eine Bundesligasaison nicht erstklassig?",
        "Welche dieser Mannschaften war bis 1998 nur eine Bundesligasaison nicht erstklassig?",
        "Werder Bremen,VfB Stuttgart,Eintracht Frankfurt,1.FC Köln",
    ),
    question(
        "Welcher aktiver Spieler hat derzeit die meisten Bundesligastationen hinter sich?",
        "Welcher aktive Spieler hatte 1998 die meisten Bundesligastationen hinter sich?",
        "Stefan Kohn,Mirko Votava,Claus-Dieter Wollitz,Franco Foda",
    ),
    question(
        "Wer gilt als der erfolgreichste Vereinstrainer der Welt?",
        "Wer galt 1998 als der erfolgreichste Vereinstrainer der Welt?",
        "Udo Lattek,Ernst Happel,Jupp Heynckes,Branco Zebec",
    ),
    # The UEFA moved from Bern to Nyon in 1995.
    both(
        "In welcher Stadt hat die UEFA ihren Sitz?",
        "Bern,Brüssel,Paris,London",
        "In welcher Stadt hatte die UEFA im November 2026 ihren Sitz?",
        "Nyon,Bern,Brüssel,Paris",
    ),
    # Bayern won the double in 1986 already, and last in 2026.
    both(
        "Welche Mannschaft gewann in Deutschland zuletzt Meisterschaft und Pokal in einer Saison?",
        "1.FC Köln,Hamburger SV,VfB Stuttgart,Bayern München",
        "Welche Mannschaft gewann bis November 2026 zuletzt Meisterschaft und Pokal in einer Saison?",
        "Bayern München,1.FC Köln,Hamburger SV,VfB Stuttgart",
    ),
    both(
        "Welcher Schiedsrichter leitete bislang die meisten BL-Partien?",
        "Henning,Gabor,Eschweiler,Redelfs",
        "Welcher Schiedsrichter leitete bis November 2026 die meisten BL-Partien?",
        "Brych,Stark,Henning,Eschweiler",
    ),
    both(
        "Was war der größte Erfolg Frankreichs bei einer WM?",
        "2mal Platz 3,Platz 4,Weltmeister 1962,Finale 1950",
        "Was war bis November 2026 der größte Erfolg Frankreichs bei einer WM?",
        "Weltmeister 1998 und 2018,2mal Platz 3,Weltmeister 1962,Finale 1950",
    ),
    both(
        "Ein Spieler schießt den Ball beim Torabstoß direkt ins eigene Tor. Entscheidung?",
        ("Wiederholung des Torabstoßes,Tor für die gegnerische Mannschaft,Freistoß für den Gegner,Gelbe Karte für "
         "den Spieler"),
        "Ein Spieler schießt den Ball beim Torabstoß direkt ins eigene Tor. Entscheidung (Stand November 2026)?",
        ("Eckstoß für den Gegner,Wiederholung des Torabstoßes,Tor für die gegnerische Mannschaft,Gelbe Karte für "
         "den Spieler"),
    ),
    both(
        "Welcher Torwart blieb am längsten ohne Gegentreffer (641 Minuten / Bundesligarekord)?",
        "Oliver Reck,Uli Stein,Toni Schumacher,Rüdiger Vollborn",
        "Welcher Torwart blieb am längsten ohne Gegentreffer (884 Minuten / Bundesligarekord, Stand November 2026)?",
        "Timo Hildebrand,Oliver Reck,Oliver Kahn,Manuel Neuer",
    ),
    both(
        "Welcher Spieler hat bislang die meisten Tore in der zweiten Bundesliga erzielt?",
        "Schatzschneider,Mödrath,Cestonaro,Mill",
        "Welcher Spieler hat bis November 2026 die meisten Tore in der zweiten Bundesliga erzielt?",
        "Terodde,Schatzschneider,Mödrath,Mill",
    ),
    both(
        "Welcher Spieler hat die meisten Zweitligaeinsätze in Deutschland absolviert?",
        "Montanes (Aachen),Schulz (Freiburg),Wulf (Kassel),Jurgeleit (Lübeck)",
        "Welcher Spieler hat bis November 2026 die meisten Zweitligaeinsätze in Deutschland absolviert?",
        "Landgraf (Aachen),Montanes (Aachen),Schulz (Freiburg),Wulf (Kassel)",
    ),
    both(
        "Welche Mannschaft verteidigte zuletzt den DFB-Pokal erfolgreich?",
        "Fortuna Düsseldorf,Bayern München,1.FC Köln,Borussia Dortmund",
        "Welche Mannschaft verteidigte bis November 2026 zuletzt den DFB-Pokal erfolgreich?",
        "RB Leipzig,Fortuna Düsseldorf,Bayern München,1.FC Köln",
    ),
    question(
        "Wie viele Vereine gewannen bisher alle drei Europapokalwettbewerbe?",
        "Wie viele Vereine gewannen bis 1998 alle drei Europapokalwettbewerbe?",
        "4,3,6,2",
    ),
    both(
        "Welcher Mannschaft gelang zuletzt die Verteidigung des UEFA-Pokals?",
        "Real Madrid,FC Barcelona,Ipswich Town,SSC Neapel",
        "Welcher Mannschaft gelang bis November 2026 zuletzt die Verteidigung des UEFA-Pokals?",
        "FC Sevilla,Real Madrid,Ipswich Town,SSC Neapel",
    ),
    both(
        "Wie oft war Manchester United englischer Meister?",
        "11mal,5mal,20mal,8 mal",
        "Wie oft war Manchester United bis November 2026 englischer Meister?",
        "20mal,11mal,5mal,8mal",
    ),
    both(
        "Wie oft war Paris St. Germain französischer Meister?",
        "3mal,20mal,7mal,9 mal",
        "Wie oft war Paris St. Germain bis November 2026 französischer Meister?",
        "14mal,3mal,7mal,9mal",
    ),
    question(
        "Welcher Dortmunder Spieler hat die meisten Europapokaleinsätze?",
        "Welcher Dortmunder Spieler hatte 1998 die meisten Europapokaleinsätze?",
        "Reuter,Kohler,Zorc,Möller",
    ),
    question(
        "Welcher Spieler des VfB Stuttgart hat die meisten Europapokaleinsätze?",
        "Welcher Spieler des VfB Stuttgart hatte 1998 die meisten Europapokaleinsätze?",
        "Wohlfahrt,Verlaat,Poschner,Berthold",
    ),
    question(
        "Welche dieser Mannschaften nahm bislang am häufigsten an einem Europapokal teil?",
        "Welche dieser Mannschaften nahm bis 1998 am häufigsten an einem Europapokal teil?",
        "CF Barcelona,Real Madrid,Bayern München,Juventus Turin",
    ),
    # Rangers play in blue.
    answers(
        "Welches sind die Vereinsfarben der Glasgow Rangers?",
        "rot/weiß,grün/weiß,schwarz/weiß,blau/weiß",
        "blau/weiß/rot,grün/weiß,schwarz/weiß,gelb/schwarz",
    ),
    question(
        "Welchen Verein trainierte der heutige HSV-Trainer Frank Pagelsdorf vor seiner Zeit bei Hansa Rostock?",
        "Welchen Verein trainierte Frank Pagelsdorf vor seiner Zeit bei Hansa Rostock?",
        "1.FC Union Berlin,VfL Bochum,Arminia Bielefeld,Fortuna Köln",
    ),
    question(
        "Bei welchem Bundesligaverein ist Claus Boden Torwarttrainer?",
        "Bei welchem Bundesligaverein war Claus Boden 1998 Torwarttrainer?",
        "TSV 1860 München,1.FC Kaiserslautern,MSV Duisburg,1.FC Köln",
    ),
    question(
        "Wie heißt der zur Zeit jüngste Bundesligaschiedsrichter?",
        "Wer war 1998 der jüngste Bundesligaschiedsrichter?",
        "Wolfgang Stark,Torsten Koop,Bernhard Zerr,Herbert Fandel",
    ),
    question(
        "Wie heißt der DFB-Schiedsrichterobmann?",
        "Wer war 1998 DFB-Schiedsrichterobmann?",
        "Volker Roth,Walter Eschweiler,Johannes Malka,Egidius Braun",
    ),
    question(
        "Welcher deutscher Schiedsrichter hat mit vier Spielen die meisten WM-Spiele gepfiffen?",
        "Welcher deutsche Schiedsrichter hatte bis 1998 mit vier Spielen die meisten WM-Spiele gepfiffen?",
        "Siegfried Kirschen,Albert Dusch,Kurt Tschenscher,Volker Roth",
    ),
    question(
        "Welche Autofirma sponsort den Weltcup?",
        "Welche Autofirma sponserte bis 2004 den Weltpokal der Vereinsmannschaften?",
        "Toyota,Mazda,Honda,Mitsubishi",
    ),
    question(
        ("Welche Bundesligamannschaft belegte nach der Herbstmeisterschaft bisher am Saisonende den schlechtesten "
         "Tabellenplatz (5.)?"),
        ("Welche Bundesligamannschaft belegte bis 1998 nach der Herbstmeisterschaft am Saisonende den schlechtesten "
         "Tabellenplatz (5.)?"),
        "Eintracht Frankfurt,Bayern München,Borussia Dortmund,Werder Bremen",
    ),
    question(
        "Welche Mannschaft gewann bisher als einzige drei Herbstmeisterschaften in Serie?",
        "Welche Mannschaft gewann bis 1998 als einzige drei Herbstmeisterschaften in Serie?",
        "Borussia Mönchengladbach,1.FC Kaiserslautern,Bayern München,Borussia Dortmund",
    ),
)

NEW = (
    # Level 1.
    new(
        0,
        "Welches Land wurde 1998 im eigenen Land Weltmeister?",
        "Frankreich,Brasilien,Kroatien,Deutschland natürlich",
    ),
    new(0, "Wo fand die WM 2002 statt?", "in Japan und Südkorea,in China,in Australien,auf dem Mond"),
    new(0, "Wie nannte man die WM 2006 in Deutschland später?", "Sommermärchen,Wintermärchen,Rasenschach,Grillfest"),
    new(
        0,
        "Welcher Franzose sah im WM-Finale 2006 nach einem Kopfstoß die rote Karte?",
        "Zinedine Zidane,Thierry Henry,Franck Ribéry,Patrick Vieira",
    ),
    new(0, "Welchen Platz belegte Deutschland bei der Heim-WM 2006?", "Platz 3,Platz 2,Platz 4,Aus in der Vorrunde"),
    new(
        0,
        "Welches Tier sagte bei der WM 2010 die Ergebnisse der deutschen Spiele voraus?",
        "Krake Paul,Ziege Gustav,Papagei Rudi,Kater Carlo",
    ),
    new(0, "Wer wurde 2010 in Südafrika Weltmeister?", "Spanien,Niederlande,Deutschland,Uruguay"),
    new(0, "Mit welchem Instrument machten die Fans bei der WM 2010 Lärm?", "Vuvuzela,Alphorn,Dudelsack,Blockflöte"),
    new(
        0,
        "Wer schoß Deutschland 2014 im WM-Finale zum Titel?",
        "Mario Götze,Thomas Müller,André Schürrle,Miroslav Klose",
    ),
    new(0, "Wie endete das WM-Halbfinale 2014 zwischen Brasilien und Deutschland?", "1:7,0:4,2:3,7:1 für Brasilien"),
    new(0, "Wer war Bundestrainer beim WM-Titel 2014?", "Joachim Löw,Jürgen Klinsmann,Hansi Flick,Rudi Völler"),
    new(0, "Wer wurde 2018 in Rußland Weltmeister?", "Frankreich,Kroatien,Belgien,Deutschland"),
    new(0, "In welchem Land fand die WM 2022 statt?", "Katar,Saudi-Arabien,Vereinigte Arabische Emirate,Rußland"),
    new(0, "Wer wurde 2022 Weltmeister?", "Argentinien,Frankreich,Kroatien,Marokko"),
    new(0, "Wer wurde 2026 Weltmeister?", "Spanien,Argentinien,Frankreich,USA"),
    new(
        0,
        "Welche drei Länder richteten die WM 2026 aus?",
        "USA Kanada und Mexiko,USA Brasilien und Argentinien,Kanada Island und Grönland,Mexiko Kuba und Jamaika",
    ),
    new(0, "Wer wurde 2004 überraschend Europameister?", "Griechenland,Portugal,Tschechien,Dänemark"),
    new(
        0,
        "Welcher deutsche Trainer führte Griechenland 2004 zum EM-Titel?",
        "Otto Rehhagel,Berti Vogts,Winfried Schäfer,Rudi Völler",
    ),
    new(0, "Welches Land richtete die EM 2024 aus?", "Deutschland,Frankreich,England,Spanien"),
    new(0, "Wer wurde 2024 Europameister?", "Spanien,England,Deutschland,Frankreich"),
    new(0, "Wer wurde 2016 Europameister?", "Portugal,Frankreich,Wales,Island"),
    new(
        0,
        "Welcher Aufsteiger wurde 1998 gleich Deutscher Meister?",
        "1.FC Kaiserslautern,VfL Wolfsburg,Hertha BSC Berlin,FC Gütersloh",
    ),
    new(
        0,
        "Welcher Verein wurde 2009 erstmals Deutscher Meister?",
        "VfL Wolfsburg,TSG Hoffenheim,Hertha BSC Berlin,FC Schalke 04",
    ),
    new(
        0,
        "Welcher Trainer führte Borussia Dortmund 2011 und 2012 zur Meisterschaft?",
        "Jürgen Klopp,Thomas Tuchel,Lucien Favre,Matthias Sammer",
    ),
    new(
        0,
        "Welcher Verein wurde 2024 ohne Niederlage Deutscher Meister?",
        "Bayer Leverkusen,Bayern München,VfB Stuttgart,RB Leipzig",
    ),
    new(
        0,
        "Welcher Spitzname blieb Bayer Leverkusen nach drei zweiten Plätzen im Jahr 2002?",
        "Vizekusen,Pechkusen,Silberkusen,Bayer Zweitausend",
    ),
    new(0, "Wie oft in Folge wurde Bayern München von 2013 bis 2023 Meister?", "11mal,8mal,10mal,13mal"),
    new(
        0,
        "Wer war Trainer beim Triple des FC Bayern 2013?",
        "Jupp Heynckes,Pep Guardiola,Louis van Gaal,Ottmar Hitzfeld",
    ),
    new(
        0,
        "Gegen wen gewann Bayern München 2013 das Champions-League-Finale?",
        "Borussia Dortmund,FC Chelsea,Inter Mailand,Real Madrid",
    ),
    new(
        0,
        "Welcher Verein stieg 2018 zum ersten Mal aus der Bundesliga ab?",
        "Hamburger SV,1.FC Köln,Werder Bremen,VfB Stuttgart",
    ),
    new(
        0,
        "Wer erzielte 2015 gegen Wolfsburg fünf Tore in neun Minuten?",
        "Robert Lewandowski,Thomas Müller,Mario Gomez,Pierre-Emerick Aubameyang",
    ),
    new(
        0,
        "Von welchem Verein wechselte Jude Bellingham 2023 zu Real Madrid?",
        "Borussia Dortmund,FC Liverpool,RB Leipzig,FC Arsenal",
    ),
    new(0, "Wie oft gewann Lionel Messi bis November 2026 den Ballon d'Or?", "8mal,5mal,6mal,10mal"),
    new(
        0,
        "Zu welchem Verein wechselte Thomas Müller 2025 nach 25 Jahren beim FC Bayern?",
        "Vancouver Whitecaps,LA Galaxy,Inter Miami,TSV 1860 München",
    ),
    new(
        0,
        "Was gibt es in der Bundesliga seit der Saison 2017/18?",
        "Videobeweis,Rückpaßregel,Golden Goal,Zeitstrafen",
    ),
    new(
        0,
        "Wie viele Spieler durfte eine Bundesliga-Mannschaft im November 2026 in der regulären Spielzeit einwechseln?",
        "fünf,drei,vier,beliebig viele",
    ),
    new(
        0,
        "Welcher Torwart wurde 2002 als erster Torhüter bester Spieler einer WM?",
        "Oliver Kahn,Gianluigi Buffon,Jens Lehmann,Iker Casillas",
    ),
    new(
        0,
        "Was hatte Jens Lehmann im WM-Viertelfinale 2006 gegen Argentinien im Stutzen?",
        "einen Zettel mit den Elfmeterschützen,seinen Einkaufszettel,ein Butterbrot,einen Liebesbrief",
    ),
    new(0, "Was forderte Oliver Kahn 2003 in einem berühmten Interview?", "Eier,mehr Geld,Freibier,Ruhe"),
    new(
        0,
        "Wer wurde 2023 mit 36 Jahren Bundestrainer?",
        "Julian Nagelsmann,Ralf Rangnick,Jürgen Klopp,Lothar Matthäus",
    ),
    new(
        0,
        "Welcher Verein gewann 2025 das Champions-League-Finale mit 5:0, der höchste Endspielsieg seit 1956?",
        "Paris St. Germain,Inter Mailand,FC Barcelona,Bayern München",
    ),
    new(
        0,
        "Welcher Verein gewann 2020 das Champions-League-Finale mit 1:0 gegen Paris St. Germain?",
        "Bayern München,FC Liverpool,Real Madrid,Borussia Dortmund",
    ),
    new(
        0,
        "Welcher Spieler wechselte 2017 für 222 Millionen Euro zu Paris St. Germain?",
        "Neymar,Kylian Mbappé,Lionel Messi,Cristiano Ronaldo",
    ),
    new(
        0,
        "Für welchen dieser Vereine hat Cristiano Ronaldo nie gespielt?",
        "Bayern München,Real Madrid,Juventus Turin,Manchester United",
    ),
    new(
        0,
        "Welchen Pokal gewann der FC Gütersloh 2023 zum ersten Mal?",
        "Westfalenpokal,DFB-Pokal,UEFA-Cup,Hallen-Masters",
    ),
    new(
        0,
        "In welche Liga stieg der FC Gütersloh 2023 als Meister der Oberliga Westfalen auf?",
        "Regionalliga West,2. Bundesliga,Bundesliga,Champions League",
    ),
    # Level 2.
    new(
        1,
        ("Gegen wen verlor Bayern München 1999 in Barcelona das Champions-League-Finale nach 1:0-Führung durch zwei "
         "Gegentore in der Nachspielzeit?"),
        "Manchester United,FC Barcelona,Juventus Turin,Real Madrid",
    ),
    new(
        1,
        "Gegen wen gewann Bayern München 2001 das Champions-League-Finale im Elfmeterschießen?",
        "FC Valencia,Real Madrid,Manchester United,AC Mailand",
    ),
    new(
        1,
        "Gegen wen verlor Bayern München 2012 das \"Finale dahoam\"?",
        "FC Chelsea,Inter Mailand,Real Madrid,Borussia Dortmund",
    ),
    new(
        1,
        "Gegen wen verlor Bayer Leverkusen 2002 das Champions-League-Finale?",
        "Real Madrid,Manchester United,FC Valencia,Juventus Turin",
    ),
    new(
        1,
        "Wo verlor Bayer Leverkusen am letzten Spieltag 2000 die Meisterschaft?",
        "in Unterhaching,in Rostock,in Bielefeld,in Gütersloh",
    ),
    new(
        1,
        "Welcher Verein wurde 2001 \"Meister der Herzen\"?",
        "FC Schalke 04,Bayer Leverkusen,Borussia Dortmund,Hertha BSC Berlin",
    ),
    new(
        1,
        "Wer schoß Bayern 2001 am letzten Spieltag in der Nachspielzeit in Hamburg zur Meisterschaft?",
        "Patrik Andersson,Giovane Elber,Carsten Jancker,Stefan Effenberg",
    ),
    new(
        1,
        "Welcher Verein gewann 2004 Meisterschaft und Pokal?",
        "Werder Bremen,Bayern München,VfB Stuttgart,Bayer Leverkusen",
    ),
    new(
        1,
        "Welches Sturmduo schoß 2008/09 zusammen 54 Tore und stellte damit einen Bundesligarekord auf?",
        "Grafite und Edin Dzeko,Klose und Podolski,Ailton und Diego,Gomez und Cacau",
    ),
    new(1, "Wie endete das DFB-Pokalfinale 2012 zwischen Dortmund und Bayern?", "5:2,2:1,0:0 n.E.,1:3"),
    new(
        1,
        "Wer war Trainer von Bayer Leverkusen bei der Meisterschaft 2024?",
        "Xabi Alonso,Gerardo Seoane,Peter Bosz,Rudi Völler",
    ),
    new(
        1,
        "Gegen wen verlor Bayer Leverkusen 2024 im Europa-League-Finale das einzige Spiel der Saison?",
        "Atalanta Bergamo,AS Rom,West Ham United,FC Sevilla",
    ),
    new(
        1,
        "Wie viele Tore schoß Bayern München in der Saison 2025/26 (Bundesligarekord, Stand November 2026)?",
        "122,101,111,99",
    ),
    new(
        1,
        "Welcher Drittligist erreichte 2025 das DFB-Pokalfinale?",
        "Arminia Bielefeld,1.FC Saarbrücken,Dynamo Dresden,FC Gütersloh",
    ),
    new(
        1,
        "Welcher Verein gewann 2022 die Europa League?",
        "Eintracht Frankfurt,Glasgow Rangers,RB Leipzig,West Ham United",
    ),
    new(
        1,
        "Gegen wen verlor der SC Freiburg 2026 das Europa-League-Finale?",
        "Aston Villa,Ajax Amsterdam,AS Rom,Olympique Lyon",
    ),
    new(
        1,
        "Wer übernahm 2004 nach Rudi Völler die Nationalmannschaft?",
        "Jürgen Klinsmann,Joachim Löw,Ottmar Hitzfeld,Otto Rehhagel",
    ),
    new(
        1,
        "Welcher Reporter mußte sich 2003 nach dem Spiel auf Island Rudi Völlers Wutrede anhören?",
        "Waldemar Hartmann,Gerhard Delling,Marcel Reif,Béla Réthy",
    ),
    new(
        1,
        "Wie viel hatte der Reporter laut Rudi Völlers Wutrede von 2003 getrunken?",
        "drei Weizenbier,zwei Rotwein,einen Kaffee,vier Eierlikör",
    ),
    new(
        1,
        "Welchen Spieler meinte Giovanni Trapattoni 1998 mit \"Was erlauben ...\"?",
        "Strunz,Basler,Scholl,Matthäus",
    ),
    new(
        1,
        "Mit welchem Satz beendete Giovanni Trapattoni 1998 seine Wutrede?",
        "Ich habe fertig,Ende Gelände,Das war's,Schluß mit lustig",
    ),
    new(
        1,
        "Welcher Schiedsrichter wurde 2005 wegen Spielmanipulation verurteilt?",
        "Robert Hoyzer,Markus Merk,Wolfgang Stark,Manuel Gräfe",
    ),
    new(
        1,
        "Welcher Spieler verließ 2008 beim Länderspiel gegen Rußland in der Halbzeit das Stadion?",
        "Kevin Kuranyi,Lukas Podolski,Torsten Frings,Michael Ballack",
    ),
    new(
        1,
        "Wem wird der Satz \"Fußball ist wie Schach, nur ohne Würfel\" zugeschrieben?",
        "Lukas Podolski,Lothar Matthäus,Andreas Möller,Thomas Häßler",
    ),
    new(
        1,
        "Wohin wollte sich Per Mertesacker 2014 nach dem Spiel gegen Algerien für drei Tage legen?",
        "in die Eistonne,ins Hotelbett,an den Strand,auf die Ersatzbank",
    ),
    new(1, "Welchen Spitznamen trägt Thomas Müller?", "Raumdeuter,Bomber,Kaiser,Titan"),
    new(
        1,
        ("Gegen welches Land gewann Deutschland bei der WM 2010 mit 4:1, obwohl ein Tor von Frank Lampard nicht "
         "zählte?"),
        "England,Argentinien,Ghana,Australien",
    ),
    new(1, "Welchen Platz belegte Deutschland bei der WM 2010?", "Platz 3,Weltmeister,Platz 2,Aus im Viertelfinale"),
    new(
        1,
        "Wer wurde bei der WM 2010 Torschützenkönig?",
        "Thomas Müller,Miroslav Klose,Lionel Messi,Cristiano Ronaldo",
    ),
    new(
        1,
        "Wer erzielte 2014 gegen Brasilien sein 16. WM-Tor, damals Rekord?",
        "Miroslav Klose,Thomas Müller,Lukas Podolski,Mario Gomez",
    ),
    new(1, "Wer gewann das EM-Finale 2000 durch ein Golden Goal?", "Frankreich,Italien,Portugal,Niederlande"),
    new(
        1,
        "Welches Land, dessen Fans mit ihrem \"Huh\" berühmt wurden, kam bei der EM 2016 ins Viertelfinale?",
        "Island,Nordirland,Albanien,Rumänien",
    ),
    new(1, "Wo fand das Endspiel der EM 2020 statt?", "London,Rom,München,Baku"),
    new(1, "In welchem Jahr wurde die EM 2020 tatsächlich gespielt?", "2021,2020,2022,gar nicht"),
    new(
        1,
        "Welcher Verein wurde 2009 als RasenBallsport gegründet?",
        "RB Leipzig,1.FC Union Berlin,TSG Hoffenheim,FC Gütersloh",
    ),
    new(
        1,
        "Welcher Verein stieg 2019 zum ersten Mal in die Bundesliga auf?",
        "1.FC Union Berlin,RB Leipzig,FC Ingolstadt,SV Darmstadt 98",
    ),
    new(
        1,
        "Welcher Verein spielte 2024/25 zum ersten Mal in der Bundesliga?",
        "Holstein Kiel,FC St. Pauli,1.FC Heidenheim,Fortuna Düsseldorf",
    ),
    new(
        1,
        "Wer trainierte den SC Freiburg von 2011 bis 2024?",
        "Christian Streich,Volker Finke,Robin Dutt,Marcus Sorg",
    ),
    new(1, "Wie alt war Julian Nagelsmann, als er 2016 Trainer in Hoffenheim wurde?", "28,35,24,41"),
    new(
        1,
        "Wer verlor 2023 am letzten Spieltag durch ein 2:2 gegen Mainz die Meisterschaft?",
        "Borussia Dortmund,Bayern München,1.FC Union Berlin,SC Freiburg",
    ),
    new(
        1,
        "Wer verlor 2024 das Champions-League-Finale gegen Real Madrid?",
        "Borussia Dortmund,Bayern München,Bayer Leverkusen,Inter Mailand",
    ),
    new(
        1,
        "Mit welchem Verein gewann Jürgen Klopp 2019 die Champions League?",
        "FC Liverpool,Borussia Dortmund,1.FSV Mainz 05,Tottenham Hotspur",
    ),
    new(
        1,
        "Welcher Verein zahlte 2023 rund 100 Millionen Euro für Harry Kane?",
        "Bayern München,Manchester United,Paris St. Germain,FC Gütersloh",
    ),
    new(
        1,
        "Zu welchem Verein wechselte Florian Wirtz 2025?",
        "FC Liverpool,Bayern München,Real Madrid,Manchester City",
    ),
    new(1, "Wie oft gewann Cristiano Ronaldo bis November 2026 den Ballon d'Or?", "5mal,8mal,3mal,7mal"),
    new(1, "Wer gewann 2024 den Ballon d'Or?", "Rodri,Vinicius Junior,Jude Bellingham,Erling Haaland"),
    new(1, "Welcher Kroate gewann 2018 den Ballon d'Or?", "Luka Modric,Ivan Rakitic,Mario Mandzukic,Ivan Perisic"),
    new(1, "Welches Land gewann die Frauen-WM 2003 und 2007?", "Deutschland,USA,Norwegen,Schweden"),
    new(1, "Welche Medaille gewannen die deutschen Fußballerinnen bei Olympia 2016?", "Gold,Silber,Bronze,keine"),
    new(1, "Welche Medaille gewannen die deutschen Fußballer bei Olympia 2016?", "Silber,Gold,Bronze,keine"),
    new(1, "In welchem Jahr stieg der FC Gütersloh in die 2. Bundesliga auf?", "1996,1984,1999,2023"),
    new(
        1,
        "Gegen wen verlor der FC Gütersloh 2023 in der ersten Runde des DFB-Pokals mit 0:2?",
        "Holstein Kiel,Bayern München,Arminia Bielefeld,SC Paderborn 07",
    ),
    new(
        1,
        "Wie oft in Folge wurde Paris St. Germain von 2022 bis 2026 französischer Meister?",
        "fünfmal,dreimal,viermal,keinmal",
    ),
    new(1, "Wie viele DFB-Pokalsiege hatte Bayern München im November 2026?", "21,20,18,25"),
    new(
        1,
        "Was zeigt der Schiedsrichter seit 2025 an, wenn ein Torwart den Ball zu lange hält?",
        "die letzten fünf Sekunden mit der Hand,eine Sanduhr,die gelbe Karte,nichts",
    ),
    new(
        1,
        "In wie vielen Pflichtspielen in Folge blieb Bayer Leverkusen 2023/24 ungeschlagen (Europarekord)?",
        "51,34,42,63",
    ),
    new(1, "Wie viele Titel gewann Bayern München im Kalenderjahr 2013?", "fünf,drei,vier,sieben"),
    new(
        1,
        "Welcher Verein gewann als erster die Champions League dreimal in Folge?",
        "Real Madrid,FC Barcelona,Bayern München,AC Mailand",
    ),
    new(1, "Wie viele Tore schoß Lionel Messi im Jahr 2012 (Rekord für ein Kalenderjahr)?", "91,85,73,102"),
    # Level 3.
    new(
        2,
        "Wer spielt beim SC Germania Stromberg Libero?",
        "Rolf Langenberg,Gerald Köhler,Lothar Matthäus,Franz Beckenbauer",
    ),
    new(
        2,
        "In welcher Liga spielte der FC Gütersloh in der Saison 1998/99?",
        "2. Bundesliga,Champions League,Kreisliga C,Regionalliga Süd",
    ),
    new(
        2,
        "Unter welchem Namen wurde der FC Gütersloh im Jahr 2000 neu gegründet?",
        "FC Gütersloh 2000,Gütersloh United,Real Gütersloh,Ascaron 2000",
    ),
    new(
        2,
        "Wie heißt das Stadion des FC Gütersloh?",
        "Heidewaldstadion,Ohlendorfstadion,Bertelsmann-Arena,Allianz Arena",
    ),
    new(2, "Wie viele Elfmeter hielt Oliver Kahn im Champions-League-Finale 2001?", "drei,zwei,einen,keinen"),
    new(
        2,
        "Wer schoß Bayern München 2013 im Champions-League-Finale in der 89. Minute zum 2:1?",
        "Arjen Robben,Thomas Müller,Mario Mandzukic,Franck Ribéry",
    ),
    new(2, "Wie viele Titel gewann Bayern München zwischen Juni 2020 und Februar 2021?", "sechs,drei,vier,fünf"),
    new(
        2,
        "Wo spielte der 1.FC Union Berlin 2023/24 seine Heimspiele in der Champions League?",
        "im Olympiastadion,an der Alten Försterei,im Jahn-Sportpark,im Mommsenstadion",
    ),
    new(
        2,
        "Welcher Viertligist erreichte 2020 das Halbfinale des DFB-Pokals?",
        "1.FC Saarbrücken,FC Gütersloh,Rot-Weiss Essen,SV Elversberg",
    ),
    new(2, "Wie endete das DFB-Pokalfinale 2024 zwischen Leverkusen und Kaiserslautern?", "1:0,3:0,2:2 n.E.,0:1"),
    new(2, "Mit wie vielen Punkten wurde Bayer Leverkusen 2024 Meister?", "90,82,78,101"),
    new(
        2,
        "Wer ist mit über 300 Toren der erfolgreichste ausländische Torschütze der Bundesliga (Stand November 2026)?",
        "Robert Lewandowski,Claudio Pizarro,Giovane Elber,Pierre-Emerick Aubameyang",
    ),
    new(
        2,
        "Wer hatte im November 2026 wie Manuel Neuer 13 deutsche Meisterschaften gewonnen?",
        "Thomas Müller,David Alaba,Franck Ribéry,Oliver Kahn",
    ),
    new(
        2,
        "In wie vielen Bundesligaspielen blieb Manuel Neuer bis Mai 2026 ohne Gegentor (Rekord)?",
        "246,197,312,150",
    ),
    new(
        2,
        "Was gibt es seit 2025, wenn ein Torwart den Ball länger als acht Sekunden in den Händen hält?",
        "Eckstoß für den Gegner,indirekten Freistoß,Elfmeter,Applaus",
    ),
    new(
        2,
        "Was malt der Schiedsrichter in die Luft, wenn er sich eine Szene am Bildschirm ansieht?",
        "ein Rechteck,eine Raute,ein Herz,eine Acht",
    ),
    new(2, "Ab welcher Saison gab es in der Bundesliga wieder die Relegation?", "2008/09,1998/99,2015/16,1991/92"),
    new(2, "Wie viele Mannschaften spielten 2025/26 in der Ligaphase der Champions League?", "36,32,48,64"),
    new(
        2,
        "Wie heißt der dritte Europapokal, den die UEFA 2021 eingeführt hat?",
        "Conference League,Intertoto-Cup,Super League,Nations League",
    ),
    new(
        2,
        "Welcher Trainer gewann als erster Champions League, Europa League und Conference League?",
        "José Mourinho,Pep Guardiola,Carlo Ancelotti,Unai Emery",
    ),
    new(
        2,
        "Für welchen dieser Vereine spielte Claudio Pizarro nie in der Bundesliga?",
        "Hertha BSC Berlin,Werder Bremen,Bayern München,1.FC Köln",
    ),
    new(
        2,
        "Wer schoß Deutschland im WM-Halbfinale 2002 gegen Südkorea ins Finale?",
        "Michael Ballack,Miroslav Klose,Oliver Neuville,Carsten Jancker",
    ),
    new(2, "Warum fehlte Michael Ballack im WM-Finale 2002?", "Gelbsperre,Grippe,Hochzeit,Streit mit Rudi Völler"),
    new(2, "Wie viele Tore erzielte Miroslav Klose bei der WM 2002 mit dem Kopf?", "fünf,drei,eins,sieben"),
    new(2, "Wie endete das Spiel Deutschland gegen Saudi-Arabien bei der WM 2002?", "8:0,5:0,3:1,0:0"),
    new(
        2,
        "In welchem Stadion fand das WM-Finale 2006 statt?",
        "Olympiastadion Berlin,Allianz Arena,Westfalenstadion,Heidewaldstadion",
    ),
    new(
        2,
        "Wer schoß Italien im WM-Halbfinale 2006 in der 119. Minute gegen Deutschland in Führung?",
        "Fabio Grosso,Alessandro Del Piero,Andrea Pirlo,Marco Materazzi",
    ),
    new(
        2,
        "In welcher Stadt verlor Deutschland 2006 das WM-Halbfinale gegen Italien?",
        "Dortmund,Berlin,München,Gelsenkirchen",
    ),
    new(
        2,
        "Welcher deutsche Spieler blutete im WM-Finale 2014 nach einem Schlag unter dem Auge?",
        "Bastian Schweinsteiger,Philipp Lahm,Toni Kroos,Mats Hummels",
    ),
    new(2, "Wer wurde 2014 mit sechs Toren WM-Torschützenkönig?", "James Rodríguez,Thomas Müller,Lionel Messi,Neymar"),
    new(2, "Wer wurde 2018 WM-Torschützenkönig?", "Harry Kane,Antoine Griezmann,Romelu Lukaku,Cristiano Ronaldo"),
    new(2, "Bei welcher WM gab es zum ersten Mal den Videobeweis?", "2018,2014,2010,2022"),
    new(
        2,
        "In welchen Monaten wurde die WM 2022 gespielt?",
        "November und Dezember,Juni und Juli,Januar und Februar,März und April",
    ),
    new(2, "Wie viele WM-Tore hat Kylian Mbappé nach der WM 2026 erzielt (Rekord)?", "22,16,12,30"),
    new(2, "Mit wie vielen Mannschaften wurde die EM 2016 erstmals gespielt?", "24,16,32,20"),
    new(2, "Wer schlug England bei der EM 2016 im Achtelfinale?", "Island,Wales,Slowakei,Rußland"),
    new(
        2,
        "Nach wie vielen Jahren in der 2. Bundesliga kehrte der Hamburger SV 2025 in die Bundesliga zurück?",
        "sieben,zwei,zwölf,einem",
    ),
    new(
        2,
        "Gegen wen verlor der FC Gütersloh 2025 in der ersten Runde des DFB-Pokals mit 0:5?",
        "1.FC Union Berlin,Holstein Kiel,Hertha BSC Berlin,FC Gütersloh 2000 Amateure",
    ),
    new(
        2,
        "Welchen Platz belegte die TSG Hoffenheim 2008/09 am Saisonende, obwohl sie Herbstmeister war?",
        "7.,2.,4.,18.",
    ),
    new(
        2,
        "Wer gewann 2026 als erster Engländer seit Michael Owen den Ballon d'Or?",
        "Harry Kane,Jude Bellingham,Bukayo Saka,Declan Rice",
    ),
    new(2, "Wie viele Länderspiele bestritt Anders Svensson für Schweden (Rekord)?", "148,143,120,99"),
    new(
        2,
        "Welcher Verein gewann 2009 als erster sechs Titel in einem Kalenderjahr?",
        "FC Barcelona,Manchester United,Bayern München,Inter Mailand",
    ),
    new(2, "Wie viele Punkte holte Bayern München 2012/13 (Bundesligarekord, Stand November 2026)?", "91,90,89,102"),
    new(
        2,
        "An welchem Spieltag stand Bayern München 2013/14 als Meister fest (Rekord, Stand November 2026)?",
        "27.,30.,25.,31.",
    ),
    new(
        2,
        "Wer wurde 2020 mit 16 Jahren jüngster Torschütze der Bundesliga?",
        "Youssoufa Moukoko,Florian Wirtz,Nuri Sahin,Jamal Musiala",
    ),
)
# fmt: on

Patch = namedtuple("Patch", "key option title changes")

PATCHES = (
    Patch("QuizAnswers", "answers", "Quizfragen", ANSWERS),
    Patch("QuizQuestions", "new", "Neue Quizfragen", NEW),
)
# the first argument: which switches are on
MODES = {"original": (), "answers": ("answers",), "both": ("answers", "new"), "new": ("new",)}


def state(patch, questions):
    """ "on", "off" or None (the quiz isn't the game's)."""
    if questions is None:
        return None
    for on in (True, False):
        if all(is_in(c, questions, on) for c in patch.changes):
            return "on" if on else "off"
    return None


def switch(patch, questions, on):
    """Switches patch on or off in questions; whether that changed them."""
    pending = [c for c in patch.changes if not is_in(c, questions, on)]
    for change in pending:
        make(change, questions, on)
    return bool(pending)


def main():
    """Sets the quiz switches as the first argument says, or shows them."""
    ap = argparse.ArgumentParser(description="Brings the manager course quiz up to date (ports from A2G-Patch).")
    ap.add_argument("mode", choices=[*MODES, "status"], help="which switches are on afterwards, or show them")
    ap.add_argument("folder")
    a = ap.parse_args()
    files = GameFiles(a.folder)
    data = files.read(QUIZ_FILE)
    if data is None:
        sys.exit(f"{a.folder}: no {QUIZ_FILE}")
    questions = read(data)
    changed = False
    for patch in PATCHES:
        now = state(patch, questions)
        if now is None:
            print(f"{patch.title}: {QUIZ_FILE} doesn't hold the game's questions, left unchanged")
        elif a.mode == "status":
            print(f"{patch.title}: {now}")
        else:
            wanted = "on" if patch.option in MODES[a.mode] else "off"
            changed |= switch(patch, questions, wanted == "on")
            print(f"{patch.title}: {wanted}" if now != wanted else f"{patch.title}: already {wanted}")
    if changed:
        files.write(QUIZ_FILE, write(questions))
        files.save()


if __name__ == "__main__":
    main()

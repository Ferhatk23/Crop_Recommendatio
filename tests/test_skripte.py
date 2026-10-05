"""Tests für die Verwaltungsskripte.

Hier steht der Fehler, den der erste echte Installationslauf zutage
gebracht hat -- und der vorher niemandem auffallen konnte, weil er in der
Entwicklung nie auftritt.

Der dokumentierte Befehl war:

    sudo -u tradediary /opt/tradediary/.venv/bin/python \\
         /opt/tradediary/scripts/nutzer.py anlegen ich@example.com

**sudo gibt die Umgebung nicht weiter.** `TRADEDIARY_DB` war damit nicht
gesetzt, das Skript fiel auf den relativen Standardwert zurück, und SQLite
legte bereitwillig eine neue, leere Datenbank im Arbeitsverzeichnis an.
Der Nutzer landete in `/opt/tradediary/tradediary.db` statt in
`/var/lib/tradediary/tradediary.db`.

Das Skript meldete „Angelegt", alles sah richtig aus -- und die Anmeldung
scheiterte danach mit „E-Mail oder Passwort stimmt nicht". Eine Meldung,
die in die völlig falsche Richtung zeigt: Wer das nicht weiss, sucht beim
Passwort und findet den Fehler nie. Gleich beim ersten Schritt, bevor
irgendetwas anderes je zum Zuge kommt.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).parent.parent
SKRIPTE = WURZEL / "scripts"


def lauf(skript: str, *argumente: str, db: str | None, cwd: Path):
    """Ein Verwaltungsskript starten -- mit oder ohne TRADEDIARY_DB.

    Die Umgebung wird bewusst ausgedünnt statt ergänzt: Genau das macht
    sudo, und genau darum geht es hier.
    """
    umgebung = {
        k: v
        for k, v in os.environ.items()
        if k in ("PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV")
    }
    if db is not None:
        umgebung["TRADEDIARY_DB"] = db
    return subprocess.run(
        [sys.executable, str(SKRIPTE / skript), *argumente],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=umgebung,
        input="ein langes probepasswort\nein langes probepasswort\n",
        timeout=120,
    )


@pytest.mark.parametrize("skript", ["nutzer.py", "marke.py"])
def test_ohne_umgebung_entsteht_keine_datenbank(skript, tmp_path):
    """Der Kern der Sache.

    Vorher legte SQLite hier wortlos eine neue Datei an, und der Eintrag
    verschwand darin. Jetzt bricht das Skript ab.
    """
    ergebnis = lauf(
        skript,
        "anlegen",
        "ich@example.invalid" if skript == "nutzer.py" else "1",
        db=None,
        cwd=tmp_path,
    )
    assert ergebnis.returncode == 2, ergebnis.stdout + ergebnis.stderr
    assert not list(tmp_path.glob("*.db")), "es ist doch eine Datenbank entstanden"


@pytest.mark.parametrize("skript", ["nutzer.py", "marke.py"])
def test_die_meldung_nennt_sudo_und_den_ausweg(skript, tmp_path):
    """Eine Fehlermeldung, die den Grund verschweigt, kostet einen Abend.

    Hier stand ursprünglich gar keine -- das Skript meldete Erfolg.
    """
    ergebnis = lauf(skript, "liste", db=None, cwd=tmp_path)
    text = ergebnis.stderr
    assert "sudo" in text
    assert "TRADEDIARY_DB" in text
    # Und sie muss den Befehl zeigen, der es richtig macht.
    assert "env" in text and "/var/lib/tradediary" in text


@pytest.mark.parametrize("skript", ["nutzer.py", "marke.py"])
def test_mit_gesetzter_umgebung_laeuft_es(skript, tmp_path):
    """Gegenprobe: Die Sperre darf nicht einfach immer zuschlagen."""
    db = tmp_path / "echt.db"
    from tradediary.db.repository import engine_bauen, schema_anlegen

    schema_anlegen(engine_bauen(f"sqlite:///{db}"))

    ergebnis = lauf(skript, "liste", db=f"sqlite:///{db}", cwd=tmp_path)
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr


def test_der_nutzer_landet_in_der_angegebenen_datenbank(tmp_path):
    """Nicht nur „es läuft durch" -- er muss auch dort sein."""
    import sqlite3

    from tradediary.db.repository import engine_bauen, schema_anlegen

    db = tmp_path / "echt.db"
    schema_anlegen(engine_bauen(f"sqlite:///{db}"))

    ergebnis = lauf(
        "nutzer.py",
        "anlegen",
        "ich@example.invalid",
        db=f"sqlite:///{db}",
        cwd=tmp_path,
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr

    v = sqlite3.connect(db)
    try:
        assert v.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    finally:
        v.close()
    # Und nirgendwo sonst.
    assert [p.name for p in tmp_path.glob("*.db")] == ["echt.db"]


def test_mit_neu_geht_es_doch(tmp_path):
    """Wer wirklich eine neue Datenbank will, sagt es ausdrücklich.

    Eine Sperre ohne Ausweg ist irgendwann der Grund, warum jemand das
    Skript umgeht.
    """
    ergebnis = lauf(
        "nutzer.py", "anlegen", "ich@example.invalid", "--neu", db=None, cwd=tmp_path
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    assert (tmp_path / "tradediary.db").exists()


def test_die_anleitungen_geben_die_umgebung_mit():
    """Jede dokumentierte Zeile, die ein Verwaltungsskript startet.

    Der Fehler stand in drei Dateien gleichzeitig. Ihn an einer zu
    beheben und die anderen zu vergessen, wäre das Naheliegende.
    """
    verdaechtig = []
    for datei in (
        WURZEL / "deploy" / "README.md",
        WURZEL / "deploy" / "einrichten.sh",
    ):
        zeilen = datei.read_text().splitlines()
        for i, zeile in enumerate(zeilen):
            if "scripts/nutzer.py" not in zeile and "scripts/marke.py" not in zeile:
                continue
            # Der Aufruf darf über mehrere Zeilen gehen; die Umgebung steht
            # dann weiter oben.
            umfeld = "\n".join(zeilen[max(0, i - 3) : i + 1])
            if "sudo" in umfeld and "TRADEDIARY_DB" not in umfeld:
                verdaechtig.append(f"{datei.name}:{i + 1}: {zeile.strip()}")

    assert not verdaechtig, (
        "Diese Aufrufe laufen unter sudo ohne TRADEDIARY_DB -- der Eintrag "
        "landet dann in einer neuen, leeren Datenbank:\n  "
        + "\n  ".join(verdaechtig)
    )

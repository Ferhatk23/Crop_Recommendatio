"""Tests für die Schema-Wanderungen.

Hier steht der Fehler, der diese Datei veranlasst hat, als Test: Beim
Commit „Regeln messen statt fragen" bekam `playbook_rules` zwei neue
Spalten. `create_all` legt nur fehlende *Tabellen* an und fasst vorhandene
nicht an -- eine bestehende Datenbank behielt also die alte Tabelle. Die
App startete sauber, meldete nichts, und starb erst beim ersten Aufruf von
`/api/playbooks` mit `no such column: playbook_rules.auto_check`.

Das ist die unangenehmste Sorte Fehler: Er tritt nur beim Aktualisieren
auf, nie in der Entwicklung, weil dort die Datenbank immer frisch ist.

Der letzte Test der Datei ist deshalb der wichtigste. Er vergleicht das
heutige Modell mit einem festgeschriebenen Stand und verlangt für jede
seither dazugekommene Spalte einen Wanderungsschritt. Ohne ihn fiele
dasselbe beim nächsten Mal wieder niemandem auf.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3

import pytest
from sqlalchemy import inspect, text

from tradediary.db import models as db
from tradediary.db.repository import engine_bauen, schema_anlegen
from tradediary.db.wanderung import SCHRITTE, offene_schritte, wandern


STAND = pathlib.Path(__file__).parent / "schema_stand.json"


@pytest.fixture()
def alte_db(tmp_path):
    """Eine Datenbank im Stand vor den gemessenen Regeln.

    Volles Schema anlegen und die beiden Spalten wieder entfernen -- näher
    am echten Fall als ein von Hand nachgebautes Schema, weil alles andere
    garantiert stimmt.
    """
    pfad = tmp_path / "alt.db"
    url = f"sqlite:///{pfad}"
    schema_anlegen(engine_bauen(url))

    v = sqlite3.connect(pfad)
    for schritt in SCHRITTE:
        v.execute(f"ALTER TABLE {schritt.tabelle} DROP COLUMN {schritt.spalte}")
    # Daten, die den Umbau überleben müssen.
    v.execute("INSERT INTO playbooks (id, user_id, name) VALUES (1, 1, 'Altes Buch')")
    v.execute(
        "INSERT INTO playbook_rules (id, playbook_id, group_label, text,"
        " checkable, sort_order) VALUES (1, 1, 'A', 'Stop gesetzt', 1, 0)"
    )
    v.commit()
    v.close()
    return url


def spalten(engine, tabelle: str) -> set[str]:
    return {s["name"] for s in inspect(engine).get_columns(tabelle)}


# ---------------------------------------------------------------------------
# Der Fall, der die Datei veranlasst hat
# ---------------------------------------------------------------------------

def test_einer_alten_datenbank_fehlen_die_spalten(alte_db):
    """Gegenprobe: Ohne sie wäre alles Folgende wertlos."""
    engine = engine_bauen(alte_db)
    assert "auto_check" not in spalten(engine, "playbook_rules")
    assert len(offene_schritte(engine)) == len(SCHRITTE)


def test_die_wanderung_haengt_sie_an(alte_db):
    engine = engine_bauen(alte_db)
    getan = wandern(engine)
    assert getan == [s.name for s in SCHRITTE]
    assert "auto_check" in spalten(engine, "playbook_rules")
    assert "auto_param" in spalten(engine, "playbook_rules")


def test_die_vorhandenen_daten_ueberleben(alte_db):
    """Eine Wanderung, die Daten kostet, ist keine Wanderung."""
    engine = engine_bauen(alte_db)
    wandern(engine)
    with engine.connect() as v:
        zeilen = v.execute(
            text("SELECT text, auto_check FROM playbook_rules")
        ).all()
    assert zeilen == [("Stop gesetzt", None)]


def test_schema_anlegen_wandert_mit(alte_db):
    """Der Weg, den die App beim Hochfahren nimmt.

    Die Wanderung nützt nichts, wenn sie niemand aufruft -- und `init_db`
    ruft genau diese Funktion.
    """
    engine = engine_bauen(alte_db)
    gewandert = schema_anlegen(engine)
    assert gewandert == [s.name for s in SCHRITTE]
    assert "auto_check" in spalten(engine, "playbook_rules")


# ---------------------------------------------------------------------------
# Wiederholbar und harmlos
# ---------------------------------------------------------------------------

def test_zweimal_gestartet_passiert_einmal_etwas(alte_db):
    engine = engine_bauen(alte_db)
    assert wandern(engine) != []
    assert wandern(engine) == []


def test_eine_frische_datenbank_braucht_nichts(tmp_path):
    """`create_all` legt sie vollständig an -- es gibt nichts nachzutragen."""
    engine = engine_bauen(f"sqlite:///{tmp_path/'neu.db'}")
    assert schema_anlegen(engine) == []
    assert "auto_check" in spalten(engine, "playbook_rules")


def test_eine_leere_datenbank_bringt_die_wanderung_nicht_um(tmp_path):
    """Ohne Tabellen gibt es keine Spalten anzuhängen.

    Die Reihenfolge in `schema_anlegen` fängt das ab, aber die Wanderung
    muss auch allein durchlaufen, ohne zu werfen.
    """
    engine = engine_bauen(f"sqlite:///{tmp_path/'leer.db'}")
    assert wandern(engine) == []


def test_das_protokoll_sagt_was_gelaufen_ist(alte_db):
    """Für den Menschen nach einem missglückten Aktualisieren."""
    engine = engine_bauen(alte_db)
    wandern(engine)
    with engine.connect() as v:
        namen = {r[0] for r in v.execute(text("SELECT name FROM schema_wanderungen"))}
    assert namen == {s.name for s in SCHRITTE}


def test_das_protokoll_entscheidet_nichts(alte_db):
    """Es ist Dokumentation, nicht Logik.

    Wer das Protokoll löscht, darf die Datenbank damit nicht kaputtmachen:
    Ein erneuter Lauf prüft das Schema selbst und findet nichts zu tun.
    Andersherum -- ein Protokolleintrag ohne die Spalte -- darf die
    Wanderung nicht davon abhalten, sie doch anzulegen.
    """
    engine = engine_bauen(alte_db)
    wandern(engine)
    with engine.begin() as v:
        v.execute(text("DELETE FROM schema_wanderungen"))
    assert wandern(engine) == []

    with engine.begin() as v:
        v.execute(text("ALTER TABLE playbook_rules DROP COLUMN auto_check"))
        v.execute(
            text(
                "INSERT INTO schema_wanderungen (name, gelaufen_am)"
                " VALUES ('playbook_rules.auto_check', 'irgendwann')"
            )
        )
    assert wandern(engine) == ["playbook_rules.auto_check"]


# ---------------------------------------------------------------------------
# Damit es nicht noch einmal passiert
# ---------------------------------------------------------------------------

def test_jeder_schritt_zeigt_auf_eine_echte_spalte():
    """Ein Tippfehler im Schritt liefe sonst bei jedem Start ins Leere."""
    for schritt in SCHRITTE:
        tabelle = db.Base.metadata.tables.get(schritt.tabelle)
        assert tabelle is not None, f"{schritt.tabelle} gibt es nicht"
        assert schritt.spalte in tabelle.c, f"{schritt.name} gibt es nicht"


def test_jede_nachgereichte_spalte_ist_optional():
    """`ALTER TABLE ... ADD COLUMN NOT NULL` ginge an vorhandenen Zeilen schief.

    Und ein Vorgabewert wäre eine stille Erfindung: Die alten Zeilen
    bekämen eine Angabe, die nie gemacht wurde.
    """
    for schritt in SCHRITTE:
        spalte = db.Base.metadata.tables[schritt.tabelle].c[schritt.spalte]
        assert spalte.nullable, f"{schritt.name} ist nicht optional"
        assert "NOT NULL" not in schritt.typ.upper()


def test_jede_neue_spalte_hat_einen_wanderungsschritt():
    """Der wichtigste Test dieser Datei.

    `tests/schema_stand.json` hält den ältesten Schema-Stand fest, von dem
    aus jemand aktualisieren kann. Jede Spalte, die das heutige Modell
    darüber hinaus hat, braucht einen Schritt -- sonst startet die App bei
    diesem Jemand sauber und stirbt beim ersten Aufruf, der sie anfasst.

    Die Datei wird **nicht** mitgezogen. Sie ist ein Fixpunkt, kein
    Spiegel: Zöge man sie bei jeder Änderung nach, ginge der Test immer
    durch und prüfte nichts.
    """
    stand = json.loads(STAND.read_text())
    abgedeckt = {(s.tabelle, s.spalte) for s in SCHRITTE}

    fehlend = []
    for name, tabelle in sorted(db.Base.metadata.tables.items()):
        if name not in stand:
            # Eine ganz neue Tabelle legt `create_all` vollständig an.
            continue
        for spalte in tabelle.columns:
            if spalte.name in stand[name]:
                continue
            if (name, spalte.name) in abgedeckt:
                continue
            fehlend.append(f"{name}.{spalte.name}")

    assert not fehlend, (
        "Neue Spalten ohne Wanderungsschritt: "
        + ", ".join(fehlend)
        + ". Ohne sie bricht das Aktualisieren einer bestehenden Datenbank. "
        "Je einen Spaltenschritt in tradediary/db/wanderung.py ergänzen."
    )

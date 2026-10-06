"""Tests für Sicherung und Zurückspielen.

Eine Sicherung, die nie zurückgespielt wurde, ist keine Sicherung,
sondern eine Hoffnung -- und genau so stand es hier: Das Skript sicherte
und prüfte, aber den Weg zurück beschrieb nur das README, und niemand war
ihn je gegangen. Beim ersten Durchgang kamen drei Fehler heraus, jeder
davon hier nachgestellt:

1. ``gunzip -c sicherung.gz > datenbank.db`` legt das Ziel an, **bevor**
   das Entpacken läuft. Scheitert es, steht eine leere Datei da, wo das
   Journal war -- und das Original ist weg.
2. ``sudo -u tradediary gunzip … > datei`` schreibt als Aufrufer, nicht
   als `tradediary`: Die Umleitung macht die eigene Shell. Die Datenbank
   gehörte danach root, der Dienst läuft als `tradediary` -- und könnte
   in seine eigene Datenbank nicht schreiben.
3. ``--pruefen`` liess die vollständige, entpackte Datenbank in `/tmp`
   liegen, für alle lesbar, und räumte sie nie weg. Das ist der Befehl,
   den man vor jedem Zurückspielen laufen lässt.

Das Journal ist der Teil, der nicht nachwächst: Trades kommen aus MT5
wieder, Notizen nicht.
"""

from __future__ import annotations

import gzip
import importlib.util
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

from tradediary.db.repository import engine_bauen, schema_anlegen, session_factory


def _lade_skript():
    """`deploy/sicherung.py` liegt ausserhalb des Pakets."""
    pfad = Path(__file__).parent.parent / "deploy" / "sicherung.py"
    spec = importlib.util.spec_from_file_location("sicherung", pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules["sicherung"] = modul
    spec.loader.exec_module(modul)
    return modul


sicherung = _lade_skript()


def fuelle(pfad: Path, trades: int = 3) -> None:
    """Eine Datenbank mit genug Inhalt, dass sie als echt durchgeht.

    Über die Modelle, nicht über rohes SQL: Eine von Hand geschriebene
    INSERT-Zeile bricht bei der nächsten Spalte, und dann steht hier ein
    roter Test, der nichts über die Sicherung aussagt.
    """
    from datetime import datetime, timezone
    from decimal import Decimal

    from tradediary.db import models as db

    engine = engine_bauen(f"sqlite:///{pfad}")
    schema_anlegen(engine)
    with session_factory(engine)() as s:
        s.add(db.User(id=1, email="a@b.invalid", password_hash="x"))
        s.add(db.Account(id=1, user_id=1, label="K"))
        s.flush()
        for i in range(trades):
            s.add(
                db.Trade(
                    account_id=1,
                    position_id=i + 1,
                    symbol="EURUSD",
                    direction="long",
                    opened_at=datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                    volume=Decimal("1"),
                    exit_volume=Decimal("1"),
                    gross_pnl=Decimal("100"),
                    costs=Decimal("-7"),
                    net_pnl=Decimal("93"),
                    note=f"Notiz {i}",
                )
            )
            s.add(
                db.Deal(
                    ticket=i + 1,
                    account_id=1,
                    position_id=i + 1,
                    symbol="EURUSD",
                    type="buy",
                    entry="in",
                    volume=Decimal("1"),
                    price=Decimal("1.08"),
                    time_utc=datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                )
            )
        s.commit()
    # Sonst haelt der Verbindungspool die Datei offen -- und die Prüfung
    # auf "in Benutzung" schlaegt beim eigenen Testprozess an.
    engine.dispose()


def zaehle(pfad: Path, tabelle: str = "trades") -> int:
    v = sqlite3.connect(pfad)
    try:
        return v.execute(f"SELECT count(*) FROM {tabelle}").fetchone()[0]
    finally:
        v.close()


@pytest.fixture()
def welt(tmp_path):
    """Eine gefüllte Datenbank und ein Sicherungsordner."""
    live = tmp_path / "tradediary.db"
    fuelle(live)
    ordner = tmp_path / "sicherungen"
    gepackt = sicherung.sichere(live, ordner, behalten=30)
    return {"live": live, "ordner": ordner, "sicherung": gepackt, "tmp": tmp_path}


# ---------------------------------------------------------------------------
# Der Kreislauf
# ---------------------------------------------------------------------------

def test_sichern_und_zurueckspielen(welt):
    """Der Test, den es nie gab -- und der die drei Fehler zutage brachte."""
    v = sqlite3.connect(welt["live"])
    v.execute("DELETE FROM trades")
    v.execute("DELETE FROM deals")
    v.commit()
    v.close()
    assert zaehle(welt["live"]) == 0

    sicherung.zurueckspielen(welt["sicherung"], welt["live"])
    assert zaehle(welt["live"]) == 3


def test_die_notizen_kommen_wortgetreu_zurueck(welt):
    """Trades wachsen aus MT5 nach, Notizen nicht."""
    welt["live"].unlink()
    sicherung.zurueckspielen(welt["sicherung"], welt["live"])

    v = sqlite3.connect(welt["live"])
    notizen = [r[0] for r in v.execute("SELECT note FROM trades ORDER BY id")]
    v.close()
    assert notizen == ["Notiz 0", "Notiz 1", "Notiz 2"]


def test_die_bisherige_datenbank_wird_beiseitegelegt(welt):
    """Wer die falsche Sicherung erwischt, hat danach noch beides.

    Das dokumentierte `gunzip … > datei` konnte das nicht: Es überschrieb
    unwiederbringlich.
    """
    sicherung.zurueckspielen(welt["sicherung"], welt["live"])
    beiseite = list(welt["tmp"].glob("tradediary.db.vorher_*"))
    assert len(beiseite) == 1
    assert zaehle(beiseite[0]) == 3


# ---------------------------------------------------------------------------
# Die drei Fehler des dokumentierten Weges
# ---------------------------------------------------------------------------

def test_eine_leere_sicherung_ersetzt_nicht_alles_durch_nichts(welt, tmp_path):
    """Der gefährlichste Fall: gültig, aber leer.

    Sie besteht jede Integritätsprüfung. Ohne eine eigene Zählung ersetzte
    sie das ganze Journal durch ein leeres Schema.
    """
    leer = tmp_path / "leer.db"
    schema_anlegen(engine_bauen(f"sqlite:///{leer}"))
    gepackt = tmp_path / "leer.db.gz"
    with open(leer, "rb") as e, gzip.open(gepackt, "wb") as a:
        a.write(e.read())

    with pytest.raises(SystemExit) as fehler:
        sicherung.zurueckspielen(gepackt, welt["live"])
    assert "nichts ersetzen" in str(fehler.value)
    # Und vor allem: unangetastet.
    assert zaehle(welt["live"]) == 3


def test_eine_beschaedigte_sicherung_laesst_die_datenbank_in_ruhe(welt, tmp_path):
    """Der Fehler, den die Umleitung `>` nicht abfangen konnte.

    Sie legt das Ziel an, bevor das Entpacken läuft -- scheitert es, steht
    dort eine leere Datei. Hier wird erst danebengeschrieben.
    """
    kaputt = tmp_path / "kaputt.db.gz"
    with gzip.open(kaputt, "wb") as a:
        a.write(b"das ist keine Datenbank" * 50)

    with pytest.raises(SystemExit):
        sicherung.zurueckspielen(kaputt, welt["live"])
    assert zaehle(welt["live"]) == 3
    assert not list(welt["tmp"].glob("*.neu"))


def test_rechte_werden_von_der_ersetzten_datei_uebernommen(welt):
    """Sonst gehört die Datenbank hinterher dem Falschen.

    `sudo -u tradediary gunzip … > datei` schreibt als Aufrufer: Die
    Umleitung macht die eigene Shell, nicht sudo. Die Datei gehörte
    danach root, der Dienst läuft als `tradediary` -- und könnte in seine
    eigene Datenbank nicht schreiben.

    Besitzer lassen sich hier nicht umstellen, Rechte schon: Sie gehen
    denselben Weg durch `stat` und `chmod`.
    """
    os.chmod(welt["live"], 0o600)
    sicherung.zurueckspielen(welt["sicherung"], welt["live"])
    assert stat.S_IMODE(welt["live"].stat().st_mode) == 0o600


def test_pruefen_laesst_nichts_liegen(welt, tmp_path, monkeypatch):
    """Keine entpackte Kopie des Journals mehr in /tmp.

    Vorher lag dort nach jedem `--pruefen` eine vollständige,
    unverschlüsselte, für alle lesbare Datenbank -- und blieb liegen. Es
    sammelten sich also genau so viele Kopien an, wie man vorsichtig war.
    """
    vorher = set(Path("/tmp").glob("tradediary_*.db"))
    monkeypatch.setattr(
        sys, "argv", ["sicherung.py", "--pruefen", str(welt["sicherung"])]
    )
    sicherung.main()
    assert set(Path("/tmp").glob("tradediary_*.db")) == vorher


# ---------------------------------------------------------------------------
# Datenbank in Benutzung
# ---------------------------------------------------------------------------

def test_eine_offene_datenbank_wird_erkannt(welt):
    """Sonst bleibt das Zurückspielen still wirkungslos.

    Die API hält die alte Datei über ihren Dateideskriptor weiter offen
    und schreibt dort hinein; beim nächsten Neustart ist das alles weg --
    zusammen mit dem Eindruck, es habe funktioniert.
    """
    offen = sqlite3.connect(welt["live"])
    offen.execute("SELECT count(*) FROM trades").fetchone()
    try:
        assert sicherung.wer_hat_offen(welt["live"])
        with pytest.raises(SystemExit) as fehler:
            sicherung.zurueckspielen(welt["sicherung"], welt["live"])
        assert "in Benutzung" in str(fehler.value)
        assert "systemctl stop" in str(fehler.value)
    finally:
        offen.close()


def test_mit_trotzdem_geht_es_doch(welt):
    """Für den Fall, dass die Erkennung danebenliegt.

    Eine Sperre, die sich nicht aufheben lässt, ist irgendwann der Grund,
    warum jemand das Skript umgeht und wieder zu `gunzip` greift.
    """
    offen = sqlite3.connect(welt["live"])
    offen.execute("SELECT count(*) FROM trades").fetchone()
    try:
        sicherung.zurueckspielen(welt["sicherung"], welt["live"], trotzdem=True)
        assert zaehle(welt["live"]) == 3
    finally:
        offen.close()


def test_eine_geschlossene_datenbank_haelt_niemand_offen(welt):
    """Gegenprobe: Sonst wäre die Erkennung wertlos, weil immer wahr."""
    assert sicherung.wer_hat_offen(welt["live"]) == []


# ---------------------------------------------------------------------------
# Die Sicherungsseite, die es schon gab -- aber ungeprüft
# ---------------------------------------------------------------------------

def test_eine_leere_datenbank_wird_gar_nicht_erst_gesichert(tmp_path):
    """Sonst verdrängt sie nach 30 Tagen alle brauchbaren Sicherungen."""
    leer = tmp_path / "leer.db"
    schema_anlegen(engine_bauen(f"sqlite:///{leer}"))
    with pytest.raises(SystemExit) as fehler:
        sicherung.sichere(leer, tmp_path / "ziel", behalten=30)
    assert "verworfen" in str(fehler.value)
    assert not list((tmp_path / "ziel").glob("*.db"))


def test_alte_sicherungen_werden_aufgeraeumt(welt, tmp_path):
    """Eine volle Platte ist kein harmloser Fehler.

    Danach kann die API nicht mehr schreiben und der Sammler liefert ins
    Leere -- und beides sieht nach einem Fehler in der App aus.
    """
    for i in range(5):
        (welt["ordner"] / f"tradediary_2026-01-0{i}_0400.db.gz").write_bytes(b"x")
    sicherung.aufraeumen(welt["ordner"], behalten=3)
    assert len(list(welt["ordner"].glob("*.db.gz"))) == 3


def test_eine_sicherung_ohne_pflichttabellen_wird_abgelehnt(tmp_path):
    """Sie stammt dann aus einer anderen Version -- oder ist keine."""
    fremd = tmp_path / "fremd.db"
    v = sqlite3.connect(fremd)
    v.execute("CREATE TABLE irgendwas (a INTEGER)")
    v.commit()
    v.close()
    with pytest.raises(SystemExit) as fehler:
        sicherung.pruefe(fremd)
    assert "Tabellen fehlen" in str(fehler.value)

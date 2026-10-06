"""Tests für die systemd-Units.

Sie laufen hier ohne systemd -- geprüft wird der Inhalt der Dateien, nicht
ihr Verhalten unter einem laufenden Init. Das reicht für die beiden
Fehler, die der erste echte Einsatz auf dem Zielrechner gezeigt hat, und
beide waren unsichtbar, solange niemand hinsah:

1. **Die Oberfläche hörte auf allen Schnittstellen.** Die Unit setzte
   `Environment=HOSTNAME=127.0.0.1` und behauptete im Kommentar daneben
   „Nur Loopback". `next start` liest diese Variable aber nicht.
   Nachgemessen mit `ss`: `0.0.0.0:3000`. Damit wäre das Journal
   unverschlüsselt im ganzen Heimnetz erreichbar gewesen -- am Proxy
   vorbei, der genau das verhindern soll. Mit `-H 127.0.0.1` als Flag
   steht dort `127.0.0.1:3000`.

2. **Ein Dienst, der nicht starten kann, lief für immer im Kreis.**
   systemd erlaubt voreingestellt 5 Starts in 10 Sekunden; mit
   `RestartSec=5` wird diese Grenze nie erreicht. Auf dem Zielrechner
   stand der Zähler bei 211.661 Versuchen -- knapp zwei Wochen
   Dauerschleife, die das Journal zumüllt und die eigentliche
   Fehlermeldung darin begräbt.

   Die Bremse dagegen gehört in `[Unit]`. In `[Service]` meldet systemd
   „Unknown key name" und ignoriert sie stillschweigend -- die Schleife
   liefe weiter, und die Unit sähe repariert aus.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

UNITS = Path(__file__).parent.parent / "deploy"
DIENSTE = sorted(UNITS.glob("*.service"))


def lies(pfad: Path) -> configparser.ConfigParser:
    """systemd-Dateien sind INI-artig, mit Mehrfachschlüsseln."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(pfad.read_text())
    return parser


def test_es_gibt_ueberhaupt_units():
    assert len(DIENSTE) == 3, [p.name for p in DIENSTE]


def test_die_oberflaeche_hoert_nur_auf_loopback():
    """Der erste der beiden Fehler.

    Die Adresse muss am Befehl stehen. Über die Umgebung gesetzt wird sie
    von `next start` ignoriert -- die Unit sähe richtig aus und bände doch
    an 0.0.0.0.
    """
    unit = lies(UNITS / "tradediary-web.service")
    start = unit["Service"]["ExecStart"]
    assert "-H 127.0.0.1" in start or "--hostname 127.0.0.1" in start, start

    # Und die Variable darf nicht zurückkommen: Sie wirkt nicht und würde
    # beim Lesen den Eindruck erwecken, die Sache sei geregelt.
    text = (UNITS / "tradediary-web.service").read_text()
    assert "Environment=HOSTNAME=" not in text


def test_die_api_hoert_nur_auf_loopback():
    """Bei uvicorn steht die Adresse ohnehin am Befehl -- festhalten."""
    start = lies(UNITS / "tradediary-api.service")["Service"]["ExecStart"]
    assert "--host 127.0.0.1" in start, start


@pytest.mark.parametrize(
    "name", ["tradediary-api.service", "tradediary-web.service"]
)
def test_ein_dienst_gibt_irgendwann_auf(name):
    """Der zweite Fehler: 211.661 Versuche sind keine Fehlerbehandlung.

    Ein Dienst, der endlos neu startet, verbirgt seinen eigenen Grund im
    Protokoll. Nach der Grenze bleibt er auf `failed` stehen, wo man ihn
    sieht.
    """
    unit = lies(UNITS / name)
    assert unit["Service"].get("Restart") == "always"
    assert "StartLimitIntervalSec" in unit["Unit"], (
        f"{name}: keine Grenze -- der Dienst läuft bei einem Startfehler "
        "für immer im Kreis"
    )
    assert int(unit["Unit"]["StartLimitBurst"]) > 0


@pytest.mark.parametrize(
    "name", ["tradediary-api.service", "tradediary-web.service"]
)
def test_die_bremse_steht_im_richtigen_abschnitt(name):
    """In [Service] ignoriert systemd sie wortlos.

    Das ist die heimtückische Variante: Die Unit sieht repariert aus, der
    Dienst läuft weiter im Kreis, und `systemd-analyze verify` sagt es nur,
    wenn man es aufruft.
    """
    unit = lies(UNITS / name)
    for schluessel in ("StartLimitIntervalSec", "StartLimitBurst"):
        assert schluessel not in unit["Service"], (
            f"{name}: {schluessel} steht in [Service] und wird ignoriert"
        )


@pytest.mark.parametrize("name", [p.name for p in DIENSTE])
def test_jeder_dienst_laeuft_unter_dem_eigenen_nutzer(name):
    """Niemals als root -- auch die Sicherung nicht."""
    unit = lies(UNITS / name)
    assert unit["Service"].get("User") == "tradediary", name


@pytest.mark.parametrize("name", [p.name for p in DIENSTE])
def test_jeder_dienst_ist_abgesichert(name):
    """Die Härtung ist der Grund, warum der Dienst ins Netz zeigen darf."""
    unit = lies(UNITS / name)["Service"]
    assert unit.get("NoNewPrivileges") == "true", name
    assert unit.get("ProtectSystem") == "strict", name
    assert unit.get("ProtectHome") == "true", name


def test_nur_die_sicherung_darf_schreiben():
    """Oberfläche und API liefern aus bzw. schreiben in die Datenbank.

    `ProtectSystem=strict` ohne `ReadWritePaths` heisst: nirgends
    schreiben. Wer das später lockert, soll es hier bemerken.
    """
    web = lies(UNITS / "tradediary-web.service")["Service"]
    assert "ReadWritePaths" not in web

    for name in ("tradediary-api.service", "tradediary-sicherung.service"):
        unit = lies(UNITS / name)["Service"]
        pfade = unit.get("ReadWritePaths", "")
        assert "/var/lib/tradediary" in pfade or "/var/backups" in pfade, name

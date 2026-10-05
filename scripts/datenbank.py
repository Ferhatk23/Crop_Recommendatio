"""Gemeinsames Vorspiel für die Verwaltungsskripte.

Sie laufen alle unter `sudo -u tradediary …`, und genau das ist die Falle:
**sudo wirft die Umgebung weg.** `TRADEDIARY_DB` ist dann nicht gesetzt,
die Skripte fallen auf den relativen Standardwert zurück, und SQLite legt
beim ersten Zugriff bereitwillig eine neue, leere Datenbank an -- im
Arbeitsverzeichnis.

Nachgemessen beim ersten echten Installationslauf: Der dokumentierte
Befehl

    sudo -u tradediary /opt/tradediary/.venv/bin/python \\
         /opt/tradediary/scripts/nutzer.py anlegen ich@example.com

legte den Nutzer in `/opt/tradediary/tradediary.db` an statt in
`/var/lib/tradediary/tradediary.db`. Das Skript meldete „Angelegt",
alles sah richtig aus, und die Anmeldung scheiterte danach mit
„E-Mail oder Passwort stimmt nicht" -- einer Meldung, die in die
völlig falsche Richtung zeigt. Wer das nicht weiss, sucht den Fehler
beim Passwort und findet ihn nie.

Deshalb hier die Regel: **Eine Datenbank wird nie beiläufig erzeugt.**
Zeigt die URL auf eine SQLite-Datei, die es nicht gibt, bricht das
Skript ab und sagt, was vermutlich fehlt. Wer wirklich eine neue
anlegen will, sagt es ausdrücklich.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tradediary.db.repository import engine_bauen, schema_anlegen, session_factory

STANDARD = "sqlite:///tradediary.db"


def datenbank_url() -> str:
    return os.environ.get("TRADEDIARY_DB", STANDARD)


def _pfad(url: str) -> Path | None:
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///") :])
    return None


def sitzung(*, anlegen_erlaubt: bool = False):
    """Eine Sitzung auf der Datenbank -- oder eine Erklärung, warum nicht."""
    url = datenbank_url()
    datei = _pfad(url)

    if datei is not None and not datei.exists() and not anlegen_erlaubt:
        gesetzt = "TRADEDIARY_DB" in os.environ
        print(
            f"Diese Datenbank gibt es nicht: {datei.absolute()}\n",
            file=sys.stderr,
        )
        if not gesetzt:
            print(
                "  TRADEDIARY_DB ist nicht gesetzt, also gilt der Standardwert\n"
                f"  {STANDARD} -- relativ zum Arbeitsverzeichnis.\n"
                "\n"
                "  Unter sudo passiert das leicht: sudo gibt die Umgebung nicht\n"
                "  weiter. Den Wert ausdrücklich mitgeben:\n"
                "\n"
                "    sudo -u tradediary env \\\n"
                "      TRADEDIARY_DB=sqlite:////var/lib/tradediary/tradediary.db \\\n"
                "      /opt/tradediary/.venv/bin/python "
                f"/opt/tradediary/scripts/{Path(sys.argv[0]).name} …\n"
                "\n"
                "  Wäre hier einfach eine neue Datenbank entstanden, stünde der\n"
                "  Eintrag am falschen Ort -- und die Anmeldung schlüge später\n"
                "  mit „E-Mail oder Passwort stimmt nicht\" fehl.",
                file=sys.stderr,
            )
        else:
            print(
                "  TRADEDIARY_DB zeigt dorthin, aber die Datei fehlt.\n"
                "  Tippfehler im Pfad? Oder soll hier wirklich eine neue\n"
                "  Datenbank entstehen? Dann mit --neu starten.",
                file=sys.stderr,
            )
        raise SystemExit(2)

    engine = engine_bauen(url)
    schema_anlegen(engine)
    return session_factory(engine)()

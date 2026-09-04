"""Sichert die TradeDiary-Datenbank -- und prüft die Sicherung nach.

Ein Journal, das man verliert, ist schlimmer als keins: Die Trades wachsen
aus MT5 nach, die Notizen nicht. Was man selbst geschrieben hat, gibt es
genau einmal.

Drei Dinge macht dieses Skript anders als ein `cp`:

* **Es kopiert im laufenden Betrieb sicher.** SQLites eigene
  Sicherungs-API zieht einen in sich stimmigen Abzug, auch während die
  API gerade schreibt. Ein `cp` auf eine offene Datenbank liefert
  gelegentlich eine halbe Transaktion -- und das merkt man erst beim
  Zurückspielen.
* **Es prüft die Kopie.** `PRAGMA integrity_check` plus eine Zählung der
  Trades. Eine Sicherung, die nie geöffnet wurde, ist keine Sicherung,
  sondern eine Hoffnung.
* **Es sagt Bescheid, wenn nichts drin ist.** Eine gültige, leere
  Datenbank ist der gefährlichste Fall: Sie besteht jede Prüfung und
  ersetzt beim Zurückspielen alles durch nichts.

    python deploy/sicherung.py
    python deploy/sicherung.py --ziel /pfad --behalten 30
    python deploy/sicherung.py --pruefen datei.db     # eine Sicherung ansehen
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

STANDARD_QUELLE = os.environ.get("TRADEDIARY_DB", "sqlite:///tradediary.db")
STANDARD_ZIEL = os.environ.get("TRADEDIARY_SICHERUNG", "/var/backups/tradediary")
STANDARD_BEHALTEN = 30

#: Tabellen, die nach dem Zurückspielen da sein müssen. Fehlt eine, ist
#: die Sicherung aus einer anderen Version oder unvollständig.
PFLICHT = ("users", "accounts", "deals", "trades", "journal_entries", "tags")


def pfad_aus_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///") :])
    if url.startswith("sqlite://"):
        raise SystemExit("Eine Datenbank im Speicher lässt sich nicht sichern.")
    raise SystemExit(
        f"Nur SQLite wird hier gesichert, nicht: {url}\n"
        "  Bei Postgres nimmt man pg_dump."
    )


def pruefe(datei: Path) -> dict:
    """Öffnet eine Datenbank und schaut nach, ob sie brauchbar ist.

    Jeder Fehlschlag endet in einer Zeile Klartext, nie in einem
    Stacktrace. Das ist kein Schönheitsfehler: Dieses Skript läuft
    nachts unbeaufsichtigt, und was im Protokoll steht, muss sich in
    einer Zeile erfassen lassen. Einen Stacktrace liest niemand -- und
    eine Sicherung, deren Fehlschlag niemand liest, gibt es nicht.

    Eine schwer beschädigte Datei lässt `integrity_check` schon gar nicht
    mehr laufen: SQLite wirft dann, statt einen Befund zurückzugeben.
    Beide Wege müssen hier ankommen.
    """
    try:
        with sqlite3.connect(f"file:{datei}?mode=ro", uri=True) as verbindung:
            ergebnis = verbindung.execute("PRAGMA integrity_check").fetchone()[0]
            if ergebnis != "ok":
                raise SystemExit(f"Sicherung beschädigt: {ergebnis}")

            vorhanden = {
                zeile[0]
                for zeile in verbindung.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            fehlend = [t for t in PFLICHT if t not in vorhanden]
            if fehlend:
                raise SystemExit(
                    f"Tabellen fehlen: {', '.join(fehlend)}\n"
                    "  Die Sicherung stammt aus einer anderen Version "
                    "oder ist unvollständig."
                )

            zahlen = {
                tabelle: verbindung.execute(
                    f"SELECT count(*) FROM {tabelle}"
                ).fetchone()[0]
                for tabelle in PFLICHT
            }
    except sqlite3.DatabaseError as fehler:
        raise SystemExit(f"Sicherung unbrauchbar: {fehler}")

    return zahlen


def sichere(quelle: Path, ziel_ordner: Path, behalten: int) -> Path:
    if not quelle.exists():
        raise SystemExit(f"Keine Datenbank unter {quelle}")

    ziel_ordner.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    roh = ziel_ordner / f"tradediary_{stempel}.db"

    # SQLites eigene Sicherungs-API: konsistent auch während geschrieben wird.
    with sqlite3.connect(f"file:{quelle}?mode=ro", uri=True) as auf, \
            sqlite3.connect(roh) as zu:
        auf.backup(zu)

    zahlen = pruefe(roh)

    # Der gefährlichste Fall: gültig, aber leer. Beim Zurückspielen ersetzt
    # so eine Sicherung alles durch nichts -- und sie besteht jede Prüfung.
    if zahlen["trades"] == 0 and zahlen["deals"] == 0:
        roh.unlink()
        raise SystemExit(
            "Sicherung enthält weder Deals noch Trades -- verworfen.\n"
            "  Zeigt TRADEDIARY_DB auf die richtige Datei?"
        )

    gepackt = Path(str(roh) + ".gz")
    with open(roh, "rb") as ein, gzip.open(gepackt, "wb", compresslevel=6) as aus:
        shutil.copyfileobj(ein, aus)
    roh.unlink()

    groesse = gepackt.stat().st_size
    print(
        f"{gepackt.name}  {groesse / 1024:.0f} kB  "
        f"{zahlen['trades']} Trades, {zahlen['deals']} Ausführungen, "
        f"{zahlen['journal_entries']} Tagesnotizen"
    )

    aufraeumen(ziel_ordner, behalten)
    return gepackt


def aufraeumen(ordner: Path, behalten: int) -> None:
    """Alte Sicherungen wegräumen -- sonst läuft die Platte voll.

    Die Platte vollzuschreiben ist kein harmloser Fehler: Danach kann die
    API nicht mehr schreiben, und der Sammler liefert ins Leere.
    """
    dateien = sorted(
        ordner.glob("tradediary_*.db.gz"), key=lambda p: p.name, reverse=True
    )
    for alt in dateien[behalten:]:
        alt.unlink()
        print(f"  entfernt: {alt.name}")


def main() -> None:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--quelle", default=STANDARD_QUELLE)
    zerleger.add_argument("--ziel", default=STANDARD_ZIEL)
    zerleger.add_argument("--behalten", type=int, default=STANDARD_BEHALTEN)
    zerleger.add_argument(
        "--pruefen", metavar="DATEI", help="Eine vorhandene Sicherung ansehen"
    )
    argumente = zerleger.parse_args()

    if argumente.pruefen:
        datei = Path(argumente.pruefen)
        if datei.suffix == ".gz":
            entpackt = Path("/tmp") / datei.stem
            with gzip.open(datei, "rb") as ein, open(entpackt, "wb") as aus:
                shutil.copyfileobj(ein, aus)
            datei = entpackt
        zahlen = pruefe(datei)
        print("Sicherung in Ordnung:")
        for tabelle, anzahl in zahlen.items():
            print(f"  {tabelle:<16} {anzahl}")
        return

    quelle = (
        Path(argumente.quelle)
        if not argumente.quelle.startswith("sqlite")
        else pfad_aus_url(argumente.quelle)
    )
    sichere(quelle, Path(argumente.ziel), argumente.behalten)


if __name__ == "__main__":
    main()

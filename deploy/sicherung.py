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
    python deploy/sicherung.py --pruefen datei.db.gz        # eine Sicherung ansehen
    python deploy/sicherung.py --zurueckspielen datei.db.gz # und wieder einspielen
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
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
    # `with sqlite3.connect(...)` schliesst *nicht* -- der Kontextmanager
    # verwaltet nur die Transaktion. Ohne das ausdrueckliche `close()`
    # bleibt die Datei offen, bis der Speicherbereiniger vorbeikommt, und
    # `zurueckspielen` haelt dann seine eigene Sicherung fest.
    verbindung = None
    try:
        verbindung = sqlite3.connect(f"file:{datei}?mode=ro", uri=True)
        with verbindung:
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
    finally:
        if verbindung is not None:
            verbindung.close()

    return zahlen


def sichere(quelle: Path, ziel_ordner: Path, behalten: int) -> Path:
    if not quelle.exists():
        raise SystemExit(f"Keine Datenbank unter {quelle}")

    ziel_ordner.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    roh = ziel_ordner / f"tradediary_{stempel}.db"

    # SQLites eigene Sicherungs-API: konsistent auch während geschrieben wird.
    auf = sqlite3.connect(f"file:{quelle}?mode=ro", uri=True)
    zu = sqlite3.connect(roh)
    try:
        auf.backup(zu)
    finally:
        # Ausdrücklich, aus demselben Grund wie in `pruefe`: Der
        # Kontextmanager von sqlite3 schliesst nicht.
        zu.close()
        auf.close()

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


def entpacke(datei: Path, ordner: Path) -> Path:
    """Packt eine `.gz`-Sicherung in einen eigenen Ordner aus.

    Nicht nach `/tmp` mit vorhersagbarem Namen: Dort lag nach jedem
    `--pruefen` eine vollständige, unverschlüsselte Kopie des Journals,
    für alle lesbar, und wurde nie weggeräumt. Das ist der Befehl, den man
    vor jedem Zurückspielen laufen lässt -- es sammelten sich also genau
    so viele Kopien an, wie man vorsichtig war.
    """
    if datei.suffix != ".gz":
        return datei
    ziel = ordner / datei.stem
    with gzip.open(datei, "rb") as ein, open(ziel, "wb") as aus:
        shutil.copyfileobj(ein, aus)
    return ziel


def wer_hat_offen(datei: Path) -> list[str]:
    """Welche Prozesse die Datei offen haben. Leer heisst: keiner.

    Ohne diese Prüfung ist ein Zurückspielen im laufenden Betrieb still
    wirkungslos: Die API hält die alte Datei über ihren Dateideskriptor
    weiter offen, schreibt dort hinein, und beim nächsten Neustart sind
    diese Schreibvorgänge weg -- zusammen mit dem Eindruck, das
    Zurückspielen habe funktioniert.
    """
    offen = []
    ziel = str(datei.resolve())
    for prozess in Path("/proc").iterdir():
        if not prozess.name.isdigit():
            continue
        try:
            for fd in (prozess / "fd").iterdir():
                if str(fd.resolve()) == ziel:
                    name = (prozess / "comm").read_text().strip()
                    offen.append(f"{name} (PID {prozess.name})")
                    break
        except (PermissionError, FileNotFoundError, OSError):
            # Prozesse kommen und gehen, während wir hier lesen.
            continue
    return offen


def zurueckspielen(sicherung: Path, ziel: Path, *, trotzdem: bool = False) -> None:
    """Spielt eine Sicherung ein -- in dieser Reihenfolge, aus Gründen.

    Die drei Fallen, die das dokumentierte `gunzip -c … > datei` hatte,
    jede davon hier nachgemessen:

    1. **Die Umleitung legt das Ziel an, bevor der Befehl läuft.** Scheitert
       das Entpacken, steht eine *leere* Datei da, wo das Journal war --
       und das Original ist weg. Hier wird erst daneben geschrieben und
       am Ende umbenannt; ein Fehlschlag lässt die alte Datei unberührt.
    2. **`sudo -u tradediary … > datei` schreibt als Aufrufer.** Die
       Umleitung macht die eigene Shell, nicht sudo. Die Datei gehörte
       danach root, der Dienst läuft als `tradediary` -- und könnte in
       seine eigene Datenbank nicht schreiben. Hier werden Besitzer und
       Rechte von der Datei übernommen, die ersetzt wird.
    3. **Es prüfte nichts.** Eine beschädigte oder leere Sicherung ersetzte
       alles durch nichts. Hier wird vorher geöffnet und gezählt.

    Und was das `gunzip` gar nicht konnte: Die Datei, die ersetzt wird,
    wird vorher beiseitegelegt. Wer die falsche Sicherung erwischt, hat
    danach noch beides.
    """
    if not sicherung.exists():
        raise SystemExit(f"Keine Sicherung unter {sicherung}")

    laeuft = wer_hat_offen(ziel) if ziel.exists() else []
    if laeuft and not trotzdem:
        raise SystemExit(
            "Die Datenbank ist in Benutzung: " + ", ".join(laeuft) + "\n"
            "  Erst anhalten, sonst schreibt der laufende Dienst weiter in\n"
            "  die alte Datei und das Zurückspielen bleibt wirkungslos:\n"
            "    sudo systemctl stop tradediary-api tradediary-web"
        )

    with tempfile.TemporaryDirectory(prefix="tradediary-ruecklauf-") as ordner:
        entpackt = entpacke(sicherung, Path(ordner))
        zahlen = pruefe(entpackt)
        if zahlen["trades"] == 0 and zahlen["deals"] == 0:
            raise SystemExit(
                "Die Sicherung enthält weder Deals noch Trades.\n"
                "  Sie würde alles durch nichts ersetzen -- abgebrochen."
            )

        # Erst danebenlegen, dann umbenennen: Ein Umbenennen innerhalb
        # desselben Dateisystems ist unteilbar. Es gibt keinen Moment, in
        # dem dort eine halbe Datenbank steht.
        ziel.parent.mkdir(parents=True, exist_ok=True)
        neben = ziel.with_name(ziel.name + ".neu")
        shutil.copyfile(entpackt, neben)

        if ziel.exists():
            # Besitzer und Rechte von der Datei übernehmen, die ersetzt
            # wird -- sonst gehört die Datenbank hinterher dem Falschen.
            stand = ziel.stat()
            os.chown(neben, stand.st_uid, stand.st_gid)
            os.chmod(neben, stand.st_mode & 0o777)

            beiseite = ziel.with_name(
                f"{ziel.name}.vorher_{datetime.now(timezone.utc):%Y-%m-%d_%H%M}"
            )
            ziel.replace(beiseite)
            print(f"  bisherige Datenbank beiseitegelegt: {beiseite.name}")

        neben.replace(ziel)

    print(
        f"Zurückgespielt: {zahlen['trades']} Trades, "
        f"{zahlen['deals']} Ausführungen, "
        f"{zahlen['journal_entries']} Tagesnotizen"
    )
    print("  Jetzt die Dienste wieder starten:")
    print("    sudo systemctl start tradediary-api tradediary-web")


def main() -> None:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--quelle", default=STANDARD_QUELLE)
    zerleger.add_argument("--ziel", default=STANDARD_ZIEL)
    zerleger.add_argument("--behalten", type=int, default=STANDARD_BEHALTEN)
    zerleger.add_argument(
        "--pruefen", metavar="DATEI", help="Eine vorhandene Sicherung ansehen"
    )
    zerleger.add_argument(
        "--zurueckspielen",
        metavar="DATEI",
        help="Eine Sicherung einspielen. Prüft sie vorher und legt die "
        "bisherige Datenbank beiseite.",
    )
    zerleger.add_argument(
        "--trotzdem",
        action="store_true",
        help="Auch zurückspielen, wenn die Datenbank in Benutzung ist",
    )
    argumente = zerleger.parse_args()

    quelle = (
        Path(argumente.quelle)
        if not argumente.quelle.startswith("sqlite")
        else pfad_aus_url(argumente.quelle)
    )

    if argumente.pruefen:
        # Eigener Ordner statt /tmp, und er verschwindet wieder: Sonst
        # bliebe nach jeder Prüfung eine vollständige, für alle lesbare
        # Kopie des Journals liegen.
        with tempfile.TemporaryDirectory(prefix="tradediary-pruefung-") as ordner:
            zahlen = pruefe(entpacke(Path(argumente.pruefen), Path(ordner)))
        print("Sicherung in Ordnung:")
        for tabelle, anzahl in zahlen.items():
            print(f"  {tabelle:<16} {anzahl}")
        return

    if argumente.zurueckspielen:
        zurueckspielen(
            Path(argumente.zurueckspielen), quelle, trotzdem=argumente.trotzdem
        )
        return

    sichere(quelle, Path(argumente.ziel), argumente.behalten)


if __name__ == "__main__":
    main()

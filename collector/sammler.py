"""Der MT5-Sammler.

Läuft unter Wine auf dem Dauerrechner, neben dem MT5-Terminal. Er liest
die Handelshistorie und schickt sie an die TradeDiary-API. Mehr nicht.

**Er rechnet nichts.** Keine Round-Trips, keine Kennzahlen, keine
Zeitzonenlogik über das Nötigste hinaus. Der Grund steht in
`tradediary/sync/mt5_source.py`: Diese Datei sitzt auf dem brüchigsten
Stück der Kette -- Wine, ein fremdes Python, ein Terminal, das sich
neu startet. Was hier nicht steht, kann hier nicht kaputtgehen. Alles
Denkbare passiert auf der anderen Seite, wo es sich testen lässt.

Abhängigkeiten: `MetaTrader5` und die Standardbibliothek. Kein
`requests`, kein `pydantic` -- jede Bibliothek mehr ist eine, die unter
Wine schiefgehen kann.

## Kein Expert Advisor

Wichtig für Prop-Konten: Das hier ist **kein EA**. Ein EA läuft im
Terminal, kann handeln und braucht bei Alpha Capital vorherige
Genehmigung. Dieses Skript ist ein externes Programm, das über die
offizielle Python-Anbindung *liest*.

Und es liest wirklich nur: Das Investor-Passwort (read-only) reicht
vollkommen. Nimm niemals das Master-Passwort -- ein Fehler in diesem
Skript könnte damit Positionen schließen.

## Einrichtung

    # .env neben diesem Skript, niemals ins Repository
    MT5_LOGIN=12345678
    MT5_PASSWORT=dein-investor-passwort
    MT5_SERVER=AlphaCapital-Live02
    MT5_PFAD=C:\\Program Files\\MetaTrader 5\\terminal64.exe
    TRADEDIARY_URL=http://192.168.1.42:8000
    TRADEDIARY_TOKEN=...   # aus scripts/marke.py anlegen

    python sammler.py            # einmal abgleichen
    python sammler.py --dauer    # alle 5 Minuten
    python sammler.py --pruefen  # nur Verbindung und Marke testen
    python sammler.py --tage 365 # Alt-Historie nachholen
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Einstellungen
# --------------------------------------------------------------------------

HIER = os.path.dirname(os.path.abspath(__file__))

#: Symbole, an denen der Zeitversatz gemessen wird. Mehrere, weil eins
#: beim Broker anders heißen kann (EURUSD.r, EURUSDm) oder nicht in der
#: Marktübersicht steht.
MESS_SYMBOLE = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "EURUSD.r", "EURUSDm")

#: Wie lange zwischen den beiden Ticks der Lebendprüfung gewartet wird.
LEBEND_PAUSE = 1.5

#: Wie weit jeder Lauf über den letzten bekannten Stand zurückgreift.
#: Kostet nichts, weil Dubletten serverseitig durchfallen, und fängt
#: nachträglich gebuchte Swaps und Korrekturen ein.
UEBERLAPPUNG_TAGE = 3

#: Deals je Anfrage. MT5 liefert Jahre auf einmal; eine Lieferung mit
#: 50.000 Deals würde die Anfrage aber unnötig groß machen.
STAPEL = 2000


def lade_env(pfad: str) -> None:
    """Eine schlichte .env-Leserei -- ohne Abhängigkeit.

    Vorhandene Umgebungsvariablen gewinnen: Wer beim Aufruf etwas setzt,
    will das auch benutzen.
    """
    if not os.path.exists(pfad):
        return
    with open(pfad, "r", encoding="utf-8") as datei:
        for zeile in datei:
            zeile = zeile.strip()
            if not zeile or zeile.startswith("#") or "=" not in zeile:
                continue
            schluessel, _, wert = zeile.partition("=")
            os.environ.setdefault(schluessel.strip(), wert.strip().strip("\"'"))


def melde(text: str) -> None:
    """Ausgabe mit Zeitstempel -- der Sammler läuft im Hintergrund."""
    print(f"[{datetime.now().strftime('%d.%m. %H:%M:%S')}] {text}", flush=True)


# --------------------------------------------------------------------------
# MT5
# --------------------------------------------------------------------------

def verbinde(mt5) -> None:
    """Baut die Verbindung zum Terminal auf."""
    login = os.environ.get("MT5_LOGIN")
    passwort = os.environ.get("MT5_PASSWORT")
    server = os.environ.get("MT5_SERVER")
    pfad = os.environ.get("MT5_PFAD")

    argumente = {}
    if pfad:
        argumente["path"] = pfad
    if login and passwort and server:
        argumente.update(
            {"login": int(login), "password": passwort, "server": server}
        )

    if not mt5.initialize(**argumente):
        code, text = mt5.last_error()
        raise SystemExit(
            f"MT5 antwortet nicht ({code}: {text}).\n"
            "  - Läuft das Terminal?\n"
            "  - Stimmen MT5_LOGIN, MT5_PASSWORT und MT5_SERVER?\n"
            "  - Ist in den Terminal-Einstellungen unter 'Expert Advisors'\n"
            "    der Algo-Handel *nicht* nötig -- gelesen wird auch ohne."
        )

    konto = mt5.account_info()
    if konto is None:
        raise SystemExit("Verbunden, aber kein Konto sichtbar. Anmeldedaten prüfen.")
    melde(
        f"Verbunden: {konto.login} auf {konto.server} "
        f"({konto.currency}, {'Demo' if konto.trade_mode == 0 else 'Live'})"
    )


def miss_versatz(mt5) -> int | None:
    """Der Zeitversatz des Broker-Servers gegenüber UTC, in Sekunden.

    Zweimal messen, dazwischen kurz warten: Rückt der Tick vor, ist der
    Markt offen und der Zeitstempel frisch. Steht er still, wird **nicht**
    gemessen -- ein 20 Minuten alter Tick ergäbe einen sauber gerundeten,
    plausibel aussehenden und falschen Versatz. Der verschöbe dann jeden
    Trade um Stunden, und zwar in allen Ansichten gleich, also
    unauffällig.

    `None` heißt "gerade nicht messbar". Die API behält dann den zuletzt
    bekannten Wert, statt auf UTC zurückzufallen.
    """
    erste: dict[str, float] = {}
    for symbol in MESS_SYMBOLE:
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None and tick.time:
            erste[symbol] = tick.time

    if not erste:
        melde("Kein Symbol für die Zeitmessung gefunden -- Versatz bleibt unverändert.")
        return None

    time.sleep(LEBEND_PAUSE)

    for symbol, vorher in erste.items():
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or not tick.time:
            continue
        if tick.time > vorher:
            # Der Markt lebt: Dieser Zeitstempel ist Sekunden alt.
            roh = (
                datetime.fromtimestamp(tick.time, tz=timezone.utc)
                - datetime.now(timezone.utc)
            ).total_seconds()
            if not -12 * 3600 <= roh <= 14 * 3600:
                continue
            versatz = int(round(roh / 900) * 900)
            melde(
                f"Serverzeit gemessen an {symbol}: "
                f"UTC{versatz / 3600:+g} h"
            )
            return versatz

    melde("Markt geschlossen -- Zeitversatz nicht messbar, bleibt unverändert.")
    return None


def hole_deals(mt5, von: datetime, bis: datetime) -> list[dict]:
    """Die Historie im Zeitraum, als schlichte Wörterbücher.

    MT5 will die Grenzen in Serverzeit. Wir geben sie großzügig -- ein
    paar Stunden zu viel kosten nichts, weil Dubletten ohnehin
    durchfallen, und zu wenig verlöre Deals am Rand.
    """
    puffer = timedelta(hours=24)
    deals = mt5.history_deals_get(von - puffer, bis + puffer)

    if deals is None:
        code, text = mt5.last_error()
        if code == 1:  # RES_S_OK mit leerem Ergebnis
            return []
        raise RuntimeError(f"Historie nicht lesbar ({code}: {text})")

    heraus = []
    for d in deals:
        heraus.append(
            {
                "ticket": d.ticket,
                "time": d.time,
                "type": d.type,
                "entry": d.entry,
                "position_id": d.position_id,
                "symbol": d.symbol,
                "volume": d.volume,
                "price": d.price,
                "profit": d.profit,
                "commission": d.commission,
                "swap": d.swap,
                "fee": d.fee,
                # Den Stop liefert der Deal selbst nicht -- er steht an der
                # Order. Wird unten nachgetragen, wo es geht.
                "sl": 0.0,
            }
        )
    return heraus


def ergaenze_stops(mt5, deals: list[dict], von: datetime, bis: datetime) -> int:
    """Trägt den ursprünglichen Stop aus den Orders nach.

    Ohne ihn gibt es kein R-Multiple -- und R ist die einzige Kennzahl,
    die Trades verschiedener Größe vergleichbar macht. Der Deal selbst
    kennt den Stop nicht; er steht an der Order, die ihn ausgelöst hat.

    Nur für eröffnende Deals: Der Stop der schließenden Order ist der
    nachgezogene, nicht der ursprünglich riskierte.
    """
    puffer = timedelta(hours=24)
    orders = mt5.history_orders_get(von - puffer, bis + puffer)
    if not orders:
        return 0

    # Der Stop wird über die position_id zugeordnet, nicht über die
    # Order-Nummer: Bei Teilausführungen gehören mehrere Deals zu einer
    # Order, und alle riskieren denselben Stop.
    stops: dict[int, float] = {}
    for o in orders:
        if getattr(o, "sl", 0):
            stops.setdefault(o.position_id, o.sl)

    getroffen = 0
    for d in deals:
        if d["entry"] == 0 and d["position_id"] in stops:  # DEAL_ENTRY_IN
            d["sl"] = stops[d["position_id"]]
            getroffen += 1
    return getroffen


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def sende(pfad: str, rumpf: dict | None = None, methode: str = "POST") -> dict:
    """Schickt etwas an die API. Nur Standardbibliothek."""
    basis = os.environ.get("TRADEDIARY_URL", "http://127.0.0.1:8000").rstrip("/")
    marke = os.environ.get("TRADEDIARY_TOKEN")
    if not marke:
        raise SystemExit(
            "TRADEDIARY_TOKEN fehlt.\n"
            "  Anlegen auf dem Server: python scripts/marke.py anlegen <konto>"
        )

    daten = json.dumps(rumpf).encode("utf-8") if rumpf is not None else None
    anfrage = urllib.request.Request(
        basis + pfad,
        data=daten,
        method=methode,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {marke}",
        },
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=120) as antwort:
            return json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as fehler:
        text = fehler.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"API antwortet {fehler.code}: {text}")
    except urllib.error.URLError as fehler:
        raise RuntimeError(f"API nicht erreichbar unter {basis}: {fehler.reason}")


# --------------------------------------------------------------------------
# Ablauf
# --------------------------------------------------------------------------

def abgleichen(mt5, tage: int | None = None) -> dict:
    """Ein Durchlauf: messen, holen, schicken."""
    bis = datetime.now(timezone.utc)
    rueckblick = timedelta(days=tage if tage else UEBERLAPPUNG_TAGE)
    von = bis - rueckblick

    versatz = miss_versatz(mt5)
    deals = hole_deals(mt5, von, bis)
    mit_stop = ergaenze_stops(mt5, deals, von, bis)

    melde(
        f"{len(deals)} Ausführungen seit {von.strftime('%d.%m.%Y')}"
        f" ({mit_stop} mit Stop)"
    )

    if not deals:
        # Trotzdem melden: Ein Lauf ohne Deals ist ein Lebenszeichen und
        # muss sich von einem ausgefallenen Sammler unterscheiden.
        return sende(
            "/api/ingest/deals",
            {
                "deals": [],
                "server_utc_offset": versatz,
                "fetched_at": bis.isoformat(),
                "window_from": von.isoformat(),
                "window_to": bis.isoformat(),
                "collector": "mt5-wine",
            },
        )

    gesamt = {"deals_new": 0, "trades_total": 0, "problems": []}
    for start in range(0, len(deals), STAPEL):
        teil = deals[start : start + STAPEL]
        antwort = sende(
            "/api/ingest/deals",
            {
                "deals": teil,
                "server_utc_offset": versatz,
                "fetched_at": bis.isoformat(),
                "window_from": von.isoformat(),
                "window_to": bis.isoformat(),
                "collector": "mt5-wine",
            },
        )
        gesamt["deals_new"] += antwort.get("deals_new", 0)
        gesamt["trades_total"] = antwort.get("trades_total", 0)
        gesamt["problems"].extend(antwort.get("problems", []))

    melde(
        f"Übernommen: {gesamt['deals_new']} neu, "
        f"{gesamt['trades_total']} Trades im Konto"
    )
    for problem in gesamt["problems"][:5]:
        melde(f"  Beanstandung: {problem}")
    return gesamt


def pruefen(mt5) -> None:
    """Verbindung und Marke testen, ohne etwas zu schicken."""
    verbinde(mt5)
    antwort = sende("/api/ingest/ping", methode="GET")
    melde(
        f"API erreichbar. Marke gilt für Konto {antwort['account_id']} "
        f"({antwort['label']})."
    )
    versatz = miss_versatz(mt5)
    if versatz is None:
        melde("Zeitversatz gerade nicht messbar (Markt geschlossen).")
    melde("Alles bereit.")


def main() -> None:
    lade_env(os.path.join(HIER, ".env"))

    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        raise SystemExit(
            "Das Paket MetaTrader5 fehlt.\n"
            "  Unter Wine:  wine python.exe -m pip install MetaTrader5\n"
            "  Es gibt es nur für Windows-Python -- unter Linux-Python\n"
            "  lässt es sich nicht installieren, das ist keine Fehlkonfiguration."
        )

    argumente = sys.argv[1:]

    if "--pruefen" in argumente:
        pruefen(mt5)
        mt5.shutdown()
        return

    tage = None
    if "--tage" in argumente:
        tage = int(argumente[argumente.index("--tage") + 1])

    verbinde(mt5)

    if "--dauer" not in argumente:
        abgleichen(mt5, tage)
        mt5.shutdown()
        return

    takt = int(os.environ.get("SAMMLER_TAKT_SEKUNDEN", "300"))
    melde(f"Dauerbetrieb, alle {takt // 60} Minuten. Beenden mit Strg+C.")
    try:
        erster = True
        while True:
            try:
                abgleichen(mt5, tage if erster else None)
                erster = False
            except Exception as fehler:  # noqa: BLE001
                # Ein Fehler darf den Sammler nicht beenden: Das Terminal
                # startet sich neu, das Netz hakt, die API wird neu
                # gestartet. Beim nächsten Lauf holt die Überlappung alles
                # nach, was in der Zwischenzeit lief.
                melde(f"Fehlgeschlagen: {fehler}")
            time.sleep(takt)
    except KeyboardInterrupt:
        melde("Beendet.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

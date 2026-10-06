"""MT5-Deals in Kern-Deals übersetzen.

Diese Datei redet **nicht** mit MetaTrader. Sie nimmt entgegen, was der
Sammler geschickt hat -- schlichte Wörterbücher --, und macht daraus
`Deal`-Objekte. Der Grund für die Trennung ist der wichtigste Satz über
den ganzen Sammler:

    Der Sammler läuft unter Wine und sitzt damit auf dem brüchigsten
    Stück der Kette. Was dort nicht steht, kann dort nicht kaputtgehen.

Alles Denkbare wandert deshalb hierher, wo es auf einem gewöhnlichen
Linux-Python läuft und sich Zeile für Zeile testen lässt. Drüben bleibt
nur: verbinden, Historie abrufen, JSON schicken.

## Die Zeitfalle

Das ist die Stelle, an der man sich bei MT5 verrechnet, und sie ist
tückisch, weil das Ergebnis plausibel aussieht.

MT5 liefert Zeitstempel in der Zeitzone des **Broker-Servers**, nicht in
UTC. Die Python-Anbindung reicht sie als Unix-Zeitstempel durch, gerechnet
so, als wäre die Serverzeit UTC gewesen. Ein Deal um 09:31 Serverzeit
kommt also als Zeitstempel an, der bei naiver Umrechnung 09:31 UTC ergibt.

Alpha Capital fährt wie die meisten Broker auf EET/EEST -- also UTC+2 im
Winter, UTC+3 im Sommer. Ohne Korrektur landet jeder Trade zwei bis drei
Stunden zu spät. Was daraus folgt:

* Der Kalender ordnet Trades kurz vor Mitternacht dem falschen Tag zu.
* Die Auswertung nach Uhrzeit ist um zwei Stunden verschoben -- man
  optimiert dann auf eine Handelsstunde, in der man nie gehandelt hat.
* Der Tagesverlust-Puffer rechnet mit dem falschen Tag und kann eine
  Regelverletzung übersehen.

Deshalb wird der Versatz **je Abgleich mitgemessen** statt fest verdrahtet:
Der Sommerzeitwechsel des Brokers erledigt sich damit von selbst. Und
beide Zeiten werden gespeichert -- `time_utc` zum Rechnen, `time_broker`
zum Anzeigen. Wer eine Order um "09:31" gesetzt hat, will sie im Journal
auch um 09:31 wiederfinden.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from ..core.models import ZERO, Deal, DealEntry, DealType, SyncResult

#: MT5-Konstante -> unser Typ.
#:
#: Alles jenseits von Kauf, Verkauf und Kontobuchung wird zu `OTHER`. Das
#: ist kein Wegwerfen: `OTHER` fällt aus der Trade-Auswertung heraus, aber
#: der Deal bleibt gespeichert. Käme später heraus, dass eine dieser
#: Buchungsarten doch zählt, steht sie noch da.
DEAL_TYPEN: dict[int, DealType] = {
    0: DealType.BUY,       # DEAL_TYPE_BUY
    1: DealType.SELL,      # DEAL_TYPE_SELL
    2: DealType.BALANCE,   # DEAL_TYPE_BALANCE -- Ein- und Auszahlung
    3: DealType.BALANCE,   # DEAL_TYPE_CREDIT
    4: DealType.BALANCE,   # DEAL_TYPE_CHARGE
    5: DealType.BALANCE,   # DEAL_TYPE_CORRECTION
    6: DealType.BALANCE,   # DEAL_TYPE_BONUS
    7: DealType.BALANCE,   # DEAL_TYPE_COMMISSION
    8: DealType.BALANCE,   # DEAL_TYPE_COMMISSION_DAILY
    9: DealType.BALANCE,   # DEAL_TYPE_COMMISSION_MONTHLY
    10: DealType.BALANCE,  # DEAL_TYPE_COMMISSION_AGENT_DAILY
    11: DealType.BALANCE,  # DEAL_TYPE_COMMISSION_AGENT_MONTHLY
    12: DealType.BALANCE,  # DEAL_TYPE_INTEREST
    13: DealType.OTHER,    # DEAL_TYPE_BUY_CANCELED
    14: DealType.OTHER,    # DEAL_TYPE_SELL_CANCELED
    15: DealType.BALANCE,  # DEAL_DIVIDEND
    16: DealType.BALANCE,  # DEAL_DIVIDEND_FRANKED
    17: DealType.BALANCE,  # DEAL_TAX
}

DEAL_ENTRIES: dict[int, DealEntry] = {
    0: DealEntry.IN,      # DEAL_ENTRY_IN
    1: DealEntry.OUT,     # DEAL_ENTRY_OUT
    2: DealEntry.INOUT,   # DEAL_ENTRY_INOUT -- die Umkehr
    3: DealEntry.OUT_BY,  # DEAL_ENTRY_OUT_BY
}

#: Broker-Versätze sind volle, halbe oder viertel Stunden. Auf 15 Minuten
#: gerundet fängt die Messung Ungenauigkeiten weg, ohne je einen echten
#: Versatz zu verfehlen.
RASTER = 15 * 60


class UnbrauchbarerDeal(ValueError):
    """Ein Datensatz, aus dem sich kein Deal machen lässt."""


def _dez(wert: Any, standard: Decimal = ZERO) -> Decimal:
    """Zahl zu `Decimal`, über den Umweg `str`.

    `Decimal(0.1)` ergibt 0.1000000000000000055511151231257827; `Decimal("0.1")`
    ergibt 0.1. Die MT5-Anbindung liefert floats, also führt hier der einzige
    richtige Weg über die Zeichenkette.
    """
    if wert is None or wert == "":
        return standard
    try:
        return Decimal(str(wert))
    except (InvalidOperation, ValueError, TypeError):
        raise UnbrauchbarerDeal(f"Keine Zahl: {wert!r}")


def runde_versatz(sekunden: float) -> int:
    """Rundet einen gemessenen Versatz auf das nächste Viertelstundenraster."""
    return int(round(sekunden / RASTER) * RASTER)


#: Grenzen eines echten UTC-Versatzes. Zwischen Baker Island (-12) und
#: Kiritimati (+14) liegt jede Zeitzone der Welt; alles darüber hinaus ist
#: kein Versatz, sondern ein veralteter Tick.
VERSATZ_MIN = -12 * 3600
VERSATZ_MAX = 14 * 3600


def _als_utc(zeit: datetime | float) -> datetime:
    """Server-Wanduhr als `datetime`, gelesen als wäre sie UTC."""
    if isinstance(zeit, (int, float)):
        return datetime.fromtimestamp(zeit, tz=timezone.utc)
    return zeit if zeit.tzinfo else zeit.replace(tzinfo=timezone.utc)


def markt_lebt(
    tick_vorher: datetime | float,
    tick_nachher: datetime | float,
) -> bool:
    """Ist der Markt gerade offen?

    Zwei Kurs-Ticks im Abstand von ein, zwei Sekunden: Ist der zweite
    neuer als der erste, kommen Kurse herein und der Markt lebt.

    Diese Prüfung ist **nicht optional**, sondern die Voraussetzung dafür,
    dass :func:`messe_versatz` überhaupt eine gültige Antwort geben kann.
    Der Grund ist unangenehm: Aus einem einzelnen Tick lässt sich sein
    eigenes Alter nicht ablesen. Ein Tick von vor 20 Minuten ergibt bei
    einem Broker auf UTC+2 einen sauber gerundeten Versatz von +1,75 h --
    eine Zahl, die durch jede Plausibilitätsprüfung kommt und trotzdem
    falsch ist. Nachgemessen:

        Tick   0 min alt -> +2,00 h   richtig
        Tick   7 min alt -> +2,00 h   richtig (Rundung fängt es auf)
        Tick  20 min alt -> +1,75 h   FALSCH
        Tick  90 min alt -> +0,50 h   FALSCH

    Ein falscher Versatz verschiebt jeden Trade um Stunden, und zwar in
    allen Ansichten gleich -- also unauffällig. Deshalb lieber gar nicht
    messen als bei geschlossenem Markt zu messen.
    """
    return _als_utc(tick_nachher) > _als_utc(tick_vorher)


def messe_versatz(
    server_zeit: datetime | float,
    jetzt_utc: datetime | None = None,
) -> int | None:
    """Der Versatz der Serverzeit gegenüber UTC, in Sekunden.

    Gemessen an einem Kurs-Tick: Dessen Zeitstempel trägt die Serverzeit,
    und der Abstand zur eigenen Uhr ist der gesuchte Versatz.

    **Nur bei offenem Markt aufrufen** -- siehe :func:`markt_lebt`. Die
    Bereichsprüfung hier fängt nur grob veraltete Ticks ab (Wochenende,
    Feiertag); einen um Minuten veralteten kann sie nicht erkennen, weil
    das Ergebnis dann wie ein gültiger Versatz aussieht.

    `None` heißt "unbekannt" und niemals 0. Null wäre die Behauptung, der
    Server laufe auf UTC -- bei Alpha Capital wäre das um zwei Stunden
    falsch. Der Aufrufer behält dann den zuletzt bekannten Wert.
    """
    jetzt = jetzt_utc or datetime.now(timezone.utc)
    roh = (_als_utc(server_zeit) - jetzt).total_seconds()

    if not VERSATZ_MIN <= roh <= VERSATZ_MAX:
        return None
    return runde_versatz(roh)


def deal_aus_mt5(
    roh: dict[str, Any],
    account_id: str,
    server_utc_offset: int = 0,
) -> Deal | None:
    """Ein MT5-Datensatz wird ein `Deal`. `None`, wenn er nicht zählt.

    `None` statt einer Ausnahme für stornierte Buchungen: Die kommen im
    normalen Betrieb vor und sind kein Fehler. Ein *kaputter* Datensatz
    wirft dagegen -- den will man sehen.
    """
    try:
        ticket = int(roh["ticket"])
        zeitstempel = float(roh["time"])
    except (KeyError, TypeError, ValueError) as fehler:
        raise UnbrauchbarerDeal(f"Pflichtfeld fehlt oder ist unlesbar: {fehler}")

    typ_zahl = int(roh.get("type", -1))
    typ = DEAL_TYPEN.get(typ_zahl, DealType.OTHER)

    # Stornierte Aufträge sind nie ausgeführt worden. Sie stehen in der
    # Historie, gehören aber in keine Auswertung -- auch nicht als
    # Nullzeile, weil sie sonst die Trade-Anzahl aufblähen.
    if typ_zahl in (13, 14):
        return None

    entry = DEAL_ENTRIES.get(int(roh.get("entry", 0)), DealEntry.IN)

    # Die Wanduhr des Servers, gelesen als wäre sie UTC.
    broker_zeit = datetime.fromtimestamp(zeitstempel, tz=timezone.utc)
    # Und daraus die echte UTC-Zeit.
    utc_zeit = broker_zeit - timedelta(seconds=server_utc_offset)

    stop = roh.get("sl")
    # MT5 schreibt 0.0 statt None, wenn kein Stop gesetzt war. Ein Stop bei
    # Preis null gibt es nicht -- das als Stop zu übernehmen ergäbe ein
    # R-Multiple aus dem vollen Kontraktwert.
    stop_loss = _dez(stop) if stop not in (None, "", 0, 0.0) else None

    return Deal(
        ticket=ticket,
        account_id=str(account_id),
        position_id=int(roh.get("position_id") or 0),
        symbol=str(roh.get("symbol") or ""),
        type=typ,
        entry=entry,
        volume=_dez(roh.get("volume")),
        price=_dez(roh.get("price")),
        time_utc=utc_zeit,
        time_broker=broker_zeit.replace(tzinfo=None),
        profit=_dez(roh.get("profit")),
        commission=_dez(roh.get("commission")),
        swap=_dez(roh.get("swap")),
        fee=_dez(roh.get("fee")),
        stop_loss=stop_loss,
    )


def deals_aus_mt5(
    rohe: Iterable[dict[str, Any]],
    account_id: str,
    server_utc_offset: int = 0,
    streng: bool = False,
) -> tuple[list[Deal], list[str]]:
    """Wandelt eine ganze Lieferung um.

    Gibt die Deals **und die Beanstandungen** zurück. Beides zusammen, weil
    ein Import, der stillschweigend Zeilen wegwirft, gefährlicher ist als
    einer, der abbricht: Die Summe stimmt dann nicht mehr und niemand weiß
    warum.

    `streng=True` lässt den ersten kaputten Datensatz durchschlagen -- für
    Tests und für den ersten Lauf gegen ein neues Konto.
    """
    deals: list[Deal] = []
    probleme: list[str] = []

    for index, roh in enumerate(rohe):
        try:
            deal = deal_aus_mt5(roh, account_id, server_utc_offset)
        except UnbrauchbarerDeal as fehler:
            if streng:
                raise
            probleme.append(f"Datensatz {index}: {fehler}")
            continue
        if deal is not None:
            deals.append(deal)

    return deals, probleme


def ergebnis_aus_lieferung(
    lieferung: dict[str, Any],
    account_id: str,
    streng: bool = False,
) -> tuple[SyncResult, list[str]]:
    """Die vollständige Lieferung des Sammlers auswerten.

    Erwartet wird, was `collector/sammler.py` schickt: die rohen Deals und
    der gemessene Versatz. Fehlt der Versatz (Markt geschlossen, Tick zu
    alt), wird **nicht** auf null zurückgefallen -- null wäre die
    Behauptung, der Server laufe auf UTC, und verschöbe jede Zeit um zwei
    Stunden. Stattdessen bleibt er `None`, und der Aufrufer entscheidet:
    zuletzt bekannten Wert nehmen oder den Lauf verwerfen.
    """
    versatz = lieferung.get("server_utc_offset")
    versatz = int(versatz) if versatz is not None else None

    deals, probleme = deals_aus_mt5(
        lieferung.get("deals") or [],
        account_id=account_id,
        server_utc_offset=versatz or 0,
        streng=streng,
    )

    geholt = lieferung.get("fetched_at")
    return (
        SyncResult(
            deals=deals,
            server_utc_offset=versatz,
            fetched_at=(
                datetime.fromisoformat(geholt) if isinstance(geholt, str) else None
            ),
        ),
        probleme,
    )

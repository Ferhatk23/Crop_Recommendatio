"""Die Datentypen, um die sich alles dreht.

Zwei Ebenen, und die Trennung ist wichtig:

* Ein `Deal` ist eine einzelne Ausführung, wie der Broker sie liefert. Er ist
  die Wahrheit und wird nie verändert.
* Ein `Trade` ist ein vollständiger Round-Trip, aus mehreren Deals berechnet.
  Er ist jederzeit neu herleitbar.

Geldbeträge sind durchgehend `Decimal`, niemals `float`. Bei float summieren
sich Rundungsfehler über tausende Trades zu Abweichungen, die man dann in der
Kennzahlen-Logik sucht statt im Datentyp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

ZERO = Decimal("0")


class DealType(str, Enum):
    """Was für eine Art von Buchung der Deal ist."""

    BUY = "buy"
    SELL = "sell"
    #: Ein- und Auszahlungen kommen bei MT5 im selben Strom wie Trades.
    #: Sie gehören in die Equity-Kurve, aber niemals in die Trade-Auswertung.
    BALANCE = "balance"
    OTHER = "other"


class DealEntry(str, Enum):
    """Wie der Deal die Position verändert."""

    IN = "in"
    OUT = "out"
    #: Positionsumkehr auf Netting-Konten: schließt die alte Position und
    #: eröffnet in einem Zug die gegenläufige neue.
    INOUT = "inout"
    OUT_BY = "out_by"


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class Outcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    #: Genau null nach Kosten. Weder Gewinn noch Verlust -- und deshalb aus
    #: der Trefferquote herauszuhalten, sonst drückt jeder Break-even-Trade
    #: die Quote, obwohl er nichts gekostet hat.
    SCRATCH = "scratch"


@dataclass(frozen=True)
class Deal:
    """Eine einzelne Ausführung, so wie der Broker sie meldet."""

    ticket: int
    account_id: str
    position_id: int
    symbol: str
    type: DealType
    entry: DealEntry
    volume: Decimal
    price: Decimal
    time_utc: datetime

    #: Vom Broker abgerechnetes Ergebnis. Bei MT5 steht es fertig im Deal --
    #: wir rechnen keine Kontraktgrößen oder Pip-Werte nach und können
    #: deshalb auch nicht vom Kontoauszug abweichen.
    profit: Decimal = ZERO
    commission: Decimal = ZERO
    swap: Decimal = ZERO
    fee: Decimal = ZERO

    #: Zeit in der Zeitzone des Broker-Servers, nur zur Anzeige.
    time_broker: datetime | None = None
    #: Ursprünglicher Stop aus der Eröffnungs-Order, falls bekannt.
    stop_loss: Decimal | None = None

    @property
    def costs(self) -> Decimal:
        """Alles, was der Broker zusätzlich abzieht."""
        return self.commission + self.swap + self.fee

    @property
    def net_pnl(self) -> Decimal:
        return self.profit + self.costs

    @property
    def is_balance(self) -> bool:
        return self.type is DealType.BALANCE

    @property
    def is_trade(self) -> bool:
        return self.type in (DealType.BUY, DealType.SELL)

    @property
    def signed_volume(self) -> Decimal:
        """Volumen mit Vorzeichen: Kauf positiv, Verkauf negativ.

        Damit lässt sich die laufende Position schlicht aufsummieren.
        """
        if self.type is DealType.BUY:
            return self.volume
        if self.type is DealType.SELL:
            return -self.volume
        return ZERO

    def sort_key(self) -> tuple[datetime, int]:
        """Zeit, dann Ticket.

        Das Ticket als zweites Kriterium ist kein Detail: Zwei Deals können
        denselben Zeitstempel tragen, und ohne stabile Reihenfolge fällt die
        Positionsverfolgung je nach Sortierung anders aus.
        """
        return (self.time_utc, self.ticket)


@dataclass
class Trade:
    """Ein vollständiger Weg von der ersten Position bis zurück auf null."""

    account_id: str
    symbol: str
    direction: Direction
    opened_at: datetime
    volume: Decimal
    #: `None`, wenn die Eröffnung vor dem abgefragten Zeitraum lag. Eine
    #: Null stünde da wie ein Preis, und niemand könnte den Unterschied
    #: sehen.
    avg_entry: Decimal | None

    closed_at: datetime | None = None
    avg_exit: Decimal | None = None

    #: Wie viel bereits wieder glattgestellt wurde. Bei einem geschlossenen
    #: Trade gleich dem Volumen; bei einem offenen der Teil, aus dem schon
    #: ausgestiegen wurde. Ein offener Trade mit Teilausstiegen trägt sehr
    #: wohl realisiertes Ergebnis -- ohne diese Angabe sähe das aus wie ein
    #: Fehler.
    exit_volume: Decimal = ZERO

    #: Bruchstück: Das Ergebnis stimmt, aber Einstiegspreis und -volumen
    #: fehlen, weil die Eröffnung außerhalb des Zeitraums lag. Am Rand jedes
    #: Abfragefensters unvermeidlich -- die Oberfläche soll es kennzeichnen
    #: statt so zu tun, als wären die Daten vollständig.
    partial: bool = False

    gross_pnl: Decimal = ZERO
    costs: Decimal = ZERO

    #: Bei MT5 die Positions-ID des Brokers, sonst vom Algorithmus vergeben.
    position_id: int | None = None
    deal_tickets: tuple[int, ...] = ()

    initial_sl: Decimal | None = None
    risk_amount: Decimal | None = None

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl + self.costs

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def duration(self) -> timedelta | None:
        if self.closed_at is None:
            return None
        return self.closed_at - self.opened_at

    @property
    def outcome(self) -> Outcome:
        if self.net_pnl > ZERO:
            return Outcome.WIN
        if self.net_pnl < ZERO:
            return Outcome.LOSS
        return Outcome.SCRATCH

    @property
    def r_multiple(self) -> Decimal | None:
        """Ergebnis in Vielfachen des ursprünglich riskierten Betrags.

        Ohne erfassten Stop gibt es kein R. Dann `None` -- niemals 0, denn
        das wäre eine erfundene Aussage über einen Trade, bei dem wir das
        Risiko schlicht nicht kennen.
        """
        if self.risk_amount is None or self.risk_amount == ZERO:
            return None
        return self.net_pnl / self.risk_amount


@dataclass
class BalanceEntry:
    """Ein- oder Auszahlung. Gehört in die Equity-Kurve, nicht in die Trades."""

    ticket: int
    account_id: str
    amount: Decimal
    time_utc: datetime


@dataclass
class SyncResult:
    """Was ein Abgleich aus einer Quelle mitgebracht hat."""

    deals: list[Deal] = field(default_factory=list)
    #: Versatz der Broker-Serverzeit gegenüber UTC, in Sekunden. Wird pro
    #: Abgleich mitgeliefert, damit Sommerzeitwechsel des Brokers sich von
    #: selbst erledigen statt fest verdrahtet zu sein.
    server_utc_offset: int | None = None
    fetched_at: datetime | None = None

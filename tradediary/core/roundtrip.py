"""Aus einzelnen Ausführungen werden vollständige Trades.

Es gibt zwei Wege hierher, und beide sind Absicht:

`trades_from_positions` nutzt die `position_id`, die MT5 jedem Deal mitgibt --
der Broker sagt uns also selbst, was zusammengehört. Das ist exakt und der
Normalweg.

`trades_from_executions` rekonstruiert dieselbe Zuordnung allein aus der
Reihenfolge der Ausführungen. Den brauchen wir aus zwei Gründen: als
Rückfallweg für Quellen ohne Positions-ID (CSV-Importe anderer Broker), und
um die Zuordnung des Brokers gegenprüfen zu können.

Dieses Modul ist bewusst frei von Seiteneffekten: Liste rein, Liste raus.
Keine Datenbank, kein Netz, keine Uhr. Genau deshalb ist es vollständig
testbar, und genau deshalb hängt der Rest des Projekts daran.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .models import ZERO, BalanceEntry, Deal, DealType, Direction, Trade


def split_balance_entries(deals: list[Deal]) -> tuple[list[Deal], list[BalanceEntry]]:
    """Trennt Ein- und Auszahlungen von den Handelsausführungen.

    MT5 liefert beides im selben Strom. Wer die Balance-Buchungen nicht
    herausfiltert, sieht eine Einzahlung als gewaltigen Gewinn -- und wer sie
    wegwirft, bekommt eine falsche Equity-Kurve. Deshalb: trennen, beides
    behalten.
    """
    trades: list[Deal] = []
    balances: list[BalanceEntry] = []
    for deal in deals:
        if deal.is_balance:
            balances.append(
                BalanceEntry(
                    ticket=deal.ticket,
                    account_id=deal.account_id,
                    amount=deal.profit,
                    time_utc=deal.time_utc,
                )
            )
        elif deal.is_trade:
            trades.append(deal)
    return trades, balances


@dataclass
class _Builder:
    """Sammelt die Teile eines Trades, bis er geschlossen ist."""

    account_id: str
    symbol: str
    direction: Direction
    position_id: int | None = None

    entry_volume: Decimal = ZERO
    entry_notional: Decimal = ZERO
    exit_volume: Decimal = ZERO
    exit_notional: Decimal = ZERO

    gross_pnl: Decimal = ZERO
    costs: Decimal = ZERO

    opened_at: datetime | None = None
    closed_at: datetime | None = None
    tickets: list[int] = field(default_factory=list)
    initial_sl: Decimal | None = None

    def add_entry(self, volume: Decimal, price: Decimal, when: datetime) -> None:
        self.entry_volume += volume
        self.entry_notional += volume * price
        if self.opened_at is None:
            self.opened_at = when

    def add_exit(self, volume: Decimal, price: Decimal, when: datetime) -> None:
        self.exit_volume += volume
        self.exit_notional += volume * price
        self.closed_at = when

    def build(self, closed: bool) -> Trade:
        avg_entry = (
            self.entry_notional / self.entry_volume if self.entry_volume else ZERO
        )
        avg_exit = (
            self.exit_notional / self.exit_volume if self.exit_volume else None
        )
        return Trade(
            account_id=self.account_id,
            symbol=self.symbol,
            direction=self.direction,
            opened_at=self.opened_at,
            closed_at=self.closed_at if closed else None,
            volume=self.entry_volume,
            avg_entry=avg_entry,
            avg_exit=avg_exit if closed else None,
            gross_pnl=self.gross_pnl,
            costs=self.costs,
            position_id=self.position_id,
            deal_tickets=tuple(self.tickets),
            initial_sl=self.initial_sl,
        )


def trades_from_positions(deals: list[Deal]) -> list[Trade]:
    """Gruppiert Deals über die `position_id` des Brokers.

    Der Normalweg für MT5. Weil der Broker die Zuordnung selbst mitliefert,
    ist hier nichts zu rekonstruieren und nichts zu schätzen: Die Beträge
    sind seine, nicht unsere.
    """
    trade_deals, _ = split_balance_entries(deals)

    groups: dict[tuple[str, int], list[Deal]] = defaultdict(list)
    for deal in trade_deals:
        groups[(deal.account_id, deal.position_id)].append(deal)

    trades: list[Trade] = []
    for (account_id, position_id), group in groups.items():
        group.sort(key=Deal.sort_key)
        first = group[0]

        # Die Richtung ergibt sich aus der ersten Ausführung: Wer kauft, um
        # zu eröffnen, ist long.
        direction = Direction.LONG if first.type is DealType.BUY else Direction.SHORT
        opening_type = first.type

        builder = _Builder(
            account_id=account_id,
            symbol=first.symbol,
            direction=direction,
            position_id=position_id,
        )

        for deal in group:
            builder.tickets.append(deal.ticket)
            builder.gross_pnl += deal.profit
            builder.costs += deal.costs
            if deal.stop_loss is not None and builder.initial_sl is None:
                builder.initial_sl = deal.stop_loss

            if deal.type is opening_type:
                builder.add_entry(deal.volume, deal.price, deal.time_utc)
            else:
                builder.add_exit(deal.volume, deal.price, deal.time_utc)

        # Auf null zurück heißt geschlossen.
        net_volume = sum((d.signed_volume for d in group), ZERO)
        trades.append(builder.build(closed=net_volume == ZERO))

    trades.sort(key=lambda t: (t.opened_at, t.position_id or 0))
    return trades


def trades_from_executions(deals: list[Deal]) -> list[Trade]:
    """Rekonstruiert die Trades allein aus der Reihenfolge der Ausführungen.

    Je Konto und Symbol wird eine vorzeichenbehaftete Position mitgeführt.
    Ein Trade beginnt, wenn die Position 0 verlässt, und endet, wenn sie 0
    wieder erreicht.

    Der interessante Fall ist die Umkehr: Eine einzelne Ausführung kann eine
    Position schließen *und* die gegenläufige eröffnen. Sie muss dann
    aufgeteilt werden -- sonst hängen zwei Trades aneinander und beide
    Ergebnisse sind falsch. Genau das erledigt die innere Schleife.

    Beim Aufteilen werden Ergebnis und Kosten anteilig nach Volumen verteilt.
    Das ist eine Näherung; wo eine `position_id` vorliegt, ist
    `trades_from_positions` deshalb die genauere Wahl.
    """
    trade_deals, _ = split_balance_entries(deals)

    by_instrument: dict[tuple[str, str], list[Deal]] = defaultdict(list)
    for deal in trade_deals:
        by_instrument[(deal.account_id, deal.symbol)].append(deal)

    trades: list[Trade] = []

    for (account_id, symbol), group in by_instrument.items():
        group.sort(key=Deal.sort_key)

        position = ZERO
        builder: _Builder | None = None

        for deal in group:
            remaining = deal.signed_volume
            if remaining == ZERO:
                continue
            total = abs(remaining)

            while remaining != ZERO:
                if position == ZERO:
                    # Neue Position -- ein neuer Trade beginnt.
                    builder = _Builder(
                        account_id=account_id,
                        symbol=symbol,
                        direction=(
                            Direction.LONG if remaining > ZERO else Direction.SHORT
                        ),
                    )
                    take = remaining
                elif (position > ZERO) == (remaining > ZERO):
                    # Gleiche Richtung: aufgestockt.
                    take = remaining
                elif abs(remaining) <= abs(position):
                    # Gegenrichtung, aber nicht mehr als offen ist: Teilausstieg.
                    take = remaining
                else:
                    # Umkehr: nur der Teil, der die Position auf null bringt.
                    take = -position

                assert builder is not None
                share = abs(take) / total
                builder.gross_pnl += deal.profit * share
                builder.costs += deal.costs * share
                if deal.ticket not in builder.tickets:
                    builder.tickets.append(deal.ticket)
                if deal.stop_loss is not None and builder.initial_sl is None:
                    builder.initial_sl = deal.stop_loss

                opening = position == ZERO or (position > ZERO) == (take > ZERO)
                if opening:
                    builder.add_entry(abs(take), deal.price, deal.time_utc)
                else:
                    builder.add_exit(abs(take), deal.price, deal.time_utc)

                position += take
                remaining -= take

                if position == ZERO:
                    trades.append(builder.build(closed=True))
                    builder = None

        # Am Ende noch offene Position: als offener Trade übernehmen.
        if builder is not None:
            trades.append(builder.build(closed=False))

    trades.sort(key=lambda t: (t.opened_at, t.symbol))
    return trades


def reconcile(deals: list[Deal]) -> list[str]:
    """Vergleicht beide Wege und meldet Abweichungen.

    Läuft als Test gegen echte Daten: Stimmt unsere eigene Rekonstruktion
    nicht mit der Zuordnung des Brokers überein, ist einer von beiden falsch
    -- und das will man wissen, bevor man auf die Kennzahlen schaut.
    """
    from_positions = trades_from_positions(deals)
    from_executions = trades_from_executions(deals)

    problems: list[str] = []

    if len(from_positions) != len(from_executions):
        problems.append(
            f"Anzahl Trades weicht ab: {len(from_positions)} über position_id, "
            f"{len(from_executions)} über Ausführungsreihenfolge"
        )

    net_a = sum((t.net_pnl for t in from_positions), ZERO)
    net_b = sum((t.net_pnl for t in from_executions), ZERO)
    if abs(net_a - net_b) > Decimal("0.01"):
        problems.append(f"Netto-Summe weicht ab: {net_a} gegen {net_b}")

    return problems


def apply_risk(
    trade: Trade, point_value: Decimal, points_per_unit: Decimal = Decimal("1")
) -> Trade:
    """Rechnet aus dem Stop-Abstand den riskierten Betrag.

    Der Kern kennt keine Kontraktgrößen -- die weiß nur die Quelle, die auch
    die Symbolangaben des Brokers hat. Deshalb wird der Geldwert je Punkt
    hier hereingereicht statt geraten.
    """
    if trade.initial_sl is None or trade.avg_entry == ZERO:
        return trade
    distance = abs(trade.avg_entry - trade.initial_sl)
    trade.risk_amount = distance * points_per_unit * point_value * trade.volume
    return trade

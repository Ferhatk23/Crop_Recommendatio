"""Tests für die Zuordnung von Ausführungen zu Trades.

Das ist das Modul, an dem alles Nachgelagerte hängt: Stimmt die Zuordnung
nicht, sind sämtliche Kennzahlen falsch, ohne dass man es ihnen ansieht.
Deshalb steht hier jeder Randfall einzeln.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import D, buy, sell

from tradediary.core.models import DealEntry, DealType, Direction, Outcome
from tradediary.core.roundtrip import (
    reconcile,
    split_balance_entries,
    trades_from_executions,
    trades_from_positions,
)
from tradediary.core.models import Deal
from conftest import BASE


# --------------------------------------------------------------------------
# Der Normalfall
# --------------------------------------------------------------------------

def test_einfacher_long_roundtrip():
    deals = [
        buy(1, 100, "1.00", "1.0842", 0, profit=0, commission="-3.50"),
        sell(2, 100, "1.00", "1.0863", 60, profit="210.00", commission="-3.50"),
    ]

    trades = trades_from_positions(deals)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.direction is Direction.LONG
    assert trade.volume == D("1.00")
    assert trade.avg_entry == D("1.0842")
    assert trade.avg_exit == D("1.0863")
    assert trade.gross_pnl == D("210.00")
    assert trade.costs == D("-7.00")
    assert trade.net_pnl == D("203.00")
    assert not trade.is_open
    assert trade.outcome is Outcome.WIN


def test_aufstocken_und_teilverkauf_ergeben_einen_trade():
    """Vier Ausführungen, ein Trade -- mit gewichteten Durchschnittspreisen."""
    deals = [
        buy(1, 100, "1.00", "1.0842", 0),
        buy(2, 100, "0.50", "1.0838", 3),
        sell(3, 100, "0.75", "1.0857", 20, profit="105.00"),
        sell(4, 100, "0.75", "1.0863", 36, profit="140.00"),
    ]

    trades = trades_from_positions(deals)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.volume == D("1.50")
    # (1.00*1.0842 + 0.50*1.0838) / 1.50
    assert trade.avg_entry == (D("1.0842") + D("0.50") * D("1.0838")) / D("1.50")
    assert trade.avg_exit == (D("0.75") * D("1.0857") + D("0.75") * D("1.0863")) / D("1.50")
    assert trade.net_pnl == D("245.00")
    assert trade.deal_tickets == (1, 2, 3, 4)


def test_offene_position_bleibt_offen():
    deals = [buy(1, 100, "1.00", "1.0842", 0)]

    trade = trades_from_positions(deals)[0]

    assert trade.is_open
    assert trade.closed_at is None
    assert trade.avg_exit is None
    assert trade.duration is None


# --------------------------------------------------------------------------
# Die Fälle, an denen selbstgebaute Journals scheitern
# --------------------------------------------------------------------------

def test_umkehr_wird_in_zwei_trades_geteilt():
    """Ein Fill schließt eine Short-Position und eröffnet eine Long-Position.

    Ohne Aufteilung hingen beide Trades aneinander und beide Ergebnisse
    wären falsch. Das ist der Fall, der in MT5 ``DEAL_ENTRY_INOUT`` heißt.
    """
    deals = [
        sell(1, 100, "2.00", "1.0871", 0),
        # 3.00 Lot: schließt 2.00 short, eröffnet 1.00 long.
        buy(2, 101, "3.00", "1.0855", 86, profit="300.00", entry=DealEntry.INOUT),
    ]

    trades = trades_from_executions(deals)

    assert len(trades) == 2

    closed, opened = trades[0], trades[1]
    assert closed.direction is Direction.SHORT
    assert closed.volume == D("2.00")
    assert not closed.is_open
    # Zwei von drei Lot gehörten zum Schließen.
    assert closed.gross_pnl == D("300.00") * D("2") / D("3")

    assert opened.direction is Direction.LONG
    assert opened.volume == D("1.00")
    assert opened.is_open


def test_gleiche_zeitstempel_werden_stabil_sortiert():
    """Zwei Deals in derselben Sekunde -- das Ticket entscheidet.

    Ohne stabile Zweitsortierung fiele die Positionsverfolgung je nach
    Eingangsreihenfolge unterschiedlich aus.
    """
    deals = [
        sell(2, 100, "1.00", "1.0863", 0, profit="210.00"),
        buy(1, 100, "1.00", "1.0842", 0),
    ]

    trades = trades_from_executions(deals)

    assert len(trades) == 1
    assert trades[0].direction is Direction.LONG
    assert not trades[0].is_open


def test_balance_buchungen_gehoeren_nicht_in_die_trades():
    """Eine Einzahlung darf nicht wie ein Riesengewinn aussehen."""
    einzahlung = Deal(
        ticket=99,
        account_id="A1",
        position_id=0,
        symbol="",
        type=DealType.BALANCE,
        entry=DealEntry.IN,
        volume=D("0"),
        price=D("0"),
        time_utc=BASE,
        profit=D("10000.00"),
    )
    deals = [
        einzahlung,
        buy(1, 100, "1.00", "1.0842", 5),
        sell(2, 100, "1.00", "1.0863", 65, profit="210.00"),
    ]

    trade_deals, balances = split_balance_entries(deals)
    trades = trades_from_positions(deals)

    assert len(trade_deals) == 2
    assert len(balances) == 1
    assert balances[0].amount == D("10000.00")
    assert len(trades) == 1
    assert trades[0].net_pnl == D("210.00")


def test_verschiedene_symbole_werden_getrennt_verfolgt():
    deals = [
        buy(1, 100, "1.00", "1.0842", 0, symbol="EURUSD"),
        buy(2, 200, "1.00", "1.2650", 1, symbol="GBPUSD"),
        sell(3, 100, "1.00", "1.0863", 30, symbol="EURUSD", profit="210.00"),
        sell(4, 200, "1.00", "1.2600", 40, symbol="GBPUSD", profit="-500.00"),
    ]

    trades = trades_from_executions(deals)

    assert len(trades) == 2
    symbole = {t.symbol for t in trades}
    assert symbole == {"EURUSD", "GBPUSD"}
    assert all(not t.is_open for t in trades)


def test_verschiedene_konten_werden_getrennt_verfolgt():
    """Prop-Trader haben über die Zeit mehrere Konten -- oft gleichzeitig."""
    deals = [
        buy(1, 100, "1.00", "1.0842", 0, account_id="challenge"),
        buy(2, 100, "1.00", "1.0842", 0, account_id="funded"),
        sell(3, 100, "1.00", "1.0863", 30, account_id="challenge", profit="210.00"),
    ]

    trades = trades_from_executions(deals)

    assert len(trades) == 2
    geschlossen = [t for t in trades if not t.is_open]
    assert len(geschlossen) == 1
    assert geschlossen[0].account_id == "challenge"


# --------------------------------------------------------------------------
# Abgleich beider Wege
# --------------------------------------------------------------------------

def test_beide_wege_kommen_zum_selben_ergebnis():
    """Unsere Rekonstruktion muss mit der Zuordnung des Brokers übereinstimmen.

    Weichen sie ab, ist einer von beiden falsch -- und das will man wissen,
    bevor man auf die Kennzahlen schaut.
    """
    deals = [
        buy(1, 100, "1.00", "1.0842", 0, commission="-3.50"),
        buy(2, 100, "0.50", "1.0838", 3, commission="-1.75"),
        sell(3, 100, "1.50", "1.0857", 20, profit="225.00", commission="-5.25"),
        sell(4, 200, "1.00", "1.0860", 30, commission="-3.50"),
        buy(5, 200, "1.00", "1.0840", 90, profit="200.00", commission="-3.50"),
    ]

    assert reconcile(deals) == []

    a = trades_from_positions(deals)
    b = trades_from_executions(deals)
    assert len(a) == len(b) == 2
    assert sum(t.net_pnl for t in a) == sum(t.net_pnl for t in b)


def test_short_roundtrip_richtung_stimmt():
    deals = [
        sell(1, 100, "1.00", "1.0871", 0),
        buy(2, 100, "1.00", "1.0855", 45, profit="160.00"),
    ]

    for trades in (trades_from_positions(deals), trades_from_executions(deals)):
        assert len(trades) == 1
        assert trades[0].direction is Direction.SHORT
        assert trades[0].avg_entry == D("1.0871")
        assert trades[0].avg_exit == D("1.0855")
        assert trades[0].net_pnl == D("160.00")


def test_leere_eingabe():
    assert trades_from_positions([]) == []
    assert trades_from_executions([]) == []
    assert reconcile([]) == []

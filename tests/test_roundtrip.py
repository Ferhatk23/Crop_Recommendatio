"""Tests für die Zuordnung von Ausführungen zu Trades.

Das ist das Modul, an dem alles Nachgelagerte hängt: Stimmt die Zuordnung
nicht, sind sämtliche Kennzahlen falsch, ohne dass man es ihnen ansieht.
Deshalb steht hier jeder Randfall einzeln.

Die Ausführungen werden über die benannten Helfer gebaut (`open_short` statt
`sell`), weil Kauf/Verkauf und Öffnen/Schließen zwei verschiedene Dinge sind
-- ein Short wird mit einem Verkauf eröffnet.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import (
    BASE,
    D,
    add_long,
    buy,
    close_long,
    close_short,
    open_long,
    open_short,
    sell,
)

from tradediary.core.models import Deal, DealEntry, DealType, Direction, Outcome
from tradediary.core.roundtrip import (
    _distribute,
    _split_plan,
    reconcile,
    split_balance_entries,
    trades_from_executions,
    trades_from_positions,
)

ZERO = D(0)


# --------------------------------------------------------------------------
# Der Normalfall
# --------------------------------------------------------------------------

def test_einfacher_long_roundtrip():
    deals = [
        open_long(1, 100, "1.00", "1.0842", 0, commission="-3.50"),
        close_long(2, 100, "1.00", "1.0863", 60, profit="210.00", commission="-3.50"),
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


def test_short_roundtrip_richtung_stimmt():
    """Ein Short wird mit einem Verkauf eröffnet -- beide Wege müssen das sehen."""
    deals = [
        open_short(1, 100, "1.00", "1.0871", 0),
        close_short(2, 100, "1.00", "1.0855", 45, profit="160.00"),
    ]

    for trades in (trades_from_positions(deals), trades_from_executions(deals)):
        assert len(trades) == 1
        assert trades[0].direction is Direction.SHORT
        assert trades[0].avg_entry == D("1.0871")
        assert trades[0].avg_exit == D("1.0855")
        assert trades[0].net_pnl == D("160.00")


def test_aufstocken_und_teilverkauf_ergeben_einen_trade():
    """Vier Ausführungen, ein Trade -- mit gewichteten Durchschnittspreisen."""
    deals = [
        open_long(1, 100, "1.00", "1.0842", 0),
        add_long(2, 100, "0.50", "1.0838", 3),
        close_long(3, 100, "0.75", "1.0857", 20, profit="105.00"),
        close_long(4, 100, "0.75", "1.0863", 36, profit="140.00"),
    ]

    trades = trades_from_positions(deals)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.volume == D("1.50")
    assert trade.avg_entry == (D("1.0842") + D("0.50") * D("1.0838")) / D("1.50")
    assert trade.avg_exit == (
        D("0.75") * D("1.0857") + D("0.75") * D("1.0863")
    ) / D("1.50")
    assert trade.net_pnl == D("245.00")
    assert trade.deal_tickets == (1, 2, 3, 4)


def test_offene_position_bleibt_offen():
    deals = [open_long(1, 100, "1.00", "1.0842", 0)]

    trade = trades_from_positions(deals)[0]

    assert trade.is_open
    assert trade.closed_at is None
    assert trade.avg_exit is None
    assert trade.duration is None


# --------------------------------------------------------------------------
# Die Umkehr -- der Fall, an dem selbstgebaute Journals scheitern
# --------------------------------------------------------------------------

def test_umkehr_wird_in_zwei_trades_geteilt():
    """Ein Fill schließt eine Short-Position und eröffnet eine Long-Position."""
    deals = [
        open_short(1, 100, "2.00", "1.0871", 0),
        buy(2, 101, "3.00", "1.0855", 86, profit="300.00", entry=DealEntry.INOUT),
    ]

    trades = trades_from_executions(deals)

    assert len(trades) == 2
    closed, opened = trades[0], trades[1]

    assert closed.direction is Direction.SHORT
    assert closed.volume == D("2.00")
    assert not closed.is_open

    assert opened.direction is Direction.LONG
    assert opened.volume == D("1.00")
    assert opened.is_open


def test_realisierter_gewinn_gehoert_ganz_dem_geschlossenen_trade():
    """Der neu eröffnete Teil hat noch nichts realisiert.

    MT5 bucht das Ergebnis auf die schließende Ausführung. Verteilt man es
    anteilig, schreibt man einem frisch eröffneten Trade einen Gewinn zu,
    den er nicht gemacht hat -- und weist beide Trades falsch aus.

    Kommission dagegen fällt je Volumen an und wird sehr wohl geteilt.
    """
    deals = [
        open_short(1, 100, "2.00", "1.0871", 0),
        buy(
            2, 101, "3.00", "1.0855", 86,
            profit="300.00", commission="-9.00", swap="-1.50",
            entry=DealEntry.INOUT,
        ),
    ]

    closed, opened = trades_from_executions(deals)

    # Ergebnis und Swap komplett beim geschlossenen Trade.
    assert closed.gross_pnl == D("300.00")
    assert opened.gross_pnl == ZERO

    # Kommission zwei Drittel zu einem Drittel.
    assert closed.costs == D("-6.00") + D("-1.50")
    assert opened.costs == D("-3.00")

    # Und nichts geht unterwegs verloren.
    assert closed.gross_pnl + opened.gross_pnl == D("300.00")
    assert closed.costs + opened.costs == D("-10.50")


def test_aufteilen_verliert_keinen_cent():
    """Krumme Beträge auf krumme Anteile -- die Summe muss exakt bleiben."""
    deals = [
        open_short(1, 100, "2.00", "1.0871", 0),
        buy(
            2, 101, "3.00", "1.0855", 86,
            profit="0.07", commission="-0.01",
            entry=DealEntry.INOUT,
        ),
    ]

    trades = trades_from_executions(deals)

    assert sum((t.gross_pnl for t in trades), ZERO) == D("0.07")
    assert sum((t.costs for t in trades), ZERO) == D("-0.01")


def test_distribute_gibt_den_rest_an_einen_teil_mit_gewicht():
    """Ein Anteil mit Gewicht null darf niemals Geld bekommen."""
    parts = _distribute(D("100.00"), [D("2"), D("1"), ZERO])

    assert parts[2] == ZERO
    assert sum(parts, ZERO) == D("100.00")


def test_split_plan_teilt_nur_bei_umkehr():
    # Eröffnen: ein Teil.
    assert _split_plan(ZERO, D("1.00")) == [D("1.00")]
    # Aufstocken: ein Teil.
    assert _split_plan(D("1.00"), D("0.50")) == [D("0.50")]
    # Teilausstieg: ein Teil.
    assert _split_plan(D("1.50"), D("-0.75")) == [D("-0.75")]
    # Glattstellen: ein Teil.
    assert _split_plan(D("1.50"), D("-1.50")) == [D("-1.50")]
    # Umkehr: zwei Teile.
    assert _split_plan(D("-2.00"), D("3.00")) == [D("2.00"), D("1.00")]


# --------------------------------------------------------------------------
# Robustheit der Eingangsdaten
# --------------------------------------------------------------------------

def test_richtung_stimmt_auch_wenn_der_zeitraum_mitten_hineinfaellt():
    """Fängt die Abfrage mitten in einer Position an, fehlt die Eröffnung.

    Ohne Auswertung des `entry`-Feldes wäre die erste vorliegende Ausführung
    ein Ausstieg -- und die Richtung genau verkehrt herum.
    """
    deals = [close_short(2, 100, "1.00", "1.0855", 45, profit="160.00")]

    trade = trades_from_positions(deals)[0]

    assert trade.direction is Direction.SHORT


def test_gleiche_zeitstempel_werden_stabil_sortiert():
    """Zwei Deals in derselben Sekunde -- das Ticket entscheidet."""
    deals = [
        close_long(2, 100, "1.00", "1.0863", 0, profit="210.00"),
        open_long(1, 100, "1.00", "1.0842", 0),
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
        volume=ZERO,
        price=ZERO,
        time_utc=BASE,
        profit=D("10000.00"),
    )
    deals = [
        einzahlung,
        open_long(1, 100, "1.00", "1.0842", 5),
        close_long(2, 100, "1.00", "1.0863", 65, profit="210.00"),
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
        open_long(1, 100, "1.00", "1.0842", 0, symbol="EURUSD"),
        open_long(2, 200, "1.00", "1.2650", 1, symbol="GBPUSD"),
        close_long(3, 100, "1.00", "1.0863", 30, symbol="EURUSD", profit="210.00"),
        close_long(4, 200, "1.00", "1.2600", 40, symbol="GBPUSD", profit="-500.00"),
    ]

    trades = trades_from_executions(deals)

    assert len(trades) == 2
    assert {t.symbol for t in trades} == {"EURUSD", "GBPUSD"}
    assert all(not t.is_open for t in trades)


def test_verschiedene_konten_werden_getrennt_verfolgt():
    """Prop-Trader haben über die Zeit mehrere Konten -- oft gleichzeitig."""
    deals = [
        open_long(1, 100, "1.00", "1.0842", 0, account_id="challenge"),
        open_long(2, 100, "1.00", "1.0842", 0, account_id="funded"),
        close_long(3, 100, "1.00", "1.0863", 30, account_id="challenge", profit="210.00"),
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

    Der Abgleich ist echt: `trades_from_positions` folgt der `position_id`
    und dem `entry`-Feld, `trades_from_executions` allein der Reihenfolge
    der Ausführungen. Sie können nur übereinstimmen, wenn beides stimmt.
    """
    deals = [
        open_long(1, 100, "1.00", "1.0842", 0, commission="-3.50"),
        add_long(2, 100, "0.50", "1.0838", 3, commission="-1.75"),
        close_long(3, 100, "1.50", "1.0857", 20, profit="225.00", commission="-5.25"),
        open_short(4, 200, "1.00", "1.0860", 30, commission="-3.50"),
        close_short(5, 200, "1.00", "1.0840", 90, profit="200.00", commission="-3.50"),
    ]

    assert reconcile(deals) == []

    a = trades_from_positions(deals)
    b = trades_from_executions(deals)
    assert len(a) == len(b) == 2
    assert sum((t.net_pnl for t in a), ZERO) == sum((t.net_pnl for t in b), ZERO)
    assert {t.direction for t in a} == {t.direction for t in b}


def test_reconcile_meldet_abweichende_anzahl():
    """Zwei getrennte Positionen, die der Broker in eine gesteckt hat.

    Erfundener Fall, aber genau der, den der Abgleich fangen soll: Die
    Ausführungsreihenfolge ergibt zwei Round-Trips, die `position_id`
    behauptet einen.
    """
    deals = [
        open_long(1, 100, "1.00", "1.0842", 0),
        close_long(2, 100, "1.00", "1.0850", 10, profit="80.00"),
        open_long(3, 100, "1.00", "1.0855", 20),
        close_long(4, 100, "1.00", "1.0870", 30, profit="150.00"),
    ]

    probleme = reconcile(deals)

    assert probleme
    assert "Anzahl" in probleme[0]


def test_leere_eingabe():
    assert trades_from_positions([]) == []
    assert trades_from_executions([]) == []
    assert reconcile([]) == []

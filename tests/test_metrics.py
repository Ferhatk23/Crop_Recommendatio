"""Tests für die Kennzahlen -- ein Test je Falle.

Die Formeln selbst sind trivial. Was hier geprüft wird, sind die
Definitionen: Was zählt als Gewinn, was passiert ohne Verluste, was passiert
ohne Stop. Genau diese Fälle machen den Unterschied zwischen Zahlen, die
etwas aussagen, und Zahlen, die nur so aussehen.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradediary.core import metrics as m
from tradediary.core import score as sc
from tradediary.core.models import Direction, Outcome, Trade

BASE = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


def D(value) -> Decimal:
    return Decimal(str(value))


def trade(net, *, day: int = 0, hour: int = 0, risk=None, symbol="EURUSD") -> Trade:
    """Ein geschlossener Trade mit vorgegebenem Nettoergebnis."""
    opened = BASE + timedelta(days=day, hours=hour)
    t = Trade(
        account_id="A1",
        symbol=symbol,
        direction=Direction.LONG,
        opened_at=opened,
        closed_at=opened + timedelta(minutes=30),
        volume=D("1.00"),
        avg_entry=D("1.0842"),
        avg_exit=D("1.0863"),
        gross_pnl=D(net),
        costs=D("0"),
    )
    if risk is not None:
        t.risk_amount = D(risk)
    return t


# --------------------------------------------------------------------------
# Trefferquote und Scratches
# --------------------------------------------------------------------------

def test_scratch_zaehlt_weder_als_gewinn_noch_als_verlust():
    """Ein Trade mit genau null darf die Trefferquote nicht drücken."""
    result = m.compute([trade("100"), trade("-50"), trade("0")])

    assert result.trade_count == 3
    assert result.wins == 1
    assert result.losses == 1
    assert result.scratches == 1
    # 1 von 2 entschiedenen Trades -- nicht 1 von 3.
    assert result.win_rate == D("0.5")


def test_win_rate_ohne_entschiedene_trades_ist_none():
    result = m.compute([trade("0"), trade("0")])

    assert result.scratches == 2
    assert result.win_rate is None


# --------------------------------------------------------------------------
# Profit Factor
# --------------------------------------------------------------------------

def test_profit_factor_ohne_verluste_ist_undefiniert():
    """Nicht unendlich, nicht null -- undefiniert."""
    result = m.compute([trade("100"), trade("50")])

    assert result.gross_loss == D("0")
    assert result.profit_factor is None


def test_profit_factor_normalfall():
    result = m.compute([trade("300"), trade("100"), trade("-200")])

    assert result.gross_profit == D("400")
    assert result.gross_loss == D("200")
    assert result.profit_factor == D("2")


# --------------------------------------------------------------------------
# R-Multiple
# --------------------------------------------------------------------------

def test_ohne_stop_kein_r_multiple():
    """`None` ist ehrlich, 0 wäre eine Erfindung."""
    ohne = trade("100")
    assert ohne.r_multiple is None

    result = m.compute([ohne, trade("-50")])
    assert result.expectancy_r is None
    assert result.trades_without_stop == 2


def test_r_multiple_mit_risiko():
    gewinner = trade("300", risk="100")
    verlierer = trade("-100", risk="100")

    assert gewinner.r_multiple == D("3")
    assert verlierer.r_multiple == D("-1")

    result = m.compute([gewinner, verlierer])
    assert result.expectancy_r == D("1")
    assert result.trades_without_stop == 0


def test_risiko_null_ergibt_kein_r():
    t = trade("100", risk="0")
    assert t.r_multiple is None


# --------------------------------------------------------------------------
# Drawdown, Erholung, Konsistenz
# --------------------------------------------------------------------------

def test_max_drawdown_ueber_die_trade_reihenfolge():
    # Verlauf: +500, +200 (Rückgang 300), +700
    trades = [trade("500", day=0), trade("-300", day=1), trade("500", day=2)]

    result = m.compute(trades)

    assert result.net_pnl == D("700")
    assert result.max_drawdown == D("300")
    assert result.recovery_factor == D("700") / D("300")


def test_drawdown_ohne_rueckgang_ist_null():
    result = m.compute([trade("100"), trade("200")])

    assert result.max_drawdown == D("0")
    # Division durch null -- kein Erholungsfaktor.
    assert result.recovery_factor is None


def test_consistency_erkennt_den_einen_gluckstag():
    """Ein Tag trägt fast alles: Konsistenz nahe null."""
    trades = [trade("1000", day=0), trade("10", day=1), trade("10", day=2)]

    result = m.compute(trades)

    assert result.consistency is not None
    assert result.consistency < D("0.05")


def test_consistency_bei_gleichmaessiger_verteilung():
    trades = [trade("100", day=0), trade("100", day=1), trade("100", day=2)]

    result = m.compute(trades)

    # Bester Tag ist ein Drittel der Gewinne -> 1 - 1/3
    assert result.consistency == D("1") - D("1") / D("3")


def test_consistency_ohne_gewinntage_ist_none():
    result = m.compute([trade("-100"), trade("-50")])

    assert result.consistency is None


# --------------------------------------------------------------------------
# Serien und Randfälle
# --------------------------------------------------------------------------

def test_serien_werden_von_scratches_nicht_unterbrochen():
    trades = [
        trade("100", day=0),
        trade("0", day=1),
        trade("100", day=2),
        trade("-50", day=3),
        trade("-50", day=4),
        trade("-50", day=5),
    ]

    result = m.compute(trades)

    assert result.max_consecutive_wins == 2
    assert result.max_consecutive_losses == 3


def test_offene_trades_bleiben_aussen_vor():
    """Ein schwebender Buchgewinn ist noch kein Ergebnis."""
    offen = trade("100")
    offen.closed_at = None

    result = m.compute([offen, trade("50")])

    assert result.trade_count == 1
    assert result.net_pnl == D("50")


def test_leere_eingabe_ergibt_leere_kennzahlen():
    result = m.compute([])

    assert result.trade_count == 0
    assert result.net_pnl == D("0")
    assert result.win_rate is None
    assert result.profit_factor is None


def test_handelstage_werden_gezaehlt():
    trades = [trade("100", day=0), trade("50", day=0, hour=3), trade("-20", day=1)]

    result = m.compute(trades)

    assert result.trading_days == 2


def test_kosten_werden_mitgefuehrt():
    t = trade("100")
    t.costs = D("-7.00")

    result = m.compute([t])

    assert result.total_costs == D("-7.00")
    assert result.net_pnl == D("93.00")


# --------------------------------------------------------------------------
# Score
# --------------------------------------------------------------------------

def test_score_ohne_trades_ist_none():
    result = sc.compute(m.compute([]))

    assert result.total is None
    assert len(result.missing) == len(sc.COMPONENTS)


def test_score_liegt_zwischen_null_und_hundert():
    trades = [
        trade("300", day=0),
        trade("200", day=1),
        trade("-100", day=2),
        trade("150", day=3),
        trade("-80", day=4),
    ]

    result = sc.compute(m.compute(trades))

    assert result.total is not None
    assert D("0") <= result.total <= D("100")
    # Jeder Teilwert einzeln sichtbar -- der Sinn der Zahl ist die
    # Aufschlüsselung, nicht der Gesamtwert.
    assert set(result.parts) == set(sc.COMPONENTS)


def test_fehlende_teilwerte_ziehen_den_score_nicht_nach_unten():
    """Ohne Verluste fehlt der Profit Factor -- das ist kein schlechter Wert."""
    trades = [trade("300", day=0), trade("200", day=1)]

    result = sc.compute(m.compute(trades))

    assert "profit_factor" in result.missing
    assert result.parts["profit_factor"] is None
    # Trotzdem ein Gesamtwert, gebildet aus den vorhandenen Teilen.
    assert result.total is not None


def test_band_begrenzt_nach_oben_und_unten():
    band = sc.Band(D("1.0"), D("2.5"))

    assert band.normalise(D("0.2")) == D("0")
    assert band.normalise(D("9.0")) == D("100")


def test_invertiertes_band_bewertet_niedrige_werte_besser():
    band = sc.Band(D("0"), D("1"), inverted=True)

    assert band.normalise(D("0")) == D("100")
    assert band.normalise(D("1")) == D("0")

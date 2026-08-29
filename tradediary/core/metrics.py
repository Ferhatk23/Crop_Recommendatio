"""Kennzahlen über eine Menge von Trades.

Jede einzelne Formel hier ist zwei Zeilen lang. Der Aufwand steckt nicht in
der Rechnung, sondern in den Randfällen -- und die sind der Grund, warum
dieses Modul existiert statt die Werte irgendwo in der Oberfläche zu bilden:

* Ein Trade mit genau null ist weder Gewinn noch Verlust und gehört aus der
  Trefferquote heraus.
* Ohne einen einzigen Verlust ist der Profit Factor undefiniert, nicht
  unendlich und schon gar nicht null.
* Ohne erfassten Stop gibt es kein R-Multiple. `None` ist die ehrliche
  Antwort, 0 wäre eine erfundene.

Wo ein Wert nicht bestimmbar ist, steht `None`. Die Oberfläche zeigt dann
einen Strich. Eine Zahl, die aussieht wie eine Zahl, aber keine Aussage
trägt, ist schlimmer als eine Lücke.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .models import ZERO, Outcome, Trade


@dataclass(frozen=True)
class Metrics:
    """Das Ergebnis einer Auswertung. Alles auf Netto, also nach Kosten."""

    trade_count: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0

    net_pnl: Decimal = ZERO
    gross_profit: Decimal = ZERO
    #: Als positive Zahl geführt, damit der Profit Factor lesbar bleibt.
    gross_loss: Decimal = ZERO
    total_costs: Decimal = ZERO

    win_rate: Decimal | None = None
    profit_factor: Decimal | None = None
    avg_win: Decimal | None = None
    avg_loss: Decimal | None = None
    win_loss_ratio: Decimal | None = None
    expectancy: Decimal | None = None
    expectancy_r: Decimal | None = None

    max_drawdown: Decimal = ZERO
    recovery_factor: Decimal | None = None
    consistency: Decimal | None = None

    largest_win: Decimal | None = None
    largest_loss: Decimal | None = None
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    trading_days: int = 0
    #: Trades ohne erfassten Stop. Die Oberfläche soll sagen können, auf wie
    #: vielen Trades die R-Kennzahlen überhaupt beruhen.
    trades_without_stop: int = 0


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Division, die bei Null nicht lügt."""
    if denominator == ZERO:
        return None
    return numerator / denominator


def max_drawdown_by_sequence(trades: list[Trade]) -> Decimal:
    """Größter Rückgang auf der Trade-für-Trade-Equity-Kurve.

    Bewusste Festlegung: gerechnet wird über die Reihenfolge der
    Schließungen, nicht über Tagessalden. Beide Varianten sind üblich und
    liefern unterschiedliche Werte -- deshalb steht die gewählte hier im Code
    und gehört auch in die Oberfläche geschrieben.
    """
    peak = ZERO
    equity = ZERO
    worst = ZERO
    for trade in sorted(trades, key=lambda t: t.closed_at or t.opened_at):
        equity += trade.net_pnl
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def daily_pnl(trades: list[Trade]) -> dict[date, Decimal]:
    """Netto-Ergebnis je Handelstag, nach Schließungsdatum."""
    per_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for trade in trades:
        when = trade.closed_at or trade.opened_at
        per_day[when.date()] += trade.net_pnl
    return dict(per_day)


def consistency(trades: list[Trade]) -> Decimal | None:
    """Wie stark hängt das Ergebnis an einem einzigen guten Tag?

    1 bedeutet gleichmäßig verteilt, nahe 0 bedeutet: ein Glückstag trägt
    das ganze Konto. Die Kennzahl, die niemand sehen will und jeder braucht
    -- und bei Prop-Konten oft sogar eine harte Regel.
    """
    winning_days = [pnl for pnl in daily_pnl(trades).values() if pnl > ZERO]
    if not winning_days:
        return None
    total = sum(winning_days, ZERO)
    if total == ZERO:
        return None
    return Decimal("1") - (max(winning_days) / total)


def _streaks(trades: list[Trade]) -> tuple[int, int]:
    """Längste Serie an Gewinnen und an Verlusten.

    Scratches unterbrechen keine Serie -- sie sind kein Ergebnis, sondern
    dessen Abwesenheit.
    """
    best_win = best_loss = run_win = run_loss = 0
    for trade in sorted(trades, key=lambda t: t.closed_at or t.opened_at):
        outcome = trade.outcome
        if outcome is Outcome.WIN:
            run_win += 1
            run_loss = 0
        elif outcome is Outcome.LOSS:
            run_loss += 1
            run_win = 0
        else:
            continue
        best_win = max(best_win, run_win)
        best_loss = max(best_loss, run_loss)
    return best_win, best_loss


def compute(trades: list[Trade]) -> Metrics:
    """Rechnet alle Kennzahlen über die geschlossenen Trades.

    Offene Trades bleiben außen vor: Ihr Ergebnis steht noch nicht fest, und
    ein schwebender Buchgewinn in der Trefferquote wäre eine Behauptung über
    einen Ausgang, den es noch nicht gibt.
    """
    closed = [t for t in trades if not t.is_open]
    if not closed:
        return Metrics()

    wins = [t for t in closed if t.outcome is Outcome.WIN]
    losses = [t for t in closed if t.outcome is Outcome.LOSS]
    scratches = [t for t in closed if t.outcome is Outcome.SCRATCH]

    gross_profit = sum((t.net_pnl for t in wins), ZERO)
    gross_loss = -sum((t.net_pnl for t in losses), ZERO)
    net_pnl = sum((t.net_pnl for t in closed), ZERO)
    total_costs = sum((t.costs for t in closed), ZERO)

    # Scratches zählen weder im Zähler noch im Nenner.
    decided = Decimal(len(wins) + len(losses))
    win_rate = _safe_div(Decimal(len(wins)), decided)

    avg_win = _safe_div(gross_profit, Decimal(len(wins)))
    avg_loss = _safe_div(gross_loss, Decimal(len(losses)))
    win_loss_ratio = (
        avg_win / avg_loss if avg_win is not None and avg_loss else None
    )

    expectancy = _safe_div(net_pnl, decided) if decided else None

    # R-Kennzahlen nur über die Trades, bei denen ein Stop erfasst war.
    r_values = [t.r_multiple for t in closed if t.r_multiple is not None]
    expectancy_r = (
        sum(r_values, ZERO) / Decimal(len(r_values)) if r_values else None
    )

    drawdown = max_drawdown_by_sequence(closed)
    best_win_streak, best_loss_streak = _streaks(closed)

    return Metrics(
        trade_count=len(closed),
        wins=len(wins),
        losses=len(losses),
        scratches=len(scratches),
        net_pnl=net_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        total_costs=total_costs,
        win_rate=win_rate,
        # Ohne Verluste undefiniert -- nicht unendlich, nicht null.
        profit_factor=_safe_div(gross_profit, gross_loss),
        avg_win=avg_win,
        avg_loss=avg_loss,
        win_loss_ratio=win_loss_ratio,
        expectancy=expectancy,
        expectancy_r=expectancy_r,
        max_drawdown=drawdown,
        recovery_factor=_safe_div(net_pnl, drawdown),
        consistency=consistency(closed),
        largest_win=max((t.net_pnl for t in wins), default=None),
        largest_loss=min((t.net_pnl for t in losses), default=None),
        max_consecutive_wins=best_win_streak,
        max_consecutive_losses=best_loss_streak,
        trading_days=len(daily_pnl(closed)),
        trades_without_stop=sum(1 for t in closed if t.r_multiple is None),
    )

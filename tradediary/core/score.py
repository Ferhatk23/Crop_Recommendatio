"""Ein Gesamtwert von 0 bis 100 aus sechs Teilwerten.

Das Gegenstück zum Zella-Score. Der Sinn ist nicht die eine Zahl -- die ist
für sich genommen ziemlich nichtssagend -- sondern die Aufschlüsselung
dahinter: Sie zeigt, *woran* es liegt. Ein Konto mit Score 55 kann eine
hervorragende Trefferquote und einen katastrophalen Drawdown haben, und genau
das soll man sehen.

Die Schwellen und Gewichte stehen bewusst als benannte Konstanten hier oben
statt verstreut im Code. Sie sind eine Festlegung, keine Wahrheit -- wer sie
anders sieht, soll sie an einer Stelle ändern können.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .metrics import Metrics

ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class Band:
    """Ab welchem Wert 0 Punkte, ab welchem 100."""

    floor: Decimal
    ceiling: Decimal
    #: True, wenn ein *niedrigerer* Wert besser ist (etwa Drawdown).
    inverted: bool = False

    def normalise(self, value: Decimal) -> Decimal:
        span = self.ceiling - self.floor
        if span == ZERO:
            return ZERO
        share = (value - self.floor) / span
        share = max(ZERO, min(Decimal("1"), share))
        if self.inverted:
            share = Decimal("1") - share
        return share * HUNDRED


#: Die sechs Teilwerte: Bewertungsspanne und Gewicht.
#: Die Gewichte summieren sich auf 1.
COMPONENTS: dict[str, tuple[Band, Decimal]] = {
    # Eine Trefferquote über 60 % ist stark; unter 20 % trägt sie nur mit
    # sehr großem Chance-Risiko-Verhältnis.
    "win_rate": (Band(Decimal("0.20"), Decimal("0.60")), Decimal("0.15")),
    # Unter 1.0 verliert die Strategie Geld, 2.5 ist sehr gut.
    "profit_factor": (Band(Decimal("1.0"), Decimal("2.5")), Decimal("0.25")),
    # Das Verhältnis aus mittlerem Gewinn zu mittlerem Verlust.
    "win_loss_ratio": (Band(Decimal("0.5"), Decimal("2.5")), Decimal("0.20")),
    # Ertrag je Einheit Schmerz. Unter 1 war der größte Rückschlag größer
    # als der gesamte Gewinn.
    "recovery_factor": (Band(Decimal("0.5"), Decimal("5.0")), Decimal("0.15")),
    # Drawdown im Verhältnis zum Bruttogewinn -- weniger ist besser.
    "drawdown_ratio": (
        Band(Decimal("0.0"), Decimal("1.0"), inverted=True),
        Decimal("0.15"),
    ),
    # Wie stark das Ergebnis an einem einzigen Tag hängt.
    "consistency": (Band(ZERO, Decimal("1.0")), Decimal("0.10")),
}


@dataclass(frozen=True)
class Score:
    total: Decimal | None
    parts: dict[str, Decimal | None]
    #: Teilwerte, die mangels Daten nicht bestimmbar waren. Die Oberfläche
    #: soll sagen können, worauf der Gesamtwert beruht -- und worauf nicht.
    missing: tuple[str, ...]


def _raw_values(metrics: Metrics) -> dict[str, Decimal | None]:
    drawdown_ratio: Decimal | None = None
    if metrics.gross_profit > ZERO:
        drawdown_ratio = metrics.max_drawdown / metrics.gross_profit

    return {
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
        "win_loss_ratio": metrics.win_loss_ratio,
        "recovery_factor": metrics.recovery_factor,
        "drawdown_ratio": drawdown_ratio,
        "consistency": metrics.consistency,
    }


def compute(metrics: Metrics) -> Score:
    """Bildet den Gesamtwert und die sechs Teilwerte.

    Fehlt ein Teilwert -- etwa der Profit Factor, weil es noch keinen Verlust
    gibt -- wird er übersprungen und die Gewichte der übrigen anteilig
    hochgerechnet. Ein fehlender Wert soll die Bewertung nicht nach unten
    ziehen, als wäre er schlecht; er ist schlicht nicht da.
    """
    if metrics.trade_count == 0:
        return Score(total=None, parts={}, missing=tuple(COMPONENTS))

    raw = _raw_values(metrics)
    parts: dict[str, Decimal | None] = {}
    missing: list[str] = []

    weighted_sum = ZERO
    weight_used = ZERO

    for name, (band, weight) in COMPONENTS.items():
        value = raw.get(name)
        if value is None:
            parts[name] = None
            missing.append(name)
            continue
        points = band.normalise(value)
        parts[name] = points
        weighted_sum += points * weight
        weight_used += weight

    total = weighted_sum / weight_used if weight_used > ZERO else None
    return Score(total=total, parts=parts, missing=tuple(missing))

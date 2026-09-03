"""Prop-Regeln: wie viel Puffer bleibt bis zum Limit.

Für einen Prop-Trader ist das die wichtigste Zahl im Produkt -- wichtiger
als der Profit Factor. Ein gerissenes Tageslimit kostet das Konto, eine
mittelmäßige Trefferquote kostet nur Zeit.

Drei Regeln werden geführt:

* **Tagesverlust** -- der heutige Verlust gegen das Tageslimit.
* **Gesamtverlust** -- der Rückgang vom Höchststand gegen das Gesamtlimit.
* **Konsistenz** -- der Anteil des besten Tages am Gesamtgewinn. Bei Alpha
  Capital sind 40 % die Grenze; wer sie reißt, bekommt nicht ausgezahlt,
  obwohl er im Plus ist.

Die Funktionen hier rechnen nur. Was ein Limit ist, steht am Konto -- und
ohne hinterlegtes Limit gibt es keinen Puffer, sondern `None`. Ein
geschätzter Puffer wäre gefährlicher als gar keiner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from .metrics import daily_pnl
from .models import ZERO, Trade

EINS = Decimal("1")


class Ampel(str):
    """Wie kritisch ein Puffer ist."""

    OK = "ok"
    WARNUNG = "warnung"
    GERISSEN = "gerissen"


@dataclass(frozen=True)
class Puffer:
    """Der Stand einer einzelnen Regel."""

    #: Wie die Regel heißt, für die Anzeige.
    label: str
    #: Wie viel bereits verbraucht ist, als positive Zahl.
    verbraucht: Decimal
    #: Das Limit, ebenfalls positiv. `None`, wenn keins hinterlegt ist.
    limit: Decimal | None
    #: Ab welchem Anteil gewarnt wird.
    warn_ab: Decimal = Decimal("0.8")
    #: Warum nicht messbar -- Pflicht, wenn `limit` fehlt.
    grund: str | None = None

    @property
    def messbar(self) -> bool:
        return self.limit is not None and self.limit > ZERO

    @property
    def rest(self) -> Decimal | None:
        """Wie viel noch bleibt. Nie negativ -- bei Überschreitung null."""
        if not self.messbar:
            return None
        return max(ZERO, self.limit - self.verbraucht)

    @property
    def anteil(self) -> Decimal | None:
        """Verbrauchter Anteil, 0 bis 1. Über 1 wird nicht gekappt."""
        if not self.messbar:
            return None
        return self.verbraucht / self.limit

    @property
    def ampel(self) -> str:
        if not self.messbar:
            return Ampel.OK
        anteil = self.anteil
        if anteil >= EINS:
            return Ampel.GERISSEN
        if anteil >= self.warn_ab:
            return Ampel.WARNUNG
        return Ampel.OK


@dataclass(frozen=True)
class Regelstand:
    """Alle Regeln eines Kontos auf einen Blick."""

    tagesverlust: Puffer
    gesamtverlust: Puffer
    konsistenz: Puffer

    @property
    def alle(self) -> tuple[Puffer, ...]:
        return (self.tagesverlust, self.gesamtverlust, self.konsistenz)

    @property
    def konto_verloren(self) -> bool:
        """Ist eine Verlustregel gerissen?

        Die Konsistenzregel zählt hier bewusst nicht: Sie kostet die
        Auszahlung, nicht das Konto -- und sie lässt sich durch weiteres
        Handeln wieder einfangen, ein gerissenes Verlustlimit nicht.
        """
        return any(
            p.ampel == Ampel.GERISSEN
            for p in (self.tagesverlust, self.gesamtverlust)
        )

    @property
    def dringendste(self) -> Puffer:
        """Der Puffer, der am nächsten am Limit steht."""
        messbar = [p for p in self.alle if p.messbar]
        if not messbar:
            return self.tagesverlust
        return max(messbar, key=lambda p: p.anteil)


def tagesverlust(
    trades: list[Trade], tag: date | None = None
) -> Decimal:
    """Verlust des Tages als positive Zahl. Im Plus: null.

    Gerechnet wird auf dem realisierten Ergebnis des Tages. Ein
    Buchgewinn auf einer offenen Position zählt nicht -- Prop-Firmen
    rechnen das teils anders, deshalb steht die Wahl hier im Code und
    gehört in die Oberfläche geschrieben.
    """
    tag = tag or datetime.now(timezone.utc).date()
    ergebnis = daily_pnl([t for t in trades if not t.is_open]).get(tag, ZERO)
    return -ergebnis if ergebnis < ZERO else ZERO


def gesamtverlust(trades: list[Trade]) -> Decimal:
    """Rückgang vom Höchststand der Equity-Kurve, als positive Zahl.

    Das ist der übliche "trailing drawdown" der Prop-Firmen: nicht der
    Verlust gegenüber dem Startkapital, sondern gegenüber dem besten
    Stand, den das Konto je hatte.
    """
    geschlossen = sorted(
        (t for t in trades if not t.is_open),
        key=lambda t: t.closed_at or t.opened_at,
    )
    hoch = equity = ZERO
    for trade in geschlossen:
        equity += trade.net_pnl
        hoch = max(hoch, equity)
    return hoch - equity


def konsistenz_anteil(trades: list[Trade]) -> Decimal | None:
    """Anteil des besten Tages am Gesamtgewinn.

    `None`, solange es keinen Gewinntag gibt -- dann ist die Regel nicht
    anwendbar, nicht etwa erfüllt.
    """
    gewinntage = [p for p in daily_pnl(
        [t for t in trades if not t.is_open]
    ).values() if p > ZERO]
    if not gewinntage:
        return None
    summe = sum(gewinntage, ZERO)
    if summe == ZERO:
        return None
    return max(gewinntage) / summe


def bewerten(
    trades: list[Trade],
    daily_loss_limit: Decimal | None = None,
    max_loss_limit: Decimal | None = None,
    consistency_limit: Decimal | None = None,
    warn_ab: Decimal = Decimal("0.8"),
    tag: date | None = None,
) -> Regelstand:
    """Bildet den Regelstand eines Kontos."""
    anteil = konsistenz_anteil(trades)

    return Regelstand(
        tagesverlust=Puffer(
            label="Tagesverlust",
            verbraucht=tagesverlust(trades, tag),
            limit=daily_loss_limit,
            warn_ab=warn_ab,
            grund=None if daily_loss_limit else "kein Tageslimit hinterlegt",
        ),
        gesamtverlust=Puffer(
            label="Gesamtverlust",
            verbraucht=gesamtverlust(trades),
            limit=max_loss_limit,
            warn_ab=warn_ab,
            grund=None if max_loss_limit else "kein Gesamtlimit hinterlegt",
        ),
        konsistenz=Puffer(
            label="Konsistenz",
            verbraucht=anteil if anteil is not None else ZERO,
            limit=consistency_limit,
            warn_ab=warn_ab,
            grund=(
                "kein Konsistenzlimit hinterlegt"
                if not consistency_limit
                else ("noch kein Gewinntag" if anteil is None else None)
            ),
        ),
    )

"""Erzeugt einen realistischen Beispiel-Datenbestand.

Damit lassen sich Oberfläche und API entwickeln, bevor die MT5-Anbindung
steht -- und zwar an Daten, die sich benehmen wie echte: Aufstockungen,
Teilausstiege, Kommission auf der Eröffnung, Swap über Nacht, ein paar
Break-even-Trades, Handelspausen am Wochenende.

Die Zahlen sind erfunden, aber die *Struktur* nicht. Wer die Oberfläche an
zu braven Daten baut, entdeckt die hässlichen Fälle erst beim ersten
echten Import.
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from ..core.models import ZERO, Deal, DealEntry, DealType

D = lambda v: Decimal(str(v))

#: Symbol -> (typischer Preis, Preisspanne je Trade, Wert je Preiseinheit
#: und Lot). Grob an echten Kontraktgrößen orientiert.
SYMBOLE = {
    "EURUSD": (D("1.0850"), D("0.0040"), D("100000")),
    "GBPUSD": (D("1.2650"), D("0.0055"), D("100000")),
    "USDJPY": (D("151.20"), D("0.60"), D("670")),
    "XAUUSD": (D("2420.00"), D("18.00"), D("100")),
    "US30":   (D("39150.0"), D("120.0"), D("1")),
}

SETUPS = ["Breakout", "Pullback", "News-Fade", "Range-Reversal", "Trend-Continuation"]
FEHLER = ["zu früh raus", "Regel gebrochen", "nachgekauft", "kein Stop", "Rache-Trade"]


def _handelstage(ende: datetime, anzahl: int) -> list[datetime]:
    """Die letzten `anzahl` Werktage bis einschließlich `ende`.

    Rückwärts gezählt, nicht vorwärts: Die Historie soll bis heute
    reichen. Zählt man vorwärts von einem geschätzten Startdatum, endet
    sie irgendwo in der Vergangenheit -- und die App sieht beim ersten
    Öffnen aus, als wäre seit Wochen nichts passiert.
    """
    tage, zeiger = [], ende
    while len(tage) < anzahl:
        if zeiger.weekday() < 5:
            tage.append(zeiger)
        zeiger -= timedelta(days=1)
    return list(reversed(tage))


def erzeuge_deals(
    account_id: str = "1",
    handelstage: int = 45,
    ende: datetime | None = None,
    seed: int = 20260315,
    startkapital: Decimal = D("100000"),
) -> list[Deal]:
    """Baut eine Deal-Historie, die sich wie eine echte verhält."""
    rng = random.Random(seed)
    ende = ende or datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    tage_liste = _handelstage(ende, handelstage)
    start = tage_liste[0]

    deals: list[Deal] = []
    ticket = 500_000
    position_id = 900_000

    # Eröffnungsbuchung -- gehört in die Equity-Kurve, nie in die Trades.
    deals.append(
        Deal(
            ticket=ticket,
            account_id=account_id,
            position_id=0,
            symbol="",
            type=DealType.BALANCE,
            entry=DealEntry.IN,
            volume=ZERO,
            price=ZERO,
            time_utc=start - timedelta(days=1),
            profit=startkapital,
        )
    )
    ticket += 1

    for tag in tage_liste:
        # Manche Tage wird gar nicht gehandelt.
        if rng.random() < 0.12:
            continue

        for _ in range(rng.choices([1, 2, 3, 4, 5], weights=[3, 5, 4, 2, 1])[0]):
            symbol = rng.choice(list(SYMBOLE))
            basis, spanne, wert_je_einheit = SYMBOLE[symbol]

            long = rng.random() < 0.55
            lot = D(rng.choice(["0.20", "0.35", "0.50", "0.75", "1.00", "1.50"]))
            einstieg = (basis + D(rng.uniform(-1, 1)) * spanne * 3).quantize(
                D("0.00001")
            )

            # Etwas mehr Gewinner als Verlierer, aber Verlierer im Schnitt
            # kleiner -- sonst sieht die Kennzahlen-Ansicht unrealistisch aus.
            gewinnt = rng.random() < 0.56
            bewegung = spanne * D(rng.uniform(0.25, 1.8))
            if not gewinnt:
                bewegung = -spanne * D(rng.uniform(0.3, 1.0))
            if not long:
                pass  # Richtung steckt schon im Ergebnis unten.

            richtung = D(1) if long else D(-1)
            ausstieg = (einstieg + bewegung * richtung).quantize(D("0.00001"))

            eroeffnung = datetime.combine(
                tag.date(),
                time(hour=rng.randint(7, 19), minute=rng.randint(0, 59)),
                tzinfo=timezone.utc,
            )
            dauer = timedelta(minutes=rng.choice([12, 25, 47, 90, 180, 420]))
            schluss = eroeffnung + dauer

            position_id += 1
            typ_auf = DealType.BUY if long else DealType.SELL
            typ_zu = DealType.SELL if long else DealType.BUY

            # Stop unterhalb (long) bzw. oberhalb (short) des Einstiegs.
            stop_abstand = spanne * D(rng.uniform(0.5, 1.1))
            stop = (einstieg - stop_abstand * richtung).quantize(D("0.00001"))

            kommission = (-lot * D("3.50")).quantize(D("0.01"))

            # Ein Teil der Trades wird aufgestockt.
            teile = [(lot, einstieg)]
            if rng.random() < 0.22:
                zusatz = (lot / D(2)).quantize(D("0.01"))
                teile = [
                    (lot, einstieg),
                    (zusatz, (einstieg - bewegung * richtung / D(4)).quantize(D("0.00001"))),
                ]

            gesamt_lot = sum((t[0] for t in teile), ZERO)

            for index, (teil_lot, teil_preis) in enumerate(teile):
                deals.append(
                    Deal(
                        ticket=ticket,
                        account_id=account_id,
                        position_id=position_id,
                        symbol=symbol,
                        type=typ_auf,
                        entry=DealEntry.IN,
                        volume=teil_lot,
                        price=teil_preis,
                        time_utc=eroeffnung + timedelta(minutes=index * 3),
                        profit=ZERO,
                        commission=(-teil_lot * D("3.50")).quantize(D("0.01")),
                        stop_loss=stop if index == 0 else None,
                    )
                )
                ticket += 1

            mittel_einstieg = sum(
                (t[0] * t[1] for t in teile), ZERO
            ) / gesamt_lot

            # Manche Trades werden in zwei Zügen geschlossen.
            schluss_teile = [gesamt_lot]
            if rng.random() < 0.28 and gesamt_lot > D("0.2"):
                haelfte = (gesamt_lot / D(2)).quantize(D("0.01"))
                schluss_teile = [haelfte, gesamt_lot - haelfte]

            for index, teil_lot in enumerate(schluss_teile):
                teil_preis = (
                    ausstieg
                    if index == len(schluss_teile) - 1
                    else (mittel_einstieg + (ausstieg - mittel_einstieg) * D("0.6"))
                ).quantize(D("0.00001"))

                brutto = (
                    (teil_preis - mittel_einstieg) * richtung * teil_lot * wert_je_einheit
                ).quantize(D("0.01"))

                # Über Nacht gehalten kostet Swap.
                swap = ZERO
                if dauer > timedelta(hours=8):
                    swap = (-teil_lot * D(rng.uniform(0.8, 3.2))).quantize(D("0.01"))

                deals.append(
                    Deal(
                        ticket=ticket,
                        account_id=account_id,
                        position_id=position_id,
                        symbol=symbol,
                        type=typ_zu,
                        entry=DealEntry.OUT,
                        volume=teil_lot,
                        price=teil_preis,
                        time_utc=schluss + timedelta(minutes=index * 8),
                        profit=brutto,
                        commission=(-teil_lot * D("3.50")).quantize(D("0.01")),
                        swap=swap,
                    )
                )
                ticket += 1

    return deals


def tags_fuer(rng: random.Random) -> tuple[str, str | None]:
    """Ein Setup-Tag, manchmal ein Fehler-Tag."""
    return rng.choice(SETUPS), (rng.choice(FEHLER) if rng.random() < 0.3 else None)

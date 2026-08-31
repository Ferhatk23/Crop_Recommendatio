"""Härtetest mit zufällig erzeugten Ausführungsfolgen.

Einzelne Beispiele prüfen die Fälle, an die man gedacht hat. Dieser Test
prüft die Fälle, an die man nicht gedacht hat: Er erzeugt tausende
Ausführungsfolgen und stellt sicher, dass ein paar Sätze *immer* gelten --
egal in welcher Reihenfolge gekauft, aufgestockt, teilverkauft und umgekehrt
wurde.

Der wichtigste dieser Sätze ist die Erhaltung: Was der Broker abgerechnet
hat, muss nach der Zuordnung auf die Trades exakt wieder herauskommen. Geht
dabei auch nur ein Cent verloren, weicht die Netto-Summe des Journals vom
Kontoauszug ab -- und das ist der Fehler, den man am längsten sucht, weil
alle Zahlen weiterhin plausibel aussehen.
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from conftest import BASE, D

from tradediary.core.models import Deal, DealEntry, DealType, Direction
from tradediary.core.roundtrip import trades_from_executions

ZERO = D(0)
LOTS = [D("0.25"), D("0.50"), D("1.00"), D("1.50"), D("2.00"), D("3.00")]


def zufallsfolge(rng: random.Random, laenge: int) -> list[Deal]:
    """Erzeugt eine plausible Kette von Ausführungen für ein Symbol.

    Die Position wird mitgeführt, damit die Ausführungen zueinander passen --
    aber Richtung und Größe wählt der Zufall, sodass Aufstockungen,
    Teilausstiege und Umkehrungen von allein entstehen.
    """
    deals: list[Deal] = []
    position = ZERO

    for i in range(laenge):
        volume = rng.choice(LOTS)
        kauft = rng.choice([True, False])
        signiert = volume if kauft else -volume

        schliesst = position != ZERO and (position > ZERO) != (signiert > ZERO)
        if schliesst:
            entry = DealEntry.INOUT if volume > abs(position) else DealEntry.OUT
        else:
            entry = DealEntry.IN

        deals.append(
            Deal(
                ticket=i + 1,
                account_id="A1",
                position_id=0,
                symbol="EURUSD",
                type=DealType.BUY if kauft else DealType.SELL,
                entry=entry,
                volume=volume,
                price=D("1.08") + D(rng.randint(0, 400)) / D(10000),
                time_utc=BASE + timedelta(minutes=i * 7),
                # Ergebnis nur auf schließenden Ausführungen -- so bucht MT5.
                profit=D(rng.randint(-50000, 50000)) / D(100) if schliesst else ZERO,
                commission=D(rng.randint(0, 900)) / D(-100),
                swap=D(rng.randint(-300, 100)) / D(100) if schliesst else ZERO,
            )
        )
        position += signiert

    return deals


def test_geld_geht_niemals_verloren():
    """Die Summe über alle Trades muss der Summe über alle Deals entsprechen."""
    rng = random.Random(20260831)

    for durchlauf in range(500):
        deals = zufallsfolge(rng, rng.randint(1, 25))
        trades = trades_from_executions(deals)

        deal_brutto = sum((d.profit for d in deals), ZERO)
        deal_kosten = sum((d.costs for d in deals), ZERO)
        trade_brutto = sum((t.gross_pnl for t in trades), ZERO)
        trade_kosten = sum((t.costs for t in trades), ZERO)

        assert trade_brutto == deal_brutto, (
            f"Durchlauf {durchlauf}: Brutto weicht ab "
            f"({trade_brutto} statt {deal_brutto})"
        )
        assert trade_kosten == deal_kosten, (
            f"Durchlauf {durchlauf}: Kosten weichen ab "
            f"({trade_kosten} statt {deal_kosten})"
        )


def test_volumen_geht_niemals_verloren():
    """Jedes gehandelte Lot muss in genau einem Trade auftauchen."""
    rng = random.Random(4711)

    for durchlauf in range(500):
        deals = zufallsfolge(rng, rng.randint(1, 25))
        trades = trades_from_executions(deals)

        gehandelt = sum((d.volume for d in deals), ZERO)
        # Jedes Lot ist entweder ein Einstieg oder ein Ausstieg genau eines
        # Trades. Bei einem Bruchstück ist der Einstieg unbekannt und zählt
        # nicht mit.
        zugeordnet = sum(
            ((ZERO if t.partial else t.volume) + t.exit_volume for t in trades),
            ZERO,
        )

        assert zugeordnet == gehandelt, (
            f"Durchlauf {durchlauf}: {zugeordnet} statt {gehandelt} Lot"
        )


def test_strukturelle_zusicherungen_gelten_immer():
    """Sätze, die für jeden erzeugten Trade gelten müssen."""
    rng = random.Random(1337)

    for durchlauf in range(500):
        deals = zufallsfolge(rng, rng.randint(1, 25))
        trades = trades_from_executions(deals)

        # Höchstens ein offener Trade je Symbol -- die Position kann nicht
        # gleichzeitig long und short offen sein.
        offene = [t for t in trades if t.is_open]
        assert len(offene) <= 1, f"Durchlauf {durchlauf}: {len(offene)} offene Trades"

        for trade in trades:
            assert trade.volume > ZERO
            assert trade.direction in (Direction.LONG, Direction.SHORT)
            assert trade.opened_at is not None
            assert trade.deal_tickets

            if trade.is_open:
                assert trade.avg_exit is None
                assert trade.closed_at is None
            else:
                assert trade.avg_exit is not None
                assert trade.closed_at is not None
                assert trade.closed_at >= trade.opened_at
                assert trade.duration is not None
                assert trade.duration >= timedelta(0)


def test_reihenfolge_der_eingabe_ist_egal():
    """Gemischte Eingabe muss dasselbe Ergebnis liefern wie sortierte.

    Die Quelle liefert nicht garantiert chronologisch -- und wenn die
    Sortierung im Modul greift, darf das keinen Unterschied machen.
    """
    rng = random.Random(99)

    for _ in range(200):
        deals = zufallsfolge(rng, rng.randint(2, 20))
        gemischt = deals[:]
        rng.shuffle(gemischt)

        a = trades_from_executions(deals)
        b = trades_from_executions(gemischt)

        assert len(a) == len(b)
        assert [t.net_pnl for t in a] == [t.net_pnl for t in b]
        assert [t.direction for t in a] == [t.direction for t in b]


def test_ohne_ausstieg_kein_realisiertes_ergebnis():
    """Wer noch nichts glattgestellt hat, hat noch nichts realisiert.

    Das ist der Satz, den der reparierte Bug verletzt hat: Bei einer Umkehr
    bekam der frisch eröffnete Teil anteilig Gewinn zugeschrieben, obwohl er
    keine einzige Position geschlossen hatte.

    Achtung, der Satz gilt nur ohne Ausstieg -- ein *offener* Trade mit
    Teilausstiegen trägt sehr wohl realisiertes Ergebnis.
    """
    rng = random.Random(2024)
    geprueft = 0

    for durchlauf in range(500):
        deals = zufallsfolge(rng, rng.randint(1, 25))
        trades = trades_from_executions(deals)

        for trade in trades:
            if trade.exit_volume == ZERO:
                geprueft += 1
                assert trade.gross_pnl == ZERO, (
                    f"Durchlauf {durchlauf}: Trade ohne Ausstieg traegt "
                    f"{trade.gross_pnl} an realisiertem Ergebnis"
                )

    # Der Test soll nicht durchlaufen, weil er nichts gefunden hat.
    assert geprueft > 50, f"nur {geprueft} Trades ohne Ausstieg geprueft"


def hedging_folge(rng: random.Random, anzahl: int) -> list[Deal]:
    """Erzeugt Ausführungen im Hedging-Stil, wie MT5 sie bei Forex liefert.

    Jede Position bekommt eine eigene `position_id`, Positionen werden
    nacheinander eröffnet und wieder geschlossen -- keine Umkehr, weil es
    die auf Hedging-Konten nicht gibt. Genau die Daten, mit denen der
    Abgleich beider Zuordnungswege etwas beweist.
    """
    deals: list[Deal] = []
    ticket = 0
    minute = 0

    for position_id in range(1, anzahl + 1):
        kauft = rng.choice([True, False])
        teile = rng.randint(1, 3)
        volumen = [rng.choice(LOTS) for _ in range(teile)]
        gesamt = sum(volumen, ZERO)

        for teil in volumen:
            ticket += 1
            minute += rng.randint(1, 5)
            deals.append(
                Deal(
                    ticket=ticket, account_id="A1", position_id=position_id,
                    symbol="EURUSD",
                    type=DealType.BUY if kauft else DealType.SELL,
                    entry=DealEntry.IN, volume=teil,
                    price=D("1.08") + D(rng.randint(0, 400)) / D(10000),
                    time_utc=BASE + timedelta(minutes=minute),
                    profit=ZERO,
                    commission=D(rng.randint(0, 400)) / D(-100),
                )
            )

        # Schliessen, in einem oder zwei Zuegen.
        rest = gesamt
        while rest > ZERO:
            ticket += 1
            minute += rng.randint(1, 20)
            teil = rest if rng.random() < 0.6 else (rest / D(2)).quantize(D("0.01"))
            teil = teil if teil > ZERO else rest
            deals.append(
                Deal(
                    ticket=ticket, account_id="A1", position_id=position_id,
                    symbol="EURUSD",
                    type=DealType.SELL if kauft else DealType.BUY,
                    entry=DealEntry.OUT, volume=teil,
                    price=D("1.08") + D(rng.randint(0, 400)) / D(10000),
                    time_utc=BASE + timedelta(minutes=minute),
                    profit=D(rng.randint(-30000, 30000)) / D(100),
                    commission=D(rng.randint(0, 400)) / D(-100),
                    swap=D(rng.randint(-200, 50)) / D(100),
                )
            )
            rest -= teil

    return deals


def test_beide_zuordnungswege_stimmen_unter_zufallslast_ueberein():
    """Der Abgleich muss auch bei tausenden erzeugten Positionen halten.

    Beide Wege kommen voellig unterschiedlich zum Ziel: einer folgt der
    position_id des Brokers, der andere allein der Reihenfolge der
    Ausfuehrungen. Dass sie uebereinstimmen, ist deshalb ein echter Beleg
    und keine Tautologie.
    """
    from tradediary.core.roundtrip import reconcile, trades_from_positions

    rng = random.Random(31415)

    for durchlauf in range(300):
        deals = hedging_folge(rng, rng.randint(1, 8))

        probleme = reconcile(deals)
        assert probleme == [], f"Durchlauf {durchlauf}: {probleme}"

        ueber_id = trades_from_positions(deals)
        ueber_folge = trades_from_executions(deals)

        assert len(ueber_id) == len(ueber_folge)
        assert [t.direction for t in ueber_id] == [t.direction for t in ueber_folge]
        assert [t.volume for t in ueber_id] == [t.volume for t in ueber_folge]
        assert [t.net_pnl for t in ueber_id] == [t.net_pnl for t in ueber_folge]

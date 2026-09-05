"""Tests für die messbaren Regeln.

Der Schwerpunkt liegt nicht auf den Vergleichen -- die sind trivial --,
sondern auf der dritten Antwort. Jede Prüfung muss `None` liefern, sobald
ihr eine Angabe fehlt. Ein `False` aus Unwissen wäre die schlimmste
Ausgabe dieses ganzen Programms: Es sähe aus wie ein Befund, wäre eine
Vermutung, und stünde am Ende als Regelbruch in einer Statistik, die
Disziplin messen soll.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tradediary.core.models import Direction, Trade
from tradediary.core.regelpruefung import (
    NACH_KEY,
    PRUEFUNGEN,
    parameter_lesen,
    pruefe,
)

START = datetime(2025, 3, 3, 9, 0, tzinfo=timezone.utc)


def trade(**abweichung) -> Trade:
    werte = dict(
        account_id="1",
        symbol="EURUSD",
        direction=Direction.LONG,
        opened_at=START,
        volume=Decimal("1.0"),
        avg_entry=Decimal("1.08000"),
        closed_at=START + timedelta(minutes=30),
        avg_exit=Decimal("1.08200"),
        exit_volume=Decimal("1.0"),
        gross_pnl=Decimal("200"),
        costs=Decimal("-7"),
        initial_sl=Decimal("1.07900"),
        risk_amount=Decimal("100"),
    )
    werte.update(abweichung)
    return Trade(**werte)


# ---------------------------------------------------------------------------
# Stop gesetzt
# ---------------------------------------------------------------------------

def test_stop_gesetzt():
    assert pruefe("stop_gesetzt", None, trade()) is True
    assert pruefe("stop_gesetzt", None, trade(initial_sl=None)) is False


def test_beim_bruchstueck_bleibt_der_stop_unbeantwortet():
    """Der Stop fehlt, weil wir die Eröffnung nicht gesehen haben.

    Nicht, weil keiner da war. Am Rand jedes Abfragefensters kommen solche
    Trades vor; als Regelbruch gezählt verdürben sie jede Quote.
    """
    assert pruefe("stop_gesetzt", None, trade(partial=True, initial_sl=None)) is None
    assert pruefe("stop_gesetzt", None, trade(partial=True)) is None


# ---------------------------------------------------------------------------
# Risiko
# ---------------------------------------------------------------------------

def test_risiko_unter_der_grenze():
    """100 € Risiko bei 100.000 € Startkapital sind 0,1 % -- unter 1 %."""
    assert (
        pruefe("risiko_hoechstens", "1", trade(), startkapital=Decimal("100000"))
        is True
    )


def test_risiko_ueber_der_grenze():
    assert (
        pruefe(
            "risiko_hoechstens",
            "1",
            trade(risk_amount=Decimal("1500")),
            startkapital=Decimal("100000"),
        )
        is False
    )


def test_genau_auf_der_grenze_gilt_als_eingehalten():
    """„Höchstens 1 %" schliesst 1 % ein. Sonst hiesse es „weniger als"."""
    assert (
        pruefe(
            "risiko_hoechstens",
            "1",
            trade(risk_amount=Decimal("1000")),
            startkapital=Decimal("100000"),
        )
        is True
    )


@pytest.mark.parametrize(
    "abweichung, konto",
    [
        ({"risk_amount": None}, Decimal("100000")),   # kein Stop, kein Risiko
        ({}, None),                                    # Startkapital unbekannt
        ({}, Decimal("0")),                            # Startkapital null
        ({"partial": True}, Decimal("100000")),        # Eröffnung nicht gesehen
    ],
)
def test_ohne_bezugsgroesse_bleibt_das_risiko_offen(abweichung, konto):
    assert pruefe("risiko_hoechstens", "1", trade(**abweichung), startkapital=konto) is None


# ---------------------------------------------------------------------------
# Haltedauer
# ---------------------------------------------------------------------------

def test_haltedauer():
    assert pruefe("haltedauer_hoechstens", "240", trade()) is True
    assert (
        pruefe(
            "haltedauer_hoechstens",
            "10",
            trade(closed_at=START + timedelta(hours=3)),
        )
        is False
    )


def test_ein_offener_trade_hat_keine_haltedauer():
    assert pruefe("haltedauer_hoechstens", "240", trade(closed_at=None)) is None


def test_ein_bruchstueck_ueber_der_grenze_ist_ein_befund():
    """Die gemessene Dauer ist kürzer als die echte.

    Reisst schon dieser Ausschnitt die Grenze, steht der Bruch fest.
    """
    lang = trade(partial=True, closed_at=START + timedelta(hours=9))
    assert pruefe("haltedauer_hoechstens", "60", lang) is False


def test_ein_bruchstueck_unter_der_grenze_beweist_nichts():
    """Der Test, der beim ersten Anlauf gefehlt hat -- und die Lücke, die
    er hätte zeigen sollen.

    Bei einem Bruchstück liegt die echte Eröffnung vor dem abgefragten
    Zeitraum, die gemessene Dauer ist also zu kurz. Dreissig gesehene
    Minuten unter einer Grenze von sechzig heissen nicht "eingehalten" --
    der ungesehene Teil kann Stunden gedauert haben. Ein `True` wäre hier
    ein Freispruch aus Nichtwissen.
    """
    kurz = trade(partial=True, closed_at=START + timedelta(minutes=30))
    assert pruefe("haltedauer_hoechstens", "60", kurz) is None
    # Ohne Bruchstück ist dieselbe Messung eine Aussage.
    assert pruefe("haltedauer_hoechstens", "60", trade()) is True


# ---------------------------------------------------------------------------
# Volumen und Einstiege
# ---------------------------------------------------------------------------

def test_volumen():
    assert pruefe("volumen_hoechstens", "1.0", trade()) is True
    assert pruefe("volumen_hoechstens", "0.5", trade()) is False


def test_nicht_nachgekauft():
    assert pruefe("nur_ein_einstieg", None, trade(), einstiege=1) is True
    assert pruefe("nur_ein_einstieg", None, trade(), einstiege=3) is False


def test_ohne_die_zahl_der_einstiege_bleibt_es_offen():
    assert pruefe("nur_ein_einstieg", None, trade(), einstiege=None) is None


@pytest.mark.parametrize(
    "key, parameter, kwargs, gesehen_reisst, gesehen_haelt",
    [
        ("volumen_hoechstens", "0.5", {}, {"volume": Decimal("2")}, {"volume": Decimal("0.4")}),
        ("nur_ein_einstieg", None, {"einstiege": 3}, {}, None),
    ],
)
def test_die_halbregel_gilt_fuer_alle_zu_klein_messbaren(
    key, parameter, kwargs, gesehen_reisst, gesehen_haelt
):
    """Dieselbe Asymmetrie wie bei der Haltedauer.

    Volumen und Zahl der Einstiege sind beim Bruchstück ebenfalls zu
    klein: Was vor dem Zeitraum liegt, sehen wir nicht. Ein Ausschnitt
    über der Grenze beweist den Bruch, ein Ausschnitt darunter beweist
    nichts.
    """
    reisst = trade(partial=True, **gesehen_reisst)
    assert pruefe(key, parameter, reisst, **kwargs) is False

    if gesehen_haelt is not None:
        haelt = trade(partial=True, **gesehen_haelt)
        assert pruefe(key, parameter, haelt, **kwargs) is None


def test_ein_gesehener_einstieg_beim_bruchstueck_beweist_nichts():
    assert pruefe("nur_ein_einstieg", None, trade(partial=True), einstiege=1) is None
    assert pruefe("nur_ein_einstieg", None, trade(), einstiege=1) is True


# ---------------------------------------------------------------------------
# Der Parameter
# ---------------------------------------------------------------------------

def test_eine_zahlenregel_ohne_zahl_bleibt_offen():
    """Sie stumm auf „eingehalten" zu setzen, belohnte ein leeres Feld.

    Und zwar bei jedem einzelnen Trade -- die Quote stiege, weil jemand
    vergessen hat, eine Grenze einzutragen.
    """
    for leer in (None, "", "   ", "keine Zahl", "0", "-3"):
        assert pruefe("risiko_hoechstens", leer, trade(), startkapital=Decimal("100000")) is None


def test_komma_und_punkt_werden_beide_verstanden():
    """Auf einer deutschen Tastatur tippt man 0,5."""
    assert parameter_lesen("0,5") == Decimal("0.5")
    assert parameter_lesen("0.5") == Decimal("0.5")


def test_eine_unbekannte_pruefung_beantwortet_nichts():
    """Etwa nach einem Rückbau: Die Regel bleibt stehen, die Prüfung nicht.

    Sie muss dann offen bleiben, nicht plötzlich als gebrochen gelten.
    """
    assert pruefe("gibt_es_nicht", None, trade()) is None


def test_jede_pruefung_hat_einen_eindeutigen_schluessel():
    assert len(NACH_KEY) == len(PRUEFUNGEN)


def test_jede_zahlenregel_nennt_ihre_einheit():
    """Sonst tippt jemand Minuten in ein Prozentfeld und merkt es nie."""
    for p in PRUEFUNGEN:
        if p.einheit is not None:
            assert p.beispiel, f"{p.key} braucht ein Beispiel"

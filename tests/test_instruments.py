"""Tests für die Instrumententabelle.

Zwei Dinge hängen daran, und beide sind still: Wenn das Risiko falsch
ist, ist jedes R-Multiple falsch -- und ein R-Multiple sieht auch dann
plausibel aus, wenn es das nicht ist. Wenn die Stellenzahl falsch ist,
liest sich ein Indexkurs als "39.498,47676" und niemand erkennt ihn
wieder.
"""

from decimal import Decimal

import pytest

from tradediary.core import instruments

D = lambda v: Decimal(str(v))


# ---------------------------------------------------------------------------
# Symbolnamen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "roh, erwartet",
    [
        ("EURUSD", "EURUSD"),
        ("eurusd", "EURUSD"),
        ("  EURUSD  ", "EURUSD"),
        ("EURUSD.r", "EURUSD"),
        ("EURUSD_raw", "EURUSD"),
        ("EURUSD-ECN", "EURUSD"),
        ("EURUSD#", "EURUSD"),
        ("EURUSDm", "EURUSD"),
        ("EURUSDmicro", "EURUSD"),
        # Zahlen im Namen gehören dazu und dürfen nicht wegfallen.
        ("US30", "US30"),
        ("NAS100", "NAS100"),
        ("GER40", "GER40"),
    ],
)
def test_normalisiere_entfernt_broker_anhaengsel(roh, erwartet):
    assert instruments.normalisiere(roh) == erwartet


def test_normalisiere_laesst_unbekanntes_stehen():
    """Kein Ratespiel: Was nicht zuzuordnen ist, bleibt wie es ist."""
    assert instruments.normalisiere("BTCUSD") == "BTCUSD"


def test_finde_erkennt_geschriebene_varianten():
    assert instruments.finde("EURUSD.r") is instruments.STANDARD["EURUSD"]
    assert instruments.finde("XAUUSDm") is instruments.STANDARD["XAUUSD"]
    assert instruments.finde("gibtsnicht") is None


def test_eigene_tabelle_schlaegt_die_standardwerte():
    """Im Betrieb kommen die echten Angaben aus MT5 und gelten vorrangig."""
    eigen = {"EURUSD": instruments.Instrument("EURUSD", D(10_000), 4)}
    assert instruments.finde("EURUSD", eigen).value_per_unit == D(10_000)
    assert instruments.nachkommastellen("EURUSD", eigen) == 4


# ---------------------------------------------------------------------------
# Nachkommastellen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "symbol, stellen",
    [
        ("EURUSD", 5),
        ("USDJPY", 3),
        ("XAUUSD", 2),
        ("US30", 1),
    ],
)
def test_nachkommastellen_je_instrument(symbol, stellen):
    assert instruments.nachkommastellen(symbol) == stellen


def test_nachkommastellen_faellt_auf_fuenf_zurueck():
    """Ein Preis muss gesetzt werden -- hier gibt es kein "unbekannt".

    Fünf Stellen zeigen bei einem unbekannten Symbol zu viel, aber sie
    verschweigen nichts. Zwei Stellen machten aus 1,08420 ein "1,08" und
    damit aus zwei verschiedenen Kursen denselben.
    """
    assert instruments.nachkommastellen("BTCUSD") == 5


# ---------------------------------------------------------------------------
# Riskierter Betrag
# ---------------------------------------------------------------------------

def test_risiko_von_hand_nachgerechnet():
    """1,00 Lot EURUSD, 30 Pips Stop.

    30 Pips sind 0,00300. Ein Lot sind 100.000 Einheiten, also
    0,00300 × 100.000 × 1,00 = 300,00. Diese Zahl ist mit der Hand
    gerechnet und nicht aus dem Code übernommen.
    """
    assert instruments.risiko(
        "EURUSD", D("1.08420"), D("1.08120"), D("1.00")
    ) == D("300.00")


def test_risiko_skaliert_mit_der_groesse():
    halb = instruments.risiko("EURUSD", D("1.08420"), D("1.08120"), D("0.50"))
    assert halb == D("150.00")


def test_risiko_bei_gold():
    """0,50 Lot XAUUSD, 8,00 $ Stop: 8,00 × 100 × 0,50 = 400,00."""
    assert instruments.risiko(
        "XAUUSD", D("2420.00"), D("2412.00"), D("0.50")
    ) == D("400.00")


@pytest.mark.parametrize(
    "beschreibung, symbol, einstieg, stop, volumen",
    [
        ("ohne Stop", "EURUSD", D("1.08420"), None, D("1.00")),
        ("ohne Einstieg", "EURUSD", None, D("1.08120"), D("1.00")),
        ("unbekanntes Symbol", "BTCUSD", D("60000"), D("59000"), D("1.00")),
        ("Stop auf dem Einstieg", "EURUSD", D("1.08420"), D("1.08420"), D("1.00")),
        ("ohne Volumen", "EURUSD", D("1.08420"), D("1.08120"), D("0")),
    ],
)
def test_risiko_gibt_none_statt_zu_raten(beschreibung, symbol, einstieg, stop, volumen):
    """Null wäre hier die gefährlichste Antwort.

    Sie liefe entweder als Division durch null in die R-Berechnung oder --
    schlimmer -- läse sich als "risikofrei". `None` sagt stattdessen, was
    zutrifft: Für diesen Trade gibt es kein R.
    """
    assert (
        instruments.risiko(symbol, einstieg, stop, volumen) is None
    ), beschreibung


def test_risiko_ist_richtungsunabhaengig():
    """Ein Short mit Stop oberhalb riskiert genauso viel wie ein Long darunter."""
    long = instruments.risiko("EURUSD", D("1.08420"), D("1.08120"), D("1.00"))
    short = instruments.risiko("EURUSD", D("1.08120"), D("1.08420"), D("1.00"))
    assert long == short == D("300.00")

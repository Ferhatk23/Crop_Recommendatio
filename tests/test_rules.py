"""Tests fuer die Prop-Regeln.

Die wichtigste Zahl im Produkt -- und die, bei der ein Fehler am
teuersten ist: Wer glaubt, er habe noch Puffer, und hat keinen mehr,
verliert das Konto.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradediary.core import rules
from tradediary.core.models import Direction, Trade

BASE = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
D = lambda v: Decimal(str(v))
HEUTE = BASE.date()


def t(net, tag=0):
    o = BASE + timedelta(days=tag)
    return Trade(account_id="A", symbol="EURUSD", direction=Direction.LONG,
                 opened_at=o, closed_at=o + timedelta(minutes=30),
                 volume=D(1), avg_entry=D("1.08"), avg_exit=D("1.09"),
                 exit_volume=D(1), gross_pnl=D(net), costs=D(0))


# --- Tagesverlust -----------------------------------------------------------

def test_tagesverlust_nur_bei_minus():
    assert rules.tagesverlust([t(-300)], HEUTE) == D(300)
    assert rules.tagesverlust([t(300)], HEUTE) == D(0)
    assert rules.tagesverlust([t(-300), t(100)], HEUTE) == D(200)


def test_tagesverlust_zaehlt_nur_den_tag():
    trades = [t(-300, tag=0), t(-999, tag=1)]
    assert rules.tagesverlust(trades, HEUTE) == D(300)


def test_offene_trades_zaehlen_nicht_in_den_tagesverlust():
    offen = t(-500)
    offen.closed_at = None
    assert rules.tagesverlust([offen, t(-100)], HEUTE) == D(100)


# --- Gesamtverlust (trailing drawdown) --------------------------------------

def test_gesamtverlust_ist_rueckgang_vom_hoechststand():
    # Verlauf: +500, +200, +700 -> Hoch 500, Tief danach 200 -> aktuell 700
    # Rueckgang vom Hoch: 700 ist neues Hoch, also 0
    assert rules.gesamtverlust([t(500, 0), t(-300, 1), t(500, 2)]) == D(0)
    # Verlauf: +500, +200 -> Hoch 500, aktuell 200 -> Rueckgang 300
    assert rules.gesamtverlust([t(500, 0), t(-300, 1)]) == D(300)


def test_gesamtverlust_ohne_gewinn_misst_ab_null():
    """Wer nie im Plus war, hat sein Hoch bei null."""
    assert rules.gesamtverlust([t(-400, 0)]) == D(400)


# --- Konsistenz -------------------------------------------------------------

def test_konsistenz_anteil_des_besten_tages():
    trades = [t(600, 0), t(200, 1), t(200, 2)]
    assert rules.konsistenz_anteil(trades) == D("0.6")


def test_konsistenz_ohne_gewinntag_ist_none():
    """Nicht anwendbar ist nicht dasselbe wie erfuellt."""
    assert rules.konsistenz_anteil([t(-100, 0)]) is None


# --- Puffer -----------------------------------------------------------------

def test_puffer_rechnet_rest_und_anteil():
    p = rules.Puffer(label="Tag", verbraucht=D(412), limit=D(1000))
    assert p.messbar
    assert p.rest == D(588)
    assert p.anteil == D("0.412")
    assert p.ampel == rules.Ampel.OK


def test_puffer_warnt_ab_der_schwelle():
    p = rules.Puffer(label="Tag", verbraucht=D(850), limit=D(1000))
    assert p.ampel == rules.Ampel.WARNUNG
    assert p.rest == D(150)


def test_puffer_gerissen_bei_erreichtem_limit():
    p = rules.Puffer(label="Tag", verbraucht=D(1000), limit=D(1000))
    assert p.ampel == rules.Ampel.GERISSEN
    assert p.rest == D(0)


def test_ueberschreitung_kappt_den_rest_aber_nicht_den_anteil():
    p = rules.Puffer(label="Tag", verbraucht=D(1400), limit=D(1000))
    assert p.rest == D(0)          # nie negativ
    assert p.anteil == D("1.4")    # aber die Schwere bleibt sichtbar
    assert p.ampel == rules.Ampel.GERISSEN


def test_ohne_limit_kein_puffer_sondern_none():
    """Ein geschaetzter Puffer waere gefaehrlicher als gar keiner."""
    p = rules.Puffer(label="Tag", verbraucht=D(500), limit=None,
                     grund="kein Tageslimit hinterlegt")
    assert not p.messbar
    assert p.rest is None
    assert p.anteil is None
    assert p.grund


# --- Gesamtstand ------------------------------------------------------------

def test_bewerten_setzt_alle_drei_regeln():
    trades = [t(600, 0), t(200, 1), t(-412, 2)]
    stand = rules.bewerten(
        trades,
        daily_loss_limit=D(1000),
        max_loss_limit=D(5000),
        consistency_limit=D("0.4"),
        tag=(BASE + timedelta(days=2)).date(),
    )

    assert stand.tagesverlust.verbraucht == D(412)
    assert stand.tagesverlust.rest == D(588)
    # Hoch war 800, aktuell 388 -> Rueckgang 412
    assert stand.gesamtverlust.verbraucht == D(412)
    # Bester Tag 600 von 800 Gewinn = 0.75, Limit 0.4 -> gerissen
    assert stand.konsistenz.verbraucht == D("0.75")
    assert stand.konsistenz.ampel == rules.Ampel.GERISSEN


def test_konto_verloren_nur_bei_verlustregeln():
    """Die Konsistenzregel kostet die Auszahlung, nicht das Konto."""
    trades = [t(1000, 0), t(10, 1)]
    stand = rules.bewerten(trades, daily_loss_limit=D(1000),
                           max_loss_limit=D(5000), consistency_limit=D("0.4"),
                           tag=(BASE + timedelta(days=1)).date())
    assert stand.konsistenz.ampel == rules.Ampel.GERISSEN
    assert not stand.konto_verloren


def test_konto_verloren_bei_gerissenem_tageslimit():
    stand = rules.bewerten([t(-1000, 0)], daily_loss_limit=D(1000),
                           max_loss_limit=D(5000), tag=HEUTE)
    assert stand.tagesverlust.ampel == rules.Ampel.GERISSEN
    assert stand.konto_verloren


def test_dringendste_regel_wird_gefunden():
    trades = [t(-900, 0)]
    stand = rules.bewerten(trades, daily_loss_limit=D(1000),
                           max_loss_limit=D(5000), tag=HEUTE)
    # Tag: 900/1000 = 0.9 ; Gesamt: 900/5000 = 0.18
    assert stand.dringendste.label == "Tagesverlust"


def test_ohne_limits_ist_nichts_messbar_und_nichts_gerissen():
    stand = rules.bewerten([t(-5000, 0)], tag=HEUTE)
    assert not stand.konto_verloren
    assert all(not p.messbar for p in stand.alle)
    assert all(p.grund for p in stand.alle)

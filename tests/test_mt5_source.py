"""Tests für die Übersetzung von MT5-Deals.

Der Sammler unter Wine ist die brüchigste Stelle der Kette. Alles, was
sich hierher ziehen liess, wird deshalb hier geprüft -- drüben bleibt nur
verbinden, abrufen, schicken.

Der Schwerpunkt liegt auf der Zeit. Ein um zwei Stunden verschobener
Trade sieht in jeder Ansicht richtig aus: Er hat den richtigen Preis, das
richtige Ergebnis, das richtige Symbol. Nur der Kalender ordnet ihn dem
falschen Tag zu und die Auswertung nach Uhrzeit misst eine Stunde, in der
nie gehandelt wurde.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tradediary.core.models import DealEntry, DealType
from tradediary.sync import mt5_source as m

D = lambda v: Decimal(str(v))

#: 02.03.2026, 09:31:00 -- als Server-Wanduhr gelesen.
STEMPEL = datetime(2026, 3, 2, 9, 31, tzinfo=timezone.utc).timestamp()

EET = 2 * 3600      # Winterzeit bei Alpha Capital
EEST = 3 * 3600     # Sommerzeit


def roh(**kw):
    """Ein MT5-Datensatz, wie ihn der Sammler schickt."""
    basis = {
        "ticket": 500001,
        "time": STEMPEL,
        "type": 0,          # DEAL_TYPE_BUY
        "entry": 0,         # DEAL_ENTRY_IN
        "position_id": 900001,
        "symbol": "EURUSD",
        "volume": 1.0,
        "price": 1.0842,
        "profit": 0.0,
        "commission": -3.5,
        "swap": 0.0,
        "fee": 0.0,
        "sl": 0.0,
    }
    basis.update(kw)
    return basis


# ---------------------------------------------------------------------------
# Die Zeitfalle
# ---------------------------------------------------------------------------

def test_ohne_versatz_bleibt_die_zeit_wie_geliefert():
    d = m.deal_aus_mt5(roh(), "1", server_utc_offset=0)
    assert d.time_utc == datetime(2026, 3, 2, 9, 31, tzinfo=timezone.utc)


def test_serverzeit_wird_nach_utc_zurueckgerechnet():
    """Der Kern der Sache.

    MT5 liefert 09:31 Serverzeit. Bei UTC+2 war das 07:31 UTC. Ohne die
    Korrektur stünde der Trade zwei Stunden zu spät im Journal -- und
    zwar in jeder einzelnen Ansicht gleich falsch, also unauffällig.
    """
    d = m.deal_aus_mt5(roh(), "1", server_utc_offset=EET)
    assert d.time_utc == datetime(2026, 3, 2, 7, 31, tzinfo=timezone.utc)


def test_die_serverzeit_bleibt_zum_anzeigen_erhalten():
    """Wer um 09:31 eine Order gesetzt hat, will sie um 09:31 wiederfinden."""
    d = m.deal_aus_mt5(roh(), "1", server_utc_offset=EET)
    assert d.time_broker == datetime(2026, 3, 2, 9, 31)
    assert d.time_broker.tzinfo is None, "Broker-Zeit ist eine Wanduhr, keine UTC"


def test_sommerzeit_verschiebt_um_eine_weitere_stunde():
    """Der Grund, warum der Versatz je Abgleich gemessen wird.

    Fest verdrahtet müsste man ihn zweimal im Jahr von Hand nachziehen --
    und die Woche dazwischen stünde falsch im Journal.
    """
    winter = m.deal_aus_mt5(roh(), "1", server_utc_offset=EET)
    sommer = m.deal_aus_mt5(roh(), "1", server_utc_offset=EEST)
    assert winter.time_utc - sommer.time_utc == timedelta(hours=1)


def test_mitternachtsgrenze_kippt_den_tag():
    """Warum zwei Stunden nicht "nur eine Kleinigkeit" sind.

    Ein Trade um 01:15 Serverzeit gehört bei UTC+2 zum Vortag. Ohne die
    Korrektur zählt ihn der Kalender zum falschen Tag -- und damit auch
    der Tagesverlust-Puffer, der über eine Regelverletzung entscheidet.
    """
    nachts = datetime(2026, 3, 3, 1, 15, tzinfo=timezone.utc).timestamp()
    d = m.deal_aus_mt5(roh(time=nachts), "1", server_utc_offset=EET)
    assert d.time_utc.date() == datetime(2026, 3, 2).date()
    assert d.time_broker.date() == datetime(2026, 3, 3).date()


# ---------------------------------------------------------------------------
# Versatz messen
# ---------------------------------------------------------------------------

def test_versatz_wird_auf_das_viertelstundenraster_gerundet():
    jetzt = datetime(2026, 3, 2, 7, 31, tzinfo=timezone.utc)
    # Tick trägt 09:31:07 Serverzeit -- sieben Sekunden alt.
    tick = datetime(2026, 3, 2, 9, 31, 7, tzinfo=timezone.utc).timestamp()
    assert m.messe_versatz(tick, jetzt) == EET


def test_versatz_erkennt_auch_halbe_stunden():
    """Nicht jeder Broker liegt auf einer vollen Stunde."""
    jetzt = datetime(2026, 3, 2, 7, 31, tzinfo=timezone.utc)
    tick = datetime(2026, 3, 2, 13, 1, tzinfo=timezone.utc).timestamp()
    assert m.messe_versatz(tick, jetzt) == 5 * 3600 + 30 * 60


def test_grob_veralteter_tick_liefert_keinen_versatz():
    """Am Wochenende steht der letzte Tick Tage zurück.

    Das Ergebnis läge dann außerhalb jeder echten Zeitzone und wird
    verworfen.
    """
    jetzt = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)  # Sonntag
    tick = datetime(2026, 3, 6, 23, 59, tzinfo=timezone.utc).timestamp()
    assert m.messe_versatz(tick, jetzt) is None


def test_leicht_veralteter_tick_ergibt_stillschweigend_den_falschen_versatz():
    """Festgehalten, weil es die Grenze des Messbaren ist -- kein Wunsch.

    Aus einem einzelnen Tick lässt sich sein eigenes Alter nicht ablesen.
    Ein 20 Minuten alter Tick ergibt bei UTC+2 einen sauber gerundeten
    Versatz von +1,75 h: plausibel, gerundet, und falsch.

    Genau deshalb gibt es `markt_lebt()`, und genau deshalb ist die
    Lebendprüfung im Sammler nicht optional. Dieser Test hält fest, was
    ohne sie passiert -- damit niemand sie später als überflüssig
    entfernt.
    """
    jetzt = datetime(2026, 3, 2, 7, 31, tzinfo=timezone.utc)
    alt = datetime(2026, 3, 2, 9, 11, tzinfo=timezone.utc).timestamp()  # 20 min alt
    assert m.messe_versatz(alt, jetzt) == 6300  # +1,75 h statt +2,00 h
    assert m.messe_versatz(alt, jetzt) != EET


def test_lebendpruefung_erkennt_offenen_markt():
    a = datetime(2026, 3, 2, 9, 31, 0, tzinfo=timezone.utc).timestamp()
    b = datetime(2026, 3, 2, 9, 31, 2, tzinfo=timezone.utc).timestamp()
    assert m.markt_lebt(a, b) is True


def test_lebendpruefung_erkennt_geschlossenen_markt():
    """Steht der Tick, kommen keine Kurse -- dann wird nicht gemessen."""
    a = datetime(2026, 3, 6, 23, 59, tzinfo=timezone.utc).timestamp()
    assert m.markt_lebt(a, a) is False


def test_negativer_versatz_westlich_von_utc():
    jetzt = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)
    tick = datetime(2026, 3, 2, 7, 0, tzinfo=timezone.utc).timestamp()
    assert m.messe_versatz(tick, jetzt) == -5 * 3600


def test_versatz_nimmt_auch_ein_datetime_entgegen():
    jetzt = datetime(2026, 3, 2, 7, 31, tzinfo=timezone.utc)
    tick = datetime(2026, 3, 2, 9, 31, tzinfo=timezone.utc)
    assert m.messe_versatz(tick, jetzt) == EET


# ---------------------------------------------------------------------------
# Felder
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "zahl, erwartet",
    [
        (0, DealType.BUY),
        (1, DealType.SELL),
        (2, DealType.BALANCE),   # Einzahlung
        (7, DealType.BALANCE),   # Kommission
        (12, DealType.BALANCE),  # Zinsen
        (99, DealType.OTHER),    # unbekannt -- kein Absturz
    ],
)
def test_deal_typen(zahl, erwartet):
    assert m.deal_aus_mt5(roh(type=zahl), "1").type is erwartet


@pytest.mark.parametrize(
    "zahl, erwartet",
    [
        (0, DealEntry.IN),
        (1, DealEntry.OUT),
        (2, DealEntry.INOUT),   # die Umkehr
        (3, DealEntry.OUT_BY),
    ],
)
def test_deal_entries(zahl, erwartet):
    assert m.deal_aus_mt5(roh(entry=zahl), "1").entry is erwartet


def test_stornierte_auftraege_fallen_heraus():
    """Nie ausgeführt -- gehören in keine Auswertung, auch nicht als Nullzeile.

    Sonst zählte die Trade-Anzahl Aufträge mit, die es nie gab, und jede
    Durchschnittsgröße wäre zu klein.
    """
    assert m.deal_aus_mt5(roh(type=13), "1") is None  # BUY_CANCELED
    assert m.deal_aus_mt5(roh(type=14), "1") is None  # SELL_CANCELED


def test_stop_bei_null_ist_kein_stop():
    """MT5 schreibt 0.0 statt None, wenn kein Stop gesetzt war.

    Das als Stop zu übernehmen ergäbe ein Risiko aus dem vollen
    Kontraktwert -- und damit ein R-Multiple nahe null bei jedem Trade.
    Genau die Sorte Zahl, die plausibel aussieht und nichts bedeutet.
    """
    assert m.deal_aus_mt5(roh(sl=0.0), "1").stop_loss is None
    assert m.deal_aus_mt5(roh(sl=None), "1").stop_loss is None
    assert m.deal_aus_mt5(roh(sl=1.0812), "1").stop_loss == D("1.0812")


def test_betraege_kommen_als_decimal_ohne_float_rest():
    """Der Umweg über `str` ist der Punkt.

    `Decimal(0.1)` ergibt 0.1000000000000000055511151231257827.
    """
    d = m.deal_aus_mt5(roh(profit=0.1, commission=-3.5, swap=-1.25), "1")
    assert d.profit == D("0.1")
    assert d.commission == D("-3.5")
    assert d.swap == D("-1.25")
    assert str(d.profit) == "0.1"


def test_fehlende_felder_werden_zu_null_nicht_zum_absturz():
    mager = {"ticket": 1, "time": STEMPEL, "type": 0, "entry": 0}
    d = m.deal_aus_mt5(mager, "1")
    assert d.volume == Decimal("0")
    assert d.profit == Decimal("0")
    assert d.symbol == ""
    assert d.position_id == 0


@pytest.mark.parametrize(
    "kaputt",
    [
        {"time": STEMPEL},                      # kein Ticket
        {"ticket": 1},                          # keine Zeit
        {"ticket": "keine-zahl", "time": 1.0},
        {"ticket": 1, "time": "gestern"},
    ],
)
def test_kaputter_datensatz_wirft(kaputt):
    with pytest.raises(m.UnbrauchbarerDeal):
        m.deal_aus_mt5(kaputt, "1")


def test_unlesbarer_betrag_wirft():
    with pytest.raises(m.UnbrauchbarerDeal):
        m.deal_aus_mt5(roh(profit="viel"), "1")


# ---------------------------------------------------------------------------
# Ganze Lieferungen
# ---------------------------------------------------------------------------

def test_lieferung_meldet_probleme_statt_sie_zu_verschlucken():
    """Ein Import, der stillschweigend Zeilen wegwirft, ist gefährlicher
    als einer, der abbricht: Die Summe stimmt dann nicht und niemand
    weiß warum."""
    deals, probleme = m.deals_aus_mt5(
        [roh(ticket=1), {"ticket": 2}, roh(ticket=3)], "1"
    )
    assert [d.ticket for d in deals] == [1, 3]
    assert len(probleme) == 1
    assert "Datensatz 1" in probleme[0]


def test_streng_laesst_den_ersten_fehler_durchschlagen():
    with pytest.raises(m.UnbrauchbarerDeal):
        m.deals_aus_mt5([roh(), {"ticket": 2}], "1", streng=True)


def test_ergebnis_traegt_den_gemessenen_versatz():
    ergebnis, probleme = m.ergebnis_aus_lieferung(
        {"deals": [roh()], "server_utc_offset": EET,
         "fetched_at": "2026-03-02T07:35:00+00:00"},
        account_id="1",
    )
    assert ergebnis.server_utc_offset == EET
    assert ergebnis.deals[0].time_utc.hour == 7
    assert ergebnis.fetched_at.hour == 7
    assert probleme == []


def test_fehlender_versatz_wird_nicht_zu_null_gemacht():
    """Null wäre die Behauptung, der Server laufe auf UTC.

    Bei Alpha Capital wäre das um zwei Stunden falsch -- und der Aufrufer
    könnte nicht mehr unterscheiden, ob "0" gemessen oder geraten war.
    """
    ergebnis, _ = m.ergebnis_aus_lieferung({"deals": [roh()]}, account_id="1")
    assert ergebnis.server_utc_offset is None


def test_leere_lieferung_ist_kein_fehler():
    """Ein Wochenende ohne Trades ist der Normalfall, nicht der Ausfall."""
    ergebnis, probleme = m.ergebnis_aus_lieferung({"deals": []}, account_id="1")
    assert ergebnis.deals == []
    assert probleme == []


def test_die_konto_id_wird_durchgereicht():
    ergebnis, _ = m.ergebnis_aus_lieferung({"deals": [roh()]}, account_id="42")
    assert ergebnis.deals[0].account_id == "42"


def test_umkehr_kommt_als_inout_durch():
    """Der Fall, an dem die Round-Trip-Bildung hängt.

    Eine Ausführung schließt die Short-Position *und* eröffnet die neue
    Long-Position. Kommt sie hier als schlichtes IN oder OUT an, hängen
    zwei Trades aneinander und beide Ergebnisse sind falsch.
    """
    ergebnis, _ = m.ergebnis_aus_lieferung(
        {"deals": [roh(entry=2, type=0, volume=2.0)]}, account_id="1"
    )
    assert ergebnis.deals[0].entry is DealEntry.INOUT

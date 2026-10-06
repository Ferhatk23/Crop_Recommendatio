"""Tests fuer den CSV-Import.

Broker-Exporte sind uneinheitlich: andere Spaltennamen, andere
Zahlenformate, andere Zeitformate, andere Trennzeichen. Der Import muss
damit umgehen -- und wo er es nicht kann, muss er es sagen statt zu raten.
"""

from __future__ import annotations

from decimal import Decimal

from tradediary.core.models import DealEntry, DealType
from tradediary.core.roundtrip import trades_from_positions
from tradediary.sources.csv_source import (
    _dezimal,
    erkenne_zuordnung,
    importiere,
)

D = lambda v: Decimal(str(v))


MT5_TYPISCH = """Time,Deal,Symbol,Type,Direction,Volume,Price,Order,Commission,Swap,Profit,Position
2026.03.02 09:31:04,180234,EURUSD,buy,in,1.00,1.08420,150011,-3.50,0.00,0.00,90001
2026.03.02 10:07:55,180235,EURUSD,sell,out,1.00,1.08630,150012,-3.50,0.00,210.00,90001
2026.03.02 13:22:01,180236,GBPUSD,sell,in,0.75,1.26500,150013,-2.60,0.00,0.00,90002
2026.03.02 15:48:19,180237,GBPUSD,buy,out,0.75,1.26720,150014,-2.60,-1.20,-165.00,90002
"""


def test_typischer_mt5_export():
    b = importiere(MT5_TYPISCH, account_id="A1")

    assert b.erfolgreich, b.probleme
    assert len(b.deals) == 4
    assert b.zeilen_uebersprungen == 0
    assert not b.probleme

    d = b.deals[0]
    assert d.ticket == 180234
    assert d.symbol == "EURUSD"
    assert d.type is DealType.BUY
    assert d.entry is DealEntry.IN
    assert d.volume == D("1.00")
    assert d.price == D("1.08420")
    assert d.commission == D("-3.50")
    assert d.position_id == 90001


def test_import_ergibt_korrekte_trades():
    """Der eigentliche Beweis: Import plus Zuordnung ergibt die Netto-Summe."""
    b = importiere(MT5_TYPISCH, account_id="A1")
    trades = trades_from_positions(b.deals)

    assert len(trades) == 2

    netto = sum(t.net_pnl for t in trades)
    # 210 - 3.50 - 3.50  minus  165 + 2.60 + 2.60 + 1.20
    assert netto == D("210.00") - D("7.00") + D("-165.00") - D("6.40")
    assert netto == D("31.60")


def test_semikolon_und_deutsches_zahlenformat():
    """Deutscher Excel-Export: Semikolon, Komma als Dezimaltrenner."""
    inhalt = (
        "Zeit;Ticket;Symbol;Typ;Volumen;Preis;Gewinn;Kommission\n"
        "02.03.2026 09:31:04;180234;EURUSD;Kauf;1,00;1,08420;0,00;-3,50\n"
        "02.03.2026 10:07:55;180235;EURUSD;Verkauf;1,00;1,08630;1.210,50;-3,50\n"
    )
    b = importiere(inhalt, account_id="A1")

    assert b.erfolgreich, b.probleme
    assert len(b.deals) == 2
    assert b.deals[0].volume == D("1.00")
    # 1.210,50 muss 1210.50 werden, nicht 121050 und nicht 1.21
    assert b.deals[1].profit == D("1210.50")


def test_dezimal_versteht_beide_schreibweisen():
    assert _dezimal("1,234.56") == D("1234.56")   # englisch
    assert _dezimal("1.234,56") == D("1234.56")   # deutsch
    assert _dezimal("1234.56") == D("1234.56")
    assert _dezimal("-3,50") == D("-3.50")
    assert _dezimal("210") == D("210")
    assert _dezimal("1 234,56") == D("1234.56")   # schmales Leerzeichen
    assert _dezimal("245,00 €") == D("245.00")
    assert _dezimal("") == D("0")
    assert _dezimal(None) == D("0")
    assert _dezimal("n/a") == D("0")


def test_fehlende_pflichtspalte_wird_gemeldet_nicht_geraten():
    inhalt = "Datum;Menge;Preis\n02.03.2026 09:00:00;1,00;1,0842\n"
    b = importiere(inhalt, account_id="A1")

    assert not b.erfolgreich
    assert not b.deals
    assert "ticket" in b.fehlende_pflichtfelder
    assert "symbol" in b.fehlende_pflichtfelder
    # Die Meldung nennt die vorhandenen Spalten, damit man zuordnen kann.
    assert "Datum" in b.probleme[0]


def test_unverstandene_zeile_wird_gezaehlt_nicht_verschluckt():
    inhalt = (
        "Time,Deal,Symbol,Type,Volume,Price,Profit\n"
        "2026.03.02 09:31:04,1,EURUSD,buy,1.00,1.08420,0.00\n"
        "2026.03.02 09:40:00,2,EURUSD,ausbuchung,1.00,1.08420,0.00\n"
        "kaputt,3,EURUSD,sell,1.00,1.08630,210.00\n"
    )
    b = importiere(inhalt, account_id="A1")

    assert len(b.deals) == 1
    assert b.zeilen_gesamt == 3
    assert b.zeilen_uebersprungen == 2
    assert len(b.probleme) == 2
    assert any("Zeit" in p for p in b.probleme)
    assert any("Typ" in p for p in b.probleme)


def test_dubletten_in_derselben_datei():
    inhalt = (
        "Time,Deal,Symbol,Type,Volume,Price,Profit\n"
        "2026.03.02 09:31:04,1,EURUSD,buy,1.00,1.08420,0.00\n"
        "2026.03.02 09:31:04,1,EURUSD,buy,1.00,1.08420,0.00\n"
    )
    b = importiere(inhalt, account_id="A1")

    assert len(b.deals) == 1
    assert b.zeilen_uebersprungen == 1


def test_balance_buchung_wird_erkannt():
    inhalt = (
        "Time,Deal,Symbol,Type,Volume,Price,Profit\n"
        "2026.03.01 00:00:00,1,,balance,0,0,10000.00\n"
        "2026.03.02 09:31:04,2,EURUSD,buy,1.00,1.08420,0.00\n"
    )
    b = importiere(inhalt, account_id="A1")

    assert len(b.deals) == 2
    assert b.deals[0].type is DealType.BALANCE
    assert b.deals[0].is_balance
    assert b.deals[0].profit == D("10000.00")


def test_zuordnung_kann_vorgegeben_werden():
    """Wenn die Erkennung nicht reicht, gibt der Nutzer die Zuordnung vor."""
    inhalt = "wann;nr;was;kaufverkauf;wieviel;wieteuer;ertrag\n" \
             "02.03.2026 09:31;7;EURUSD;buy;1,00;1,0842;0\n"
    zuordnung = {
        "time": "wann", "ticket": "nr", "symbol": "was",
        "type": "kaufverkauf", "volume": "wieviel", "price": "wieteuer",
        "profit": "ertrag",
    }
    b = importiere(inhalt, account_id="A1", zuordnung=zuordnung)

    assert b.erfolgreich, b.probleme
    assert b.deals[0].ticket == 7
    assert b.deals[0].symbol == "EURUSD"


def test_erkennung_bevorzugt_exakte_treffer():
    """'price' darf nicht an 'openprice' gehen, wenn beide existieren."""
    z = erkenne_zuordnung(["Time", "Deal", "Symbol", "Type", "Volume",
                           "OpenPrice", "Price", "Profit"])
    assert z["price"] == "Price"


def test_leere_datei():
    b = importiere("", account_id="A1")
    assert not b.erfolgreich
    assert "leer" in b.probleme[0].lower()


def test_tabulator_getrennt():
    inhalt = (
        "Time\tDeal\tSymbol\tType\tVolume\tPrice\tProfit\n"
        "2026.03.02 09:31:04\t1\tEURUSD\tbuy\t1.00\t1.08420\t0.00\n"
    )
    b = importiere(inhalt, account_id="A1")
    assert b.erfolgreich, b.probleme
    assert len(b.deals) == 1

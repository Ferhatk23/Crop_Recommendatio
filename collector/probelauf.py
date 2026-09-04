"""Der Sammler gegen ein nachgebautes MT5.

Das Paket `MetaTrader5` gibt es nur für Windows-Python. Wer den Sammler
auf einem Linux-Rechner entwickelt oder in eine Prüfung einbauen will,
kann ihn deshalb nicht laufen lassen -- und alles zwischen "Deals holen"
und "API antwortet" bliebe ungeprüft.

Dieses Skript legt ein `MetaTrader5` in den Modulcache, das sich wie das
echte verhält: Es liefert Deal-Tupel mit denselben Feldnamen, Ticks, die
vorrücken, und eine Order-Historie mit Stops. Danach läuft `sammler.py`
unverändert.

Was es prüft:
  * dass der Sammler die MT5-Felder richtig ausliest,
  * dass die Lebendprüfung greift,
  * dass Stops aus den Orders an die richtigen Deals kommen,
  * dass die Lieferung durchgeht und wiederholbar ist.

Was es **nicht** prüft: ob das echte MT5 dieselben Felder liefert. Das
geht nur an einem echten Terminal.

    python collector/probelauf.py            # Markt offen
    python collector/probelauf.py --zu       # Markt geschlossen
"""

from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timedelta, timezone

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

MARKT_OFFEN = "--zu" not in sys.argv

#: Der Broker läuft auf UTC+2 -- wie Alpha Capital im Winter.
VERSATZ = 2 * 3600


class Tupel:
    """Ein Objekt mit Attributen, wie MT5 sie liefert."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _server_stempel(utc: datetime) -> float:
    """Was MT5 als `time` liefert: die Server-Wanduhr, gelesen als UTC."""
    return (utc + timedelta(seconds=VERSATZ)).timestamp()


JETZT = datetime.now(timezone.utc)

DEALS = [
    Tupel(ticket=800001, time=_server_stempel(JETZT - timedelta(hours=5)),
          type=0, entry=0, position_id=920001, symbol="EURUSD",
          volume=1.0, price=1.08000, profit=0.0, commission=-3.5,
          swap=0.0, fee=0.0),
    Tupel(ticket=800002, time=_server_stempel(JETZT - timedelta(hours=4)),
          type=1, entry=1, position_id=920001, symbol="EURUSD",
          volume=1.0, price=1.08300, profit=300.0, commission=-3.5,
          swap=0.0, fee=0.0),
    Tupel(ticket=800003, time=_server_stempel(JETZT - timedelta(hours=3)),
          type=1, entry=0, position_id=920002, symbol="XAUUSD",
          volume=0.5, price=2420.00, profit=0.0, commission=-1.75,
          swap=0.0, fee=0.0),
    Tupel(ticket=800004, time=_server_stempel(JETZT - timedelta(hours=2)),
          type=0, entry=1, position_id=920002, symbol="XAUUSD",
          volume=0.5, price=2412.00, profit=400.0, commission=-1.75,
          swap=-2.10, fee=0.0),
    # Ein stornierter Auftrag -- darf nicht gezählt werden.
    Tupel(ticket=800005, time=_server_stempel(JETZT - timedelta(hours=1)),
          type=13, entry=0, position_id=920003, symbol="EURUSD",
          volume=1.0, price=1.09000, profit=0.0, commission=0.0,
          swap=0.0, fee=0.0),
]

ORDERS = [
    Tupel(ticket=700001, position_id=920001, sl=1.07700),
    Tupel(ticket=700002, position_id=920002, sl=2428.00),
]

_tick_zaehler = {"n": 0}


def _tick(symbol):
    if symbol not in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
        return None
    if MARKT_OFFEN:
        # Jeder Aufruf rückt vor: Der Markt lebt.
        _tick_zaehler["n"] += 1
        zeit = _server_stempel(datetime.now(timezone.utc)) + _tick_zaehler["n"]
    else:
        # Steht still und ist zwei Tage alt: Wochenende.
        zeit = _server_stempel(JETZT - timedelta(days=2))
    return Tupel(time=int(zeit), bid=1.08, ask=1.0801)


def baue_mt5():
    modul = types.ModuleType("MetaTrader5")
    modul.initialize = lambda **kw: True
    modul.shutdown = lambda: None
    modul.last_error = lambda: (1, "kein Fehler")
    modul.account_info = lambda: Tupel(
        login=12345678, server="AlphaCapital-Live02", currency="EUR", trade_mode=0
    )
    modul.symbol_info_tick = _tick
    modul.history_deals_get = lambda von, bis: DEALS
    modul.history_orders_get = lambda von, bis: ORDERS
    return modul


sys.modules["MetaTrader5"] = baue_mt5()

import sammler  # noqa: E402

# Die Lebendprüfung kostet sonst 1,5 Sekunden je Lauf.
sammler.LEBEND_PAUSE = 0.01


def main() -> None:
    mt5 = sys.modules["MetaTrader5"]
    print(f"Nachgebautes MT5, Markt {'offen' if MARKT_OFFEN else 'geschlossen'}, "
          f"Broker auf UTC{VERSATZ / 3600:+g}\n")

    sammler.verbinde(mt5)

    versatz = sammler.miss_versatz(mt5)
    erwartet = VERSATZ if MARKT_OFFEN else None
    print(f"  Versatz gemessen: {versatz}  (erwartet {erwartet})")
    assert versatz == erwartet, "Versatzmessung falsch"

    deals = sammler.hole_deals(mt5, JETZT - timedelta(days=3), JETZT)
    assert len(deals) == 5, f"5 Deals erwartet, {len(deals)} bekommen"

    getroffen = sammler.ergaenze_stops(
        mt5, deals, JETZT - timedelta(days=3), JETZT
    )
    print(f"  Stops nachgetragen: {getroffen}  (erwartet 2)")
    assert getroffen == 2, "Stops nicht an den eröffnenden Deals"
    assert deals[0]["sl"] == 1.07700
    assert deals[1]["sl"] == 0.0, "Stop am schliessenden Deal -- falsch"
    assert deals[2]["sl"] == 2428.00

    print("\n  Lieferung an die API …")
    ergebnis = sammler.abgleichen(mt5)
    print(f"  -> {ergebnis}")

    print("\n  Noch einmal -- muss wiederholbar sein …")
    zweite = sammler.abgleichen(mt5)
    assert zweite["deals_new"] == 0, (
        f"Wiederholung hat {zweite['deals_new']} Deals doppelt angelegt"
    )

    print("\nAlles in Ordnung.")


if __name__ == "__main__":
    main()

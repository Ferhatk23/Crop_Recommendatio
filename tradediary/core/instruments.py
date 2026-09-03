"""Was ein Preisunterschied in Geld bedeutet.

Der Kern rechnet bewusst nicht mit Kontraktgrößen -- das Ergebnis eines
Trades kommt fertig vom Broker, und das ist die verlässlichste Quelle.
Für genau eine Größe reicht das aber nicht: das **R-Multiple**. Es braucht
den riskierten Betrag, und der ergibt sich aus dem Stop-Abstand mal
Kontraktwert -- ein Weg, den kein Broker mitliefert, weil der Trade ja nie
am Stop gelandet ist.

Deshalb steht hier eine Tabelle. Sie ist ein *Standardwert*, kein Gesetz:
Broker führen Symbole unterschiedlich (`EURUSD`, `EURUSD.r`, `EURUSDm`),
und Kontraktgrößen weichen ab. Im Betrieb kommen die echten Angaben aus
`symbol_info()` von MT5 und überschreiben diese Tabelle.

Ist ein Symbol unbekannt, wird **kein** Wert geraten. Dann gibt es für
diesen Trade kein R -- und die Oberfläche sagt das, statt eine Zahl zu
zeigen, die niemand nachrechnen kann.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

D = lambda v: Decimal(str(v))


@dataclass(frozen=True)
class Instrument:
    """Wie viel ein Lot bei einer Preisbewegung von 1.0 wert ist."""

    symbol: str
    #: Geld je Preiseinheit und Lot. Bei EURUSD: 1 Lot = 100.000 Einheiten,
    #: eine Bewegung von 1.00000 ist also 100.000 wert.
    value_per_unit: Decimal
    digits: int = 5


#: Standardwerte für gängige Symbole. Bewusst klein gehalten -- was fehlt,
#: kommt aus MT5, nicht aus einer immer längeren Rateliste.
STANDARD: dict[str, Instrument] = {
    "EURUSD": Instrument("EURUSD", D(100_000), 5),
    "GBPUSD": Instrument("GBPUSD", D(100_000), 5),
    "AUDUSD": Instrument("AUDUSD", D(100_000), 5),
    "NZDUSD": Instrument("NZDUSD", D(100_000), 5),
    "USDCHF": Instrument("USDCHF", D(100_000), 5),
    "USDCAD": Instrument("USDCAD", D(100_000), 5),
    "USDJPY": Instrument("USDJPY", D(670), 3),
    "EURJPY": Instrument("EURJPY", D(670), 3),
    "GBPJPY": Instrument("GBPJPY", D(670), 3),
    "XAUUSD": Instrument("XAUUSD", D(100), 2),
    "XAGUSD": Instrument("XAGUSD", D(5_000), 3),
    "US30":   Instrument("US30", D(1), 1),
    "NAS100": Instrument("NAS100", D(1), 1),
    "GER40":  Instrument("GER40", D(1), 1),
    "SPX500": Instrument("SPX500", D(1), 1),
}


def normalisiere(symbol: str) -> str:
    """Entfernt broker-eigene Anhängsel: ``EURUSD.r`` wird ``EURUSD``.

    Prop-Firmen und Broker hängen gern Suffixe an -- ohne diese
    Vereinheitlichung stünde dasselbe Instrument mehrfach im Report und
    hätte je Schreibweise seine eigene Statistik.
    """
    name = symbol.strip().upper()
    for trenner in (".", "_", "-", "#"):
        if trenner in name:
            name = name.split(trenner)[0]
    # Angehängte Kleinbuchstaben-Kürzel wie EURUSDm, EURUSDmicro
    while name and not name[-1].isdigit() and name not in STANDARD:
        if len(name) <= 6:
            break
        name = name[:-1]
    return name


def finde(symbol: str, eigene: dict[str, Instrument] | None = None) -> Instrument | None:
    """Sucht die Angaben zu einem Symbol. `None`, wenn unbekannt."""
    name = normalisiere(symbol)
    if eigene and name in eigene:
        return eigene[name]
    if eigene and symbol in eigene:
        return eigene[symbol]
    return STANDARD.get(name)


def nachkommastellen(
    symbol: str,
    eigene: dict[str, Instrument] | None = None,
) -> int:
    """Wie viele Nachkommastellen ein Preis dieses Instruments trägt.

    Anders als bei :func:`risiko` gibt es hier keine ehrliche Antwort
    "unbekannt": Ein Preis muss irgendwie gesetzt werden. Fünf Stellen
    sind die sichere Vorgabe -- sie zeigen bei einem unbekannten Symbol
    zwar zu viel, aber sie verschweigen nichts. Andersherum wäre es
    schlimmer: Zwei Stellen auf einem Devisenpaar machten aus 1,08420
    ein "1,08" und damit aus zwei verschiedenen Kursen denselben.

    Bekannt ist die Stellenzahl trotzdem meistens, und dann zählt sie:
    "39.498,47676" für einen Index ist keine Notierung, die jemand
    wiedererkennt.
    """
    gefunden = finde(symbol, eigene)
    return gefunden.digits if gefunden else 5


def risiko(
    symbol: str,
    avg_entry: Decimal | None,
    initial_sl: Decimal | None,
    volume: Decimal,
    eigene: dict[str, Instrument] | None = None,
) -> Decimal | None:
    """Der beim Einstieg riskierte Betrag.

    ``None``, sobald eine Angabe fehlt -- ohne Stop, ohne Einstiegspreis
    oder bei unbekanntem Symbol gibt es kein Risiko, das man beziffern
    könnte. Eine Null wäre hier die gefährlichste aller Antworten: Sie
    würde durch die R-Berechnung als Division durch null laufen oder,
    schlimmer, als "risikofrei" gelesen.
    """
    if avg_entry is None or initial_sl is None or volume <= 0:
        return None
    instrument = finde(symbol, eigene)
    if instrument is None:
        return None
    abstand = abs(avg_entry - initial_sl)
    if abstand == 0:
        return None
    return (abstand * instrument.value_per_unit * volume).quantize(Decimal("0.01"))

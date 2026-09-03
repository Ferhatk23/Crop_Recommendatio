"""CSV-Import mit einstellbarer Spaltenzuordnung.

Der universelle Weg: Er funktioniert mit jedem Broker und jeder Plattform,
die exportieren kann -- und ist zugleich die einmalige Rückwärts-Befüllung
der Alt-Historie, die jeder automatische Abgleich braucht, weil der immer
erst am Einrichtungstag beginnt.

Der Importer rät nicht. Er bekommt eine Zuordnung von Dateispalten auf
Felder, oder er versucht sie über bekannte Namen zu erkennen und sagt
danach, was er gefunden hat. Was er nicht sicher zuordnen kann, meldet er
als Problem, statt eine Spalte zu erfinden.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from ..core.models import ZERO, Deal, DealEntry, DealType

#: Feldname -> Spaltenüberschriften, unter denen er üblicherweise auftaucht.
#: Alles klein geschrieben und ohne Sonderzeichen verglichen.
ERKENNUNG: dict[str, tuple[str, ...]] = {
    "ticket": ("ticket", "deal", "dealid", "id", "order", "position"),
    "position_id": ("positionid", "position", "positionsid", "posid"),
    "symbol": ("symbol", "instrument", "pair", "markt", "market"),
    "type": ("type", "typ", "side", "seite", "richtung", "action", "direction"),
    "entry": ("entry", "einstieg", "direction", "dealentry"),
    "volume": ("volume", "volumen", "lots", "lot", "size", "menge", "quantity"),
    "price": ("price", "preis", "kurs", "openprice", "entryprice"),
    "time": ("time", "zeit", "datetime", "date", "datum", "closetime", "opentime"),
    "profit": ("profit", "gewinn", "pnl", "pl", "netprofit", "ergebnis"),
    "commission": ("commission", "kommission", "provision", "fee", "gebuehr"),
    "swap": ("swap", "rollover", "interest", "zinsen", "finanzierung"),
    "fee": ("fee", "gebuehr", "charges", "kosten"),
    "stop_loss": ("sl", "stoploss", "stop", "stopp"),
}

#: Werte, die in der Typ-Spalte einen Kauf bzw. Verkauf bedeuten.
KAUF = {"buy", "b", "long", "kauf", "0", "buy_limit", "buylimit"}
VERKAUF = {"sell", "s", "short", "verkauf", "1", "sell_limit", "selllimit"}
BALANCE = {"balance", "credit", "deposit", "withdrawal", "einzahlung", "auszahlung", "2"}

#: Werte, die in der Entry-Spalte Öffnen bzw. Schließen bedeuten.
ENTRY_IN = {"in", "0", "einstieg", "open", "entry_in"}
ENTRY_OUT = {"out", "1", "ausstieg", "close", "entry_out"}
ENTRY_INOUT = {"inout", "in/out", "2", "reverse", "umkehr", "entry_inout"}
ENTRY_OUTBY = {"outby", "out by", "3", "entry_out_by"}

ZEITFORMATE = (
    "%Y-%m-%d %H:%M:%S",
    "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y.%m.%d %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%d.%m.%Y",
)


def _normalisiere(text: str) -> str:
    """Spaltenüberschrift auf Kleinbuchstaben ohne Sonderzeichen reduzieren."""
    return "".join(c for c in text.lower() if c.isalnum())


@dataclass
class ImportBericht:
    """Was der Import gefunden, übersprungen und nicht verstanden hat.

    Ein Import, der stillschweigend Zeilen wegwirft, ist gefährlicher als
    einer, der abbricht -- die Summe stimmt dann nicht mehr und niemand
    weiß warum. Deshalb wird jede übersprungene Zeile gezählt und begründet.
    """

    deals: list[Deal] = field(default_factory=list)
    zuordnung: dict[str, str] = field(default_factory=dict)
    zeilen_gesamt: int = 0
    zeilen_uebersprungen: int = 0
    probleme: list[str] = field(default_factory=list)

    @property
    def erfolgreich(self) -> bool:
        return bool(self.deals) and not self.fehlende_pflichtfelder

    @property
    def fehlende_pflichtfelder(self) -> list[str]:
        pflicht = ("ticket", "symbol", "type", "volume", "price", "time")
        return [f for f in pflicht if f not in self.zuordnung]

    def zusammenfassung(self) -> str:
        teile = [
            f"{len(self.deals)} Ausführungen aus {self.zeilen_gesamt} Zeilen",
        ]
        if self.zeilen_uebersprungen:
            teile.append(f"{self.zeilen_uebersprungen} übersprungen")
        if self.probleme:
            teile.append(f"{len(self.probleme)} Probleme")
        return ", ".join(teile)


def erkenne_zuordnung(kopfzeile: list[str]) -> dict[str, str]:
    """Ordnet Dateispalten den Feldern zu, so weit es eindeutig geht.

    Bewusst konservativ: Eine Spalte wird nur zugeordnet, wenn ihr
    normalisierter Name in der Liste bekannter Bezeichnungen steht. Was
    übrig bleibt, muss der Nutzer zuordnen -- das ist die Aufgabe der
    Zuordnungs-Oberfläche.
    """
    zuordnung: dict[str, str] = {}
    belegt: set[str] = set()

    # Erst die exakten Treffer, damit "price" nicht an "openprice" geht,
    # wenn beide Spalten existieren.
    for feld, kandidaten in ERKENNUNG.items():
        for spalte in kopfzeile:
            if spalte in belegt:
                continue
            if _normalisiere(spalte) == kandidaten[0]:
                zuordnung[feld] = spalte
                belegt.add(spalte)
                break

    for feld, kandidaten in ERKENNUNG.items():
        if feld in zuordnung:
            continue
        for spalte in kopfzeile:
            if spalte in belegt:
                continue
            if _normalisiere(spalte) in kandidaten:
                zuordnung[feld] = spalte
                belegt.add(spalte)
                break

    return zuordnung


def _dezimal(rohwert: str | None) -> Decimal:
    """Wandelt einen Zahlenwert um und verkraftet beide Trennzeichen.

    Broker-Exporte kommen mal als ``1,234.56`` und mal als ``1.234,56``.
    Beides muss dieselbe Zahl ergeben, sonst ist der Import um Faktor 1000
    daneben -- und das fällt bei kleinen Beträgen nicht sofort auf.
    """
    if rohwert is None:
        return ZERO
    text = str(rohwert).strip()
    if not text or text in ("-", "--", "n/a", "N/A"):
        return ZERO

    text = text.replace(" ", "").replace(" ", "")
    for waehrung in ("€", "$", "£", "¥", "EUR", "USD", "GBP"):
        text = text.replace(waehrung, "")

    hat_komma, hat_punkt = "," in text, "." in text
    if hat_komma and hat_punkt:
        # Das weiter hinten stehende Zeichen ist das Dezimaltrennzeichen.
        if text.rindex(",") > text.rindex("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif hat_komma:
        # Ein Komma mit genau zwei Nachkommastellen ist ein Dezimalkomma,
        # sonst ein Tausendertrenner.
        text = (
            text.replace(",", ".")
            if len(text.split(",")[-1]) in (1, 2)
            else text.replace(",", "")
        )

    try:
        return Decimal(text)
    except InvalidOperation:
        return ZERO


def _zeit(rohwert: str) -> datetime | None:
    text = str(rohwert).strip()
    if not text:
        return None
    for fmt in ZEITFORMATE:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _typ(rohwert: str) -> DealType:
    wert = _normalisiere(str(rohwert))
    if wert in KAUF:
        return DealType.BUY
    if wert in VERKAUF:
        return DealType.SELL
    if wert in BALANCE:
        return DealType.BALANCE
    return DealType.OTHER


def _entry(rohwert: str | None, fallback: DealEntry = DealEntry.IN) -> DealEntry:
    if rohwert is None:
        return fallback
    wert = _normalisiere(str(rohwert))
    if wert in ENTRY_IN:
        return DealEntry.IN
    if wert in ENTRY_OUT:
        return DealEntry.OUT
    if wert in ENTRY_INOUT:
        return DealEntry.INOUT
    if wert in ENTRY_OUTBY:
        return DealEntry.OUT_BY
    return fallback


def importiere(
    inhalt: str,
    account_id: str,
    zuordnung: dict[str, str] | None = None,
    trennzeichen: str | None = None,
) -> ImportBericht:
    """Liest einen CSV-Export und gibt Ausführungen zurück.

    ``zuordnung`` bildet Feldnamen auf Spaltenüberschriften ab. Fehlt sie,
    wird sie über bekannte Namen erkannt und im Bericht mitgeliefert, damit
    die Oberfläche sie zur Bestätigung anzeigen kann.
    """
    bericht = ImportBericht()

    if not inhalt.strip():
        bericht.probleme.append("Datei ist leer.")
        return bericht

    if trennzeichen is None:
        probe = inhalt[:4096]
        try:
            trennzeichen = csv.Sniffer().sniff(probe, delimiters=",;\t|").delimiter
        except csv.Error:
            # Häufigstes Zeichen in der Kopfzeile gewinnt.
            kopf = probe.splitlines()[0] if probe.splitlines() else ""
            trennzeichen = max(",;\t|", key=kopf.count)

    leser = csv.DictReader(io.StringIO(inhalt), delimiter=trennzeichen)
    if not leser.fieldnames:
        bericht.probleme.append("Keine Kopfzeile gefunden.")
        return bericht

    spalten = [f for f in leser.fieldnames if f]
    bericht.zuordnung = zuordnung or erkenne_zuordnung(spalten)

    fehlend = bericht.fehlende_pflichtfelder
    if fehlend:
        bericht.probleme.append(
            "Diese Pflichtfelder konnten keiner Spalte zugeordnet werden: "
            + ", ".join(fehlend)
            + ". Vorhandene Spalten: "
            + ", ".join(spalten)
        )
        return bericht

    z = bericht.zuordnung
    gesehen: set[int] = set()

    for nummer, zeile in enumerate(leser, start=2):
        bericht.zeilen_gesamt += 1

        def wert(feld: str) -> str | None:
            spalte = z.get(feld)
            return zeile.get(spalte) if spalte else None

        zeitpunkt = _zeit(wert("time") or "")
        if zeitpunkt is None:
            bericht.zeilen_uebersprungen += 1
            bericht.probleme.append(f"Zeile {nummer}: Zeit nicht lesbar.")
            continue

        try:
            ticket = int(_dezimal(wert("ticket")))
        except (TypeError, ValueError):
            bericht.zeilen_uebersprungen += 1
            bericht.probleme.append(f"Zeile {nummer}: Ticket nicht lesbar.")
            continue

        if ticket in gesehen:
            # Dubletten in derselben Datei still überspringen -- der
            # Primärschlüssel würde sie ohnehin abweisen.
            bericht.zeilen_uebersprungen += 1
            continue
        gesehen.add(ticket)

        typ = _typ(wert("type") or "")
        if typ is DealType.OTHER:
            bericht.zeilen_uebersprungen += 1
            bericht.probleme.append(
                f"Zeile {nummer}: Typ '{wert('type')}' nicht verstanden."
            )
            continue

        position_id = ticket
        if "position_id" in z:
            roh = _dezimal(wert("position_id"))
            if roh != ZERO:
                position_id = int(roh)

        stop = _dezimal(wert("stop_loss")) if "stop_loss" in z else ZERO

        bericht.deals.append(
            Deal(
                ticket=ticket,
                account_id=account_id,
                position_id=position_id,
                symbol=(wert("symbol") or "").strip(),
                type=typ,
                entry=_entry(wert("entry")),
                volume=_dezimal(wert("volume")),
                price=_dezimal(wert("price")),
                time_utc=zeitpunkt,
                profit=_dezimal(wert("profit")),
                commission=_dezimal(wert("commission")),
                swap=_dezimal(wert("swap")),
                fee=_dezimal(wert("fee")),
                stop_loss=stop if stop != ZERO else None,
            )
        )

    return bericht


class CsvSource:
    """Deal-Quelle aus einer Datei -- erfüllt das Protokoll aus sync.source."""

    name = "csv"

    def __init__(self, inhalt: str, account_id: str, zuordnung=None):
        self._bericht = importiere(inhalt, account_id, zuordnung)

    @property
    def bericht(self) -> ImportBericht:
        return self._bericht

    def fetch(self, since: datetime, until: datetime):
        from ..core.models import SyncResult

        passend = [
            d for d in self._bericht.deals if since <= d.time_utc <= until
        ]
        return SyncResult(deals=passend, fetched_at=datetime.now(timezone.utc))

    def healthy(self) -> bool:
        return self._bericht.erfolgreich

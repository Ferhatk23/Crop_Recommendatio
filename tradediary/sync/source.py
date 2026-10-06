"""Die Schnittstelle, an der die Herkunft der Daten austauschbar wird.

Das ist die wichtigste kleine Datei im Projekt. Sie legt fest, was eine
Deal-Quelle können muss -- und weil alles dahinter nur noch `Deal`-Objekte
sieht, ist die Entscheidung, *woher* die Trades kommen, jederzeit umkehrbar.

Geplante Umsetzungen:

* ``MT5CollectorSource``  -- ein dünner Sammler unter Wine auf dem
  Dauerrechner, der die MT5-Historie ausliest und hierher schickt.
* ``CsvSource``          -- Datei-Import mit einstellbarer Spaltenzuordnung.
  Der universelle Weg: Er funktioniert mit jedem Broker und jeder Plattform,
  die exportieren kann, und ist zugleich die einmalige Rückwärts-Befüllung
  der Alt-Historie, die jeder automatische Weg braucht.
* ``MetaApiSource``      -- über einen Cloud-Dienst, falls die
  Geräteabhängigkeit später stören sollte.
* ``CTraderSource``      -- über die kostenlose cTrader Open API.

Keine dieser Umsetzungen darf rechnen. Sie holen Deals und normalisieren
Zeiten, mehr nicht. Alles Weitere gehört in ``core`` -- schon deshalb, weil
der Sammler unter Wine läuft und damit auf dem brüchigsten Stück der Kette
sitzt. Was dort nicht steht, kann dort nicht kaputtgehen.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from ..core.models import SyncResult


@runtime_checkable
class DealSource(Protocol):
    """Was jede Quelle können muss."""

    #: Kurzname für Protokoll und Oberfläche, etwa ``"mt5-collector"``.
    name: str

    def fetch(self, since: datetime, until: datetime) -> SyncResult:
        """Liefert alle Ausführungen im Zeitraum.

        Zwei Zusicherungen, auf denen die Ausfallsicherheit der ganzen Kette
        beruht:

        * **Vollständig.** Der Aufruf liefert *alles* im Zeitraum, nicht nur
          das Neue. Damit ist jeder Abgleich ein Abzug und kein
          Ereignisstrom -- war die Quelle stundenlang still, holt der nächste
          Lauf alles nach.
        * **Wiederholbar.** Derselbe Zeitraum darf beliebig oft abgefragt
          werden. Möglich wird das durch das MT5-Ticket als Primärschlüssel:
          Bekannte Deals fallen beim Speichern still durch.

        Zeiten kommen und gehen in UTC.
        """
        ...

    def healthy(self) -> bool:
        """Ist die Quelle gerade erreichbar?

        Für die Statusanzeige. Bei einem Sammler, der unter Wine läuft, ist
        das kein Luxus: Ein stiller Ausfall führt sonst zu einem Journal, das
        weiterhin Zahlen zeigt -- nur eben veraltete.
        """
        ...


#: Wie weit jeder Abgleich über den letzten bekannten Stand zurückgreift.
#: Die Überlappung kostet nichts, weil Dubletten ohnehin abgewiesen werden,
#: und fängt nachträglich gebuchte Swaps und verspätete Korrekturen ein.
DEFAULT_OVERLAP = timedelta(days=3)


def window(
    last_synced: datetime | None,
    now: datetime | None = None,
    overlap: timedelta = DEFAULT_OVERLAP,
    initial_lookback: timedelta = timedelta(days=365),
) -> tuple[datetime, datetime]:
    """Berechnet den abzufragenden Zeitraum für den nächsten Lauf."""
    now = now or datetime.now(timezone.utc)
    if last_synced is None:
        return now - initial_lookback, now
    return last_synced - overlap, now

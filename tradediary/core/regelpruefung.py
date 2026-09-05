"""Regeln, die sich aus den Daten beantworten lassen.

Eine Regeltreue-Quote aus lauter selbstgesetzten Häkchen misst die eigene
Selbsteinschätzung. Das ist nicht wertlos -- aber man benotet sich selbst,
und zwar rückblickend, wenn das Ergebnis schon bekannt ist. Nach einem
Gewinn erinnert man sich anders an den Einstieg als nach einem Verlust.

Ein Teil der üblichen Regeln braucht diese Erinnerung nicht. Ob ein Stop
gesetzt war, steht im Deal. Wie lange gehalten wurde, auch. Wo das geht,
wird gemessen statt gefragt.

Drei Festlegungen tragen die ganze Datei:

* **Drei Antworten, nicht zwei.** ``True``, ``False`` -- und ``None`` für
  "lässt sich hier nicht sagen". Fehlt eine Angabe, ist das kein
  Regelbruch. Ein `False` aus Unwissen wäre die schlimmste Ausgabe: Es
  sähe aus wie ein Befund und wäre eine Vermutung.
* **Bruchstücke werden nur bewertet, wo es zwingend ist.** Lag die
  Eröffnung vor dem abgefragten Zeitraum, fehlen Einstiegspreis und Stop
  -- nicht weil keiner da war, sondern weil wir ihn nicht gesehen haben.
  Wo die Angabe ganz fehlt, ist die Antwort ``None``.

  Wo sie nur *zu klein* ist, gilt eine Halbregel: Ein Bruchstück zeigt
  eine kürzere Haltedauer, ein kleineres Volumen und weniger Einstiege,
  als es wirklich gab. Reisst schon dieser Ausschnitt die Grenze, ist die
  Regel zwingend gebrochen -- das ist ein Befund. Liegt der Ausschnitt
  darunter, folgt daraus nichts: Der unsichtbare Rest kann die Grenze
  längst gerissen haben. Ein ``True`` wäre hier ein Freispruch aus
  Nichtwissen, und der ist schlimmer als eine offene Frage.
* **Der Kern kennt keine Datenbank.** Alles hier sind reine Funktionen
  über die Dataclasses. Was aus der Datenbank kommt -- Startkapital, Zahl
  der Einstiege --, wird als Argument hereingereicht.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .models import Trade


@dataclass(frozen=True)
class Pruefung:
    """Eine messbare Regel.

    `einheit` ist ``None``, wenn die Prüfung ohne Zahl auskommt. Sonst
    steht dort, was der Wert bedeutet -- die Oberfläche schreibt es an das
    Eingabefeld, damit niemand Minuten in ein Prozentfeld tippt.
    """

    key: str
    label: str
    einheit: str | None
    beschreibung: str
    beispiel: str | None = None


PRUEFUNGEN: tuple[Pruefung, ...] = (
    Pruefung(
        key="stop_gesetzt",
        label="Stop war gesetzt",
        einheit=None,
        beschreibung=(
            "Erfüllt, wenn beim Einstieg ein Stop-Loss im Markt lag. "
            "Ohne Stop gibt es kein R-Multiple -- die Regel deckt sich "
            "also mit dem, was auch die Auswertung braucht."
        ),
    ),
    Pruefung(
        key="risiko_hoechstens",
        label="Risiko höchstens",
        einheit="% vom Startkapital",
        beschreibung=(
            "Vergleicht den beim Einstieg riskierten Betrag mit dem "
            "Startkapital des Kontos. Ohne Stop oder bei unbekanntem "
            "Symbol lässt sich das Risiko nicht beziffern -- dann bleibt "
            "die Regel offen statt auf „gebrochen“ zu fallen."
        ),
        beispiel="1",
    ),
    Pruefung(
        key="haltedauer_hoechstens",
        label="Haltedauer höchstens",
        einheit="Minuten",
        beschreibung=(
            "Vom ersten Einstieg bis zum letzten Ausstieg. Ein noch "
            "offener Trade hat keine Haltedauer und bleibt offen."
        ),
        beispiel="240",
    ),
    Pruefung(
        key="volumen_hoechstens",
        label="Volumen höchstens",
        einheit="Lot",
        beschreibung=(
            "Das eingegangene Gesamtvolumen der Position, nicht die "
            "einzelne Teilausführung."
        ),
        beispiel="1.0",
    ),
    Pruefung(
        key="nur_ein_einstieg",
        label="Nicht nachgekauft",
        einheit=None,
        beschreibung=(
            "Erfüllt, wenn die Position mit genau einer Ausführung "
            "eröffnet wurde. Gestaffelte Einstiege sind ein Verfahren wie "
            "jedes andere -- diese Regel ist für den, der sich vorgenommen "
            "hat, in eine laufende Position nicht nachzulegen."
        ),
    ),
)

NACH_KEY = {p.key: p for p in PRUEFUNGEN}


def parameter_lesen(roh: str | None) -> Decimal | None:
    """Den gespeicherten Parameter als Zahl. `None`, wenn nichts brauchbar ist."""
    if roh is None:
        return None
    text = str(roh).strip().replace(",", ".")
    if not text:
        return None
    try:
        wert = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return wert if wert > 0 else None


def _untergrenze(gemessen, grenze, unvollstaendig: bool) -> bool | None:
    """Antwort auf „höchstens", wenn die Messung zu klein ausfallen kann.

    Bei einem Bruchstück sehen wir nur einen Ausschnitt: kürzere Dauer,
    kleineres Volumen, weniger Einstiege. Reisst schon der Ausschnitt die
    Grenze, steht der Bruch fest. Liegt er darunter, ist nichts bewiesen
    -- der ungesehene Teil kann die Grenze längst gerissen haben.
    """
    gehalten = gemessen <= grenze
    if unvollstaendig and gehalten:
        return None
    return gehalten


def pruefe(
    key: str,
    parameter: str | None,
    trade: Trade,
    *,
    startkapital: Decimal | None = None,
    einstiege: int | None = None,
) -> bool | None:
    """Beantwortet eine messbare Regel für einen Trade.

    ``None`` heisst durchgehend "hier nicht zu beantworten" und wird
    stromabwärts wie eine nicht gesetzte Antwort behandelt -- nie wie ein
    Regelbruch.
    """
    pruefung = NACH_KEY.get(key)
    if pruefung is None:
        return None

    wert = parameter_lesen(parameter)
    if pruefung.einheit is not None and wert is None:
        # Eine Zahlenregel ohne Zahl ist keine Regel. Sie stumm auf
        # "eingehalten" zu setzen, hiesse jeden Trade zu belohnen, weil
        # ein Feld leer geblieben ist.
        return None

    if key == "stop_gesetzt":
        # Beim Bruchstück fehlt der Stop, weil wir die Eröffnung nicht
        # gesehen haben -- nicht, weil keiner da war.
        if trade.partial:
            return None
        return trade.initial_sl is not None

    if key == "risiko_hoechstens":
        if trade.partial or trade.risk_amount is None or startkapital is None:
            return None
        if startkapital <= 0:
            return None
        return trade.risk_amount <= startkapital * wert / Decimal(100)

    if key == "haltedauer_hoechstens":
        if trade.duration is None:
            return None
        minuten = Decimal(int(trade.duration.total_seconds())) / Decimal(60)
        return _untergrenze(minuten, wert, trade.partial)

    if key == "volumen_hoechstens":
        return _untergrenze(trade.volume, wert, trade.partial)

    if key == "nur_ein_einstieg":
        if einstiege is None:
            return None
        # Dieselbe Halbregel: Zwei gesehene Einstiege sind zwei Einstiege.
        # Ein gesehener beweist bei einem Bruchstück nicht, dass es nur
        # einen gab -- die früheren liegen vor dem Fenster.
        return _untergrenze(einstiege, 1, trade.partial)

    return None

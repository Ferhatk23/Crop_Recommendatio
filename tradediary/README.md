# TradeDiary

Ein Trading-Journal nach dem Vorbild von TradeZella: Trades laufen automatisch
aus MT5 ein, die Auswertung liegt als Web-App auf Mac, iPad und iPhone.

**Stand: Phase 1.** Der rechnende Kern steht und ist getestet. Datenbank, API
und Oberfläche folgen.

## Warum der Aufbau so aussieht

Der ganze Entwurf hängt an einer Regel: **`core/` weiß nichts über Herkunft,
Speicher oder Anzeige.** Reine Funktionen über Dataclasses, keine Datenbank,
kein Netz, keine Uhr.

Das ist keine Ästhetik, sondern hat sich in der Planung schon dreimal
ausgezahlt. Im Verlauf des Entwurfs fielen Streamlit, SQLite und der
MQL5-Export-EA wieder heraus — und keine dieser Änderungen hat den Kern
berührt. Die Anbindung an MT5 steht bis heute nicht endgültig fest; auch das
kostet nur eine neue Umsetzung von `sync/source.py`.

## Aufbau

```
tradediary/
├── core/            # reine Logik — hier hängt alles dran
│   ├── models.py    # Deal, Trade, Direction, Outcome
│   ├── roundtrip.py # Ausführungen → Trades
│   ├── metrics.py   # Trades → Kennzahlen
│   └── score.py     # Teilwerte → Gesamtwert 0–100
└── sync/
    └── source.py    # die Schnittstelle, an der die Quelle austauschbar wird
```

## Die zwei Wege von Deals zu Trades

Ein Broker liefert **Deals** (einzelne Ausführungen), auswerten will man
**Trades** (vollständige Round-Trips). Dafür gibt es zwei Funktionen, und
beide sind Absicht:

| Funktion | Wann | Genauigkeit |
|---|---|---|
| `trades_from_positions` | MT5 — der Broker liefert die `position_id` mit | exakt |
| `trades_from_executions` | alles andere, plus Gegenprobe | Kosten anteilig geschätzt |

`reconcile()` lässt beide gegeneinander laufen. Weichen sie ab, ist einer von
beiden falsch — und das will man wissen, bevor man auf die Kennzahlen schaut.

Der schwierige Fall ist die **Umkehr**: Eine einzelne Ausführung kann eine
Short-Position schließen *und* eine Long-Position eröffnen (in MT5
`DEAL_ENTRY_INOUT`). Sie muss aufgeteilt werden, sonst hängen zwei Trades
aneinander und beide Ergebnisse sind falsch.

## Die Festlegungen bei den Kennzahlen

Die Formeln sind trivial, die Definitionen nicht. Was hier entschieden wurde:

- **Ein Trade mit genau null** ist weder Gewinn noch Verlust. Er zählt als
  *Scratch* und fällt aus Zähler **und** Nenner der Trefferquote — sonst
  drückt jeder Break-even-Trade die Quote, obwohl er nichts gekostet hat.
- **Profit Factor ohne Verluste** ist `None`, nicht unendlich und nicht null.
- **R-Multiple ohne erfassten Stop** ist `None`, niemals 0. `trades_without_stop`
  sagt der Oberfläche, worauf die R-Kennzahlen überhaupt beruhen.
- **Max Drawdown** wird über die Trade-Reihenfolge gerechnet, nicht über
  Tagessalden. Beide Varianten sind üblich und liefern verschiedene Werte —
  die gewählte gehört in die Oberfläche geschrieben.
- **Offene Trades** bleiben außen vor. Ein schwebender Buchgewinn ist noch
  kein Ergebnis.

Wo ein Wert nicht bestimmbar ist, steht `None` und die Oberfläche zeigt einen
Strich. Eine Zahl, die aussieht wie eine Zahl, aber keine Aussage trägt, ist
schlimmer als eine Lücke.

Geldbeträge sind durchgehend `Decimal`. Bei `float` summieren sich
Rundungsfehler über tausende Trades zu Abweichungen, die man dann in der
Kennzahlen-Logik sucht statt im Datentyp.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Ein Test je Randfall — Umkehr, Teilausführungen, gleiche Zeitstempel,
Balance-Buchungen, mehrere Konten, jede Kennzahlen-Falle einzeln.

## Als Nächstes

1. **Postgres-Schema** — inklusive der Prop-Erweiterung: mehrere Konten über
   die Zeit, ihre Phase und ihr Status, dazu die Regel-Grenzwerte für Daily
   und Max Drawdown.
2. **CSV-Import** mit einstellbarer Spaltenzuordnung. Der universelle Weg —
   er funktioniert mit jedem Broker und ist zugleich die einmalige
   Rückwärts-Befüllung, die jeder automatische Abgleich braucht.
3. **MT5-Sammler** — ein dünner Sammler unter Wine auf dem Ubuntu-Dauerrechner.
   Bewusst ohne Logik: Er liest die Historie und schickt JSON. Was dort nicht
   steht, kann dort nicht kaputtgehen.
4. **FastAPI und Next.js** nach dem Design-Durchgang.

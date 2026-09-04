# TradeDiary

Ein Trading-Journal nach dem Vorbild von TradeZella: Trades laufen automatisch
aus MT5 ein, die Auswertung liegt als Web-App auf Mac, iPad und iPhone.

**Stand.** Kern, Datenbank, API und Oberfläche stehen und laufen gegen einen
Beispiel-Datenbestand. Was noch fehlt, steht unten unter
[Was noch nicht da ist](#was-noch-nicht-da-ist) — vollständig und ohne
Beschönigung.

## Warum der Aufbau so aussieht

Der ganze Entwurf hängt an einer Regel: **`core/` weiß nichts über Herkunft,
Speicher oder Anzeige.** Reine Funktionen über Dataclasses, keine Datenbank,
kein Netz, keine Uhr.

Das ist keine Ästhetik. Im Verlauf des Entwurfs fielen Streamlit, SQLite als
Endziel und der MQL5-Export-EA wieder heraus — und keine dieser Änderungen hat
den Kern berührt. Die Anbindung an MT5 steht bis heute nicht endgültig fest;
auch das kostet nur eine neue Umsetzung von `sync/source.py`.

## Aufbau

```
tradediary/
├── core/              # reine Logik — hier hängt alles dran
│   ├── models.py      # Deal, Trade, Direction, Outcome
│   ├── roundtrip.py   # Ausführungen → Trades
│   ├── metrics.py     # Trades → Kennzahlen
│   ├── score.py       # Teilwerte → Gesamtwert 0–100
│   ├── rules.py       # Prop-Grenzen: Tagesverlust, Max-DD, Konsistenz
│   └── instruments.py # Preisstellen und riskierter Betrag je Symbol
├── sources/
│   └── csv_source.py  # Broker-CSV mit einstellbarer Spaltenzuordnung
├── sync/
│   └── source.py      # die Schnittstelle, an der die Quelle austauschbar wird
├── db/
│   ├── models.py      # SQLAlchemy-Schema
│   └── repository.py  # Speichern, Neuberechnen, Lesen
├── api/
│   └── main.py        # FastAPI
└── demo/
    └── seed.py        # Beispieldaten, die sich wie echte benehmen

web/                   # Next.js 15, React 19, TypeScript
├── lib/               # outcome(), Formatierung, API-Client
├── components/        # Kacheln, Diagramme, Listen, Gerüst
└── app/               # Dashboard, Kalender, Trades, Reports, Journal
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

Beim Aufteilen gilt: **Ergebnis und Swap gehen vollständig an den schließenden
Anteil, Kommission und Gebühr werden nach Volumen verteilt.** Das ist kein
Detail — MT5 bucht den realisierten Gewinn auf dem schließenden Deal. Wer ihn
nach Volumen aufteilt, schreibt dem neu eröffneten Trade ein Ergebnis zu, das
er noch gar nicht haben kann.

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
  die gewählte gehört in die Oberfläche geschrieben, und sie steht dort.
- **Offene Trades** bleiben außen vor. Ein schwebender Buchgewinn ist noch
  kein Ergebnis.

Wo ein Wert nicht bestimmbar ist, steht `None` und die Oberfläche zeigt einen
Strich. Eine Zahl, die aussieht wie eine Zahl, aber keine Aussage trägt, ist
schlimmer als eine Lücke.

Geldbeträge sind durchgehend `Decimal`. Bei `float` summieren sich
Rundungsfehler über tausende Trades zu Abweichungen, die man dann in der
Kennzahlen-Logik sucht statt im Datentyp.

## Die Prop-Regeln

`core/rules.py` rechnet die drei Grenzen aus, an denen ein Prop-Konto stirbt:
Tagesverlust, mitlaufender Maximalverlust vom Hoch, und die Konsistenzregel
(bei Alpha Capital 40 % — kein einzelner Tag darf mehr als 40 % des
Gesamtgewinns ausmachen).

Eine Unterscheidung ist dabei wichtig: `konto_verloren` bezieht die
Konsistenzregel **nicht** ein. Ein Konsistenzverstoß kostet die Auszahlung,
nicht das Konto. Beides in einen Zustand zu werfen hieße, dem Nutzer eine
Sperre zu zeigen, die es nicht gibt.

## Preisstellen und Risiko

`core/instruments.py` hält für jedes Symbol den Kontraktwert und die
Nachkommastellen. Zwei verschiedene Antworten auf fehlendes Wissen:

- **Risiko** bei unbekanntem Symbol → `None`. Es gibt dann kein R-Multiple,
  und die Oberfläche sagt das. Eine Null wäre die gefährlichste Antwort: Sie
  liefe als Division durch null in die R-Berechnung oder läse sich als
  „risikofrei".
- **Nachkommastellen** bei unbekanntem Symbol → 5. Hier gibt es kein
  „unbekannt", ein Preis muss gesetzt werden. Fünf Stellen zeigen zu viel,
  verschweigen aber nichts; zwei Stellen machten aus zwei verschiedenen
  Devisenkursen denselben.

Im Betrieb kommen beide Angaben aus `symbol_info()` von MT5 und überschreiben
die Tabelle.

## Schreiben — was der Nutzer hinterlässt

Notiz am Trade, Tags, Playbook-Zuordnung, Tagesnotiz und Verfassung.
Drei Festlegungen gelten für alles davon:

- **PATCH ändert nur, was dasteht.** Ein weggelassenes Feld bleibt, wie es
  war; ein ausdrückliches `null` löscht. Ohne die Unterscheidung könnte die
  Oberfläche keine Notiz speichern, ohne zugleich das Playbook zu leeren.
- **Die Tag-Liste wird als Ganzes gesetzt** (`PUT`), nicht einzeln ergänzt.
  Zweimal geschickt ergibt zweimal dasselbe; ein doppelter Klick kann nichts
  anrichten.
- **Nur Selbstgeschriebenes ist schreibbar.** Kein Endpunkt fasst eine
  gerechnete Größe an. Die kommen aus den Deals und würden beim nächsten
  Abgleich ohnehin überschrieben — bis dahin stünde eine Zahl in der
  Auswertung, die zu keinem Deal gehört.

Der Speicherzustand ist in der Oberfläche immer sichtbar, und gespeichert
wird ausdrücklich. Alles andere auf dem Bildschirm wächst aus den Deals
nach; eine Notiz gibt es genau einmal. Ein Auto-Save, der scheitert, sieht
aus wie einer, der klappt.

### Auswertung nach Tags

`/api/reports/setup`, `/fehler`, `/emotion` und `/tag`. Sie unterscheiden
sich von den anderen Rubriken in zwei Punkten, und beide stehen in der
Antwort:

- `overlapping: true` — ein Trade kann mehrere Tags tragen und zählt dann
  in mehreren Gruppen. Die Gruppen ergeben zusammen mehr als die Zahl der
  Trades. Wer das nicht sagt, lässt den Leser eine falsche Summe bilden.
- Trades **ohne** Tag bekommen eine eigene Gruppe. Ließe man sie weg, sähe
  der Report aus wie eine Aussage über alle Trades, beschriebe aber nur die
  schon eingeordneten. „Breakout verdient Geld" stimmte dann vielleicht nur,
  weil die schlechten Breakouts nie getaggt wurden — die stillste Art, sich
  selbst zu belügen.

Tags ohne Trade stehen nicht in den Vorschlägen: Die Liste ist zum
Wiederverwenden da. Gelöscht wird trotzdem nichts — wer die Bezeichnung
erneut tippt, bekommt dieselbe Marke wieder.

## Die Oberfläche

Zwei Regeln tragen den ganzen Entwurf:

1. **Grün und Rot gehören dem Ergebnis.** Keine grüne Schaltfläche, keine rote
   Short-Pille. `lib/outcome.ts` ist die einzige Stelle, die entscheidet, was
   welche Farbe bekommt.
2. **Farbe ist nie der einzige Kanal.** Jedes Ergebnis trägt zusätzlich ein
   Vorzeichen (`+` / `−` / `±`) und eine Regelposition (oben / unten / keine).
   Wer nur die Farbe nicht sieht, verliert keine Information.

Beide Regeln sind in `web/lib/__tests__/outcome.test.ts` festgeschrieben —
inklusive der Prüfung, dass drei Vorzeichen und drei Regelpositionen
tatsächlich unterscheidbar bleiben.

Die API liefert **Rohwerte, keine fertigen Zeichenketten.** Nur so kann der
Einheiten-Umschalter (€ / R / % / Pips) jede Zahl auf dem Bildschirm aus
derselben Quelle umrechnen. Fehlt die Bezugsgröße — kein Risiko, also kein R —
steht ein Strich, keine geschätzte Zahl.

## Loslegen

```bash
# Kern und API
pip install -e ".[dev]"
python scripts/seed_db.py                     # Beispieldaten anlegen
python -m uvicorn tradediary.api.main:app --port 8000

# Oberfläche
cd web && npm install && npm run dev          # http://localhost:3000
```

## Tests

```bash
pytest                                        # Kern, Regeln, Import, API
cd web && npm test                            # outcome() und Formatierung
cd web && npm run typecheck
```

Ein Test je Randfall — Umkehr, Teilausführungen, gleiche Zeitstempel,
Balance-Buchungen, mehrere Konten, jede Kennzahlen-Falle einzeln.

Die Frontend-Tests laufen über Nodes eigenen Test-Runner, ohne zusätzliche
Abhängigkeit. Damit Node denselben Quellcode lädt wie Next.js — der schreibt
Importe ohne Dateiendung — hängt `tools/ts-resolve.mjs` die Endung bei der
Auflösung nach.

### Die Oberfläche im Browser prüfen

```bash
cd web && node tools/pruefe-oberflaeche.mjs            # Darstellung
cd web && node tools/pruefe-oberflaeche.mjs --bilder   # zusätzlich Screenshots
cd web && node tools/pruefe-schreiben.mjs              # Speichern und Wiederfinden
```

Braucht Playwright (`npm install --no-save playwright`) und eine laufende
Oberfläche. Bewusst keine Abhängigkeit in `package.json`: Das Skript ist
Werkzeug, keine Voraussetzung zum Bauen.

Es lädt jede Seite auf 390, 834 und 1280 px in beiden Farbschemata und endet
mit Rückgabewert 1, sobald etwas nicht stimmt: Konsolenfehler, fehlgeschlagene
Requests, HTTP ≥ 400, ein fast leerer Hauptbereich, waagerechter Überlauf, eine
Trade-Liste, die auf einer Breite doppelt oder gar nicht erscheint, oder eine
Schrift, die nicht geladen wurde.

Jede dieser Zusicherungen steht dort, weil genau dieser Fehler schon einmal
aufgetreten ist. Die CORS-Einstellung erlaubte `localhost:3000`, der Browser
kam als `127.0.0.1:3000` — jede Seite blieb leer, ohne dass etwas rot wurde.
Die Trade-Liste hatte zwischen 720 und 1099 px eine tote Zone. Und das Raster
sprengte auf dem Telefon den Bildschirm um 87 px, weil `1fr` eine Spalte nicht
schmaler werden lässt als ihr breitester unteilbarer Inhalt.

`pruefe-schreiben.mjs` geht die Schreibwege im Browser durch: tippen,
speichern, Seite neu laden, wiederfinden. Ein Test gegen die API sagt, dass
der Endpunkt speichert — nicht, ob die Schaltfläche ihn trifft und die
Anzeige den Erfolg meldet. Auch das steht dort wegen eines echten Fehlers:
Die Meldung „gespeichert" verschwand im selben Augenblick, in dem sie
erscheinen sollte, weil die Seite den gespeicherten Wert zurückreichte und
damit den Zurücksetzen-Effekt auslöste.

## Was noch nicht da ist

Damit der Stand nicht besser klingt, als er ist:

- **Der MT5-Sammler.** Der automatische Abgleich ist entworfen
  (`sync/source.py` steht, mit Überlappungsfenster gegen verpasste Deals),
  aber der Sammler unter Wine auf dem Ubuntu-Dauerrechner ist nicht gebaut.
  Bis dahin füllt der CSV-Import.
- **Playbook-Seiten.** Playbooks lassen sich einem Trade zuordnen und über
  `/api/playbooks` lesen, aber nicht in der Oberfläche anlegen oder
  bearbeiten — und die Regel-Häkchen je Trade werden noch nicht gespeichert.
- **Einstellungen und Einrichtung.** Konten, Limits und Spaltenzuordnung für
  den CSV-Import stehen nur in der Datenbank, nicht in der Oberfläche.
- **Login.** Es gibt ein `User`-Schema, aber keine Anmeldung. Bis die steht,
  darf die App nicht offen im Netz stehen.
- **Deployment.**

## Als Nächstes

1. **MT5-Sammler** unter Wine. Bewusst ohne Logik: Er liest die Historie und
   schickt JSON. Was dort nicht steht, kann dort nicht kaputtgehen.
2. **Login und Deployment.** Ohne Anmeldung darf die App nicht offen im Netz
   stehen — das ist die Bedingung, bevor sie vom iPad aus erreichbar wird.
3. **Playbook-Seiten** samt Regel-Häkchen je Trade.

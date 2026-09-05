# TradeDiary

Ein Trading-Journal nach dem Vorbild von TradeZella: Trades laufen automatisch
aus MT5 ein, die Auswertung liegt als Web-App auf Mac, iPad und iPhone.

**Stand.** Kern, Datenbank, API, Anmeldung, Oberfläche und der MT5-Sammler
stehen. Alles bis auf den Sammler läuft hier gegen einen
Beispiel-Datenbestand; der Sammler ist gegen ein nachgebautes MT5 geprüft
und wartet auf den ersten Lauf an einem echten Terminal. Was noch fehlt, steht unten unter
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
│   ├── regelpruefung.py # Playbook-Regeln, die sich aus den Deals ergeben
│   └── instruments.py # Preisstellen und riskierter Betrag je Symbol
├── sources/
│   └── csv_source.py  # Broker-CSV mit einstellbarer Spaltenzuordnung
├── sync/
│   ├── source.py      # die Schnittstelle, an der die Quelle austauschbar wird
│   └── mt5_source.py  # MT5-Deals -> Kern-Deals, samt Zeitzonen-Rechnung
├── db/
│   ├── models.py      # SQLAlchemy-Schema
│   └── repository.py  # Speichern, Neuberechnen, Lesen
├── sicherheit.py      # Passwörter (scrypt) und Sitzungsmarken
├── api/
│   └── main.py        # FastAPI, Anmeldung, Zugriffsschutz
└── demo/
    └── seed.py        # Beispieldaten, die sich wie echte benehmen

collector/             # der Sammler, laeuft unter Wine
└── sammler.py         # verbinden, Historie lesen, JSON schicken -- mehr nicht

deploy/                # Inbetriebnahme
├── einrichten.sh      # ein Lauf, wiederholbar
├── Caddyfile          # TLS und ein Ursprung fuer alles
├── sicherung.py       # taeglich, mit Nachpruefung
└── *.service/.timer   # systemd

web/                   # Next.js 15, React 19, TypeScript
├── lib/               # outcome(), Formatierung, API-Client
├── components/        # Kacheln, Diagramme, Listen, Gerüst
└── app/               # Dashboard, Kalender, Trades, Reports, Journal,
                       # Playbooks, Einstellungen
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

Notiz am Trade, Tags, Playbook-Zuordnung samt Regel-Häkchen, Tagesnotiz
und Verfassung. Drei Festlegungen gelten für alles davon:

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

## Playbooks und Regeltreue

Ein Playbook ist die schriftliche Fassung dessen, was man zu handeln
behauptet: ein Name, eine Beschreibung und eine geordnete Regelliste. Die
Reihenfolge ist der Ablauf und wird deshalb nirgends sortiert.

Regeln sind **gemessen**, **abhakbar** oder ein **Merksatz**. Der
Unterschied ist nicht kosmetisch: Nur die ersten beiden zählen in die
Quote. „Nicht in die Nachricht hineintraden" ist richtig und wichtig,
lässt sich am einzelnen Trade aber nicht mit ja oder nein beantworten —
in einer Quote wäre es Füllmaterial.

### Gemessen statt gefragt

Eine Quote aus lauter selbstgesetzten Häkchen misst die eigene
Selbsteinschätzung. Man benotet sich selbst, und zwar rückblickend, wenn
das Ergebnis schon bekannt ist: Nach einem Gewinn erinnert man sich anders
an den Einstieg als nach einem Verlust.

Ein Teil der üblichen Regeln braucht diese Erinnerung nicht. Fünf davon
beantwortet `core/regelpruefung.py` aus den Deals:

| Prüfung | woraus |
|---|---|
| `stop_gesetzt` | `initial_sl` |
| `risiko_hoechstens` (%) | `risk_amount` gegen das Startkapital |
| `haltedauer_hoechstens` (min) | Eröffnung bis Schliessung |
| `volumen_hoechstens` (Lot) | Positionsvolumen |
| `nur_ein_einstieg` | Zahl der Einstiegs-Deals |

**Gemessen schlägt abgehakt.** Ein Häkchen an einer Regel, die inzwischen
eine Prüfung trägt, fällt heraus; von Hand setzen lässt sie sich gar nicht
erst (400). Das ist der ganze Zweck — sonst hätte man die Prüfung auch
weglassen können. Gelöscht wird das alte Häkchen aber nicht: Nimmt man die
Prüfung wieder weg, steht es wieder da.

**Drei Antworten, nicht zwei.** Fehlt eine Angabe, ist das kein Regelbruch,
sondern eine offene Frage. Ohne Stop gibt es kein Risiko zu vergleichen,
ohne Startkapital keinen Prozentbezug; beides ergibt `None` und damit eine
fehlende Zeile. Ein `False` aus Unwissen wäre die schlimmste Ausgabe dieses
Programms: Es sähe aus wie ein Befund über den Händler und wäre eine
Aussage über eine leere Spalte.

**Bruchstücke bekommen eine Halbregel.** Lag die Eröffnung vor dem
abgefragten Zeitraum, sind Haltedauer, Volumen und Zahl der Einstiege
*zu klein* gemessen. Reisst schon dieser Ausschnitt die Grenze, steht der
Bruch fest — das ist ein Befund. Liegt er darunter, folgt daraus nichts,
und die Regel bleibt offen. Ein „eingehalten" wäre hier ein Freispruch aus
Nichtwissen. (Diese Asymmetrie war beim ersten Anlauf nicht drin und ist
beim Nachlesen des eigenen Codes aufgefallen: Ein Bruchstück mit dreissig
gemessenen Minuten galt unter einer Grenze von sechzig als eingehalten,
obwohl der ungesehene Teil Stunden gedauert haben kann.)

### Drei Zustände, nicht zwei

Eine Regel ist **eingehalten**, **gebrochen** oder **unbeantwortet**. Der
dritte ist kein Zwischending, sondern der häufigste: Man geht einen Trade
durch, wenn man Zeit hat, nicht in dem Moment, in dem er einläuft.

Gäbe es nur ein Kästchen an oder aus, wäre ein Trade, den man nie
angesehen hat, von einem mit lauter Regelbrüchen nicht zu unterscheiden —
und die Regeltreue eines frisch eingelaufenen Trades stünde bei 0 %. Die
Zahl, die Disziplin messen soll, bestrafte damit den, der noch nicht
dazugekommen ist. Deshalb ist „unbeantwortet" die fehlende Zeile, und
`PUT /api/trades/{id}/regeln` entfernt, was nicht in der Liste steht,
statt es auf Nein zu setzen.

### Was `/api/reports/regeltreue` zusammenzählt

- **gebrochen** — mindestens eine abhakbare Regel ausdrücklich mit Nein
  beantwortet. Ein bestätigter Bruch bleibt ein Bruch, auch wenn der Rest
  der Liste offen ist.
- **eingehalten** — *alle* abhakbaren Regeln beantwortet, keine gebrochen.
  Nicht „keine gebrochene gefunden": Sonst zählte ein Trade, bei dem man
  nur die bequemen drei Häkchen gesetzt hat, als sauber — und die Quote
  misst dann Fleiß beim Abhaken.
- **offen** — der Rest. Steht getrennt in der Antwort (`unanswered`) und
  geht in keinen Vergleich ein.

Je Regel kommt zusätzlich, was ihr Bruch gekostet hat (`pnl_kept` gegen
`pnl_broken`). Das ist der eigentliche Zweck: Eine Regel, deren Bruch
nichts kostet, ist keine Regel, sondern eine Angewohnheit.

`self_reported` ist wahr, solange **irgendeine** Regel von Hand
beantwortet wird, und `measured_rules` sagt, wie viele gemessen werden.
Erst wenn jede abhakbare Regel eine Prüfung trägt, verschwindet der
Hinweis — eine Einschränkung stehenzulassen, wenn sie nicht mehr gilt, ist
genauso unehrlich wie sie wegzulassen, wenn sie gilt.

### Wiederfinden, was noch aussteht

Ein Journal führt man abends, nicht während des Handels — und danach muss
man wiederfinden, wo man stehen geblieben ist. Daran stirbt die
Gewohnheit: nicht am Aufschreiben, sondern am Suchen. `GET /api/trades`
nimmt deshalb `nachbearbeitung=` mit fünf Werten:

| Wert | heißt |
|---|---|
| `unberuehrt` | weder Notiz noch Tag noch Playbook — nie angesehen |
| `regeln_offen` | Playbook dran, aber nicht jede abhakbare Regel beantwortet |
| `ohne_notiz` / `ohne_tag` / `ohne_playbook` | jeweils genau das |

Jeder Wert sagt **eine nachprüfbare Sache**. Es gibt bewusst kein
zusammengesetztes „erledigt": Wann ein Trade durchgearbeitet ist, weiß nur
der Händler, und eine erfundene Definition stünde am Ende als
Fortschrittsbalken da, der etwas anderes misst, als er behauptet.

Zwei Feinheiten, beide mit einem Test dahinter:

- Gefiltert wird **in der Datenbank**, nicht auf der geholten Seite. Ein
  Filter, der erst nach dem Blättern greift, liefert auf Seite zwei etwas
  anderes als auf Seite eins — und `total` wäre eine falsche Zahl an genau
  der Stelle, an der sie als „noch offen" auf dem Schirm steht.
- Ein Playbook **ohne** abhakbare Regeln kann nichts offen haben. Sonst
  stünde jeder Trade eines reinen Merksatz-Playbooks für immer auf der
  Liste, und niemand bekäme ihn je herunter.

Auf der Trade-Seite steht die Zahl der unberührten Trades auch dann da,
wenn der Filter auf „alle" steht — sonst fände sie nur, wer ohnehin schon
danach sucht. Sie verschwindet, sobald nichts mehr offen ist; eine
dauerhafte Null wäre eine Mahnung ohne Anlass.

### Was beim Ändern nicht verlorengeht

Regeln behalten beim Speichern ihre `id`. Ohne das verlöre jede
Tippfehlerkorrektur sämtliche Häkchen, die je an dieser Regel hingen —
lautlos, denn die Oberfläche zeigte danach einfach leere Kästchen. Wer
eine Regel wirklich streicht, an der Antworten hängen, bekommt erst ein
409 mit deren Anzahl und muss ausdrücklich zustimmen.

Die Antworten überleben außerdem den Neuaufbau der Trades — dieselbe
Falle wie bei den Tags, die dort schon einmal zugeschlagen hat, und aus
demselben Grund ausdrücklich mitgeführt.

Ein Playbook-Wechsel am Trade löscht die alten Antworten nicht, zeigt und
zählt sie aber nicht mehr: Sie beantworten Regeln, die für diesen Trade
nicht mehr gelten. Zurückgewechselt sind sie wieder da — ein Fehlgriff in
der Auswahlliste ist damit umkehrbar.

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

## Der MT5-Sammler

Liest die Historie aus MetaTrader 5 und schickt sie hierher. Läuft unter
Wine auf dem Ubuntu-Dauerrechner — ausführlich in
[`collector/README.md`](../collector/README.md).

**Kein Expert Advisor.** Das ist für Prop-Konten der Punkt: Alpha Capital
verlangt für jeden EA vorherige Genehmigung. Ein EA läuft im Terminal und
kann handeln; der Sammler ist ein externes Programm, das über die offizielle
Python-Anbindung liest. Mit dem **Investor-Passwort** — dem Lesezugang —
kann er nachweislich nicht handeln.

Er rechnet nichts. Verbinden, Historie abrufen, JSON schicken; Umwandlung,
Round-Trips und Kennzahlen passieren alle hier. Der Grund: Wine plus ein
fremdes Python plus ein Terminal, das sich neu startet, ist das brüchigste
Stück der Kette. Was dort nicht steht, kann dort nicht kaputtgehen.

Sein Zugang ist eine eigene Marke (`scripts/marke.py`), keine
Browser-Sitzung. Sie steht dauerhaft in einer Datei auf dem Dauerrechner und
darf deshalb **nur einliefern, nicht lesen**: Wer sie findet, kommt damit
weder an Notizen noch an Kontostände. Sie gilt zudem für genau ein Konto —
das Zielkonto steht an der Marke, nicht in der Lieferung, lässt sich also
nicht umbiegen.

### Die Zeitfalle

MT5 liefert Zeitstempel in der Zeitzone des Broker-Servers, nicht in UTC.
Alpha Capital fährt auf EET/EEST, also UTC+2 im Winter und UTC+3 im Sommer.
Ohne Korrektur landet jeder Trade zwei bis drei Stunden zu spät — und zwar
in jeder Ansicht gleich, also unauffällig. Der Kalender ordnet Trades kurz
nach Mitternacht dem falschen Tag zu, die Auswertung nach Uhrzeit misst eine
Stunde, in der nie gehandelt wurde, und der Tagesverlust-Puffer rechnet mit
dem falschen Tag.

Der Versatz wird deshalb **je Lauf gemessen**, nicht eingetragen — der
Sommerzeitwechsel des Brokers erledigt sich damit von selbst. Gemessen wird
an einem Kurs-Tick, aber nur bei offenem Markt: Aus einem einzelnen Tick
lässt sich sein eigenes Alter nicht ablesen, und ein 20 Minuten alter ergibt
einen sauber gerundeten, plausiblen und falschen Versatz (nachgemessen:
+1,75 h statt +2,00 h). Der Sammler prüft darum mit zwei Ticks im Abstand
von anderthalb Sekunden, ob überhaupt Kurse hereinkommen.

Ist der Markt zu, meldet er `null`, und der zuletzt bekannte Versatz gilt
weiter. Auf null zurückzufallen hiesse zu behaupten, der Server laufe auf
UTC.

Gespeichert werden beide Zeiten: `time_utc` zum Rechnen, `time_broker` zum
Anzeigen.

### Ohne MT5 prüfen

```bash
python collector/probelauf.py        # Markt offen
python collector/probelauf.py --zu   # Markt geschlossen
```

Legt ein nachgebautes `MetaTrader5` in den Modulcache und lässt `sammler.py`
unverändert dagegen laufen: Felder auslesen, Lebendprüfung, Stops aus den
Orders nachtragen, Lieferung, Wiederholbarkeit. Was es nicht prüfen kann,
ist, ob das echte Terminal dieselben Felder liefert — der erste Lauf gehört
gegen ein Demo-Konto.

## Konten und Grenzwerte

Unter `/einstellungen`. Das ist der Bildschirm, ohne den die App nach einer
frischen Installation nicht benutzbar wäre: `einrichten.sh` legt ein leeres
Schema an, `nutzer.py` einen Nutzer — und danach führte kein Weg mehr zum
eigenen Handelskonto ausser von Hand per SQL.

Der eigentliche Inhalt sind die **Grenzwerte**. Sie sind nicht Beiwerk,
sondern der Grund, warum es die Regel-Puffer auf dem Dashboard gibt. Ein
falsch eingetragenes Limit zeigt einen Puffer, den es nicht gibt — und das
ist schlimmer als gar keiner, weil man sich darauf verlässt. Deshalb wird
jeder Wert geprüft, und jede Prüfung steht für eine Zahl, die sonst als
Sicherheit erschiene:

| Eingabe | Antwort |
|---|---|
| Limit `0` | abgelehnt — wäre vom ersten Augenblick an gerissen |
| Konsistenz `40` statt `0,4` | abgelehnt, mit dem Hinweis, wie es richtig geht |
| Tagesverlust über Gesamtverlust | abgelehnt — das Konto wäre verloren, bevor das Tageslimit greift |
| Limit leer | erlaubt — ein Privatkonto hat diese Grenzen nicht, und dann zeigt die App keinen Puffer statt eines erfundenen |

Die Fehlermeldungen nennen das Feld so, wie es auf dem Bildschirm heisst
(„Konsistenzregel", nicht `consistency_limit`). Klingt nebensächlich; wer
gerade in ein Feld getippt hat, findet die Stelle sonst nicht wieder.

**Gelöscht wird nur ein leeres Konto.** Ein verlorenes Challenge-Konto
gehört auf `status: verloren`, nicht in den Papierkorb — seine Trades sind
die Lehre, für die man bezahlt hat.

## Anmeldung

Serverseitige Sitzungen in einem HttpOnly-Cookie. Vier Entscheidungen, die
man an der Umsetzung sieht:

- **`scrypt` aus der Standardbibliothek**, ohne zusätzliche Abhängigkeit. Ein
  speicherhartes Verfahren mit ~96 ms je Prüfung: für eine Anmeldung nicht
  spürbar, für das Durchprobieren von Passwortlisten teuer. Die Parameter
  stehen im Hash mit drin, also lassen sie sich später erhöhen, ohne alte
  Hashes ungültig zu machen.
- **HttpOnly-Cookie statt `localStorage`.** JavaScript kommt an die Marke
  nicht heran, kann sie also auch nicht ausleiten.
- **Sitzungen in der Datenbank, kein JWT.** Eine Sitzung lässt sich beenden.
  Ein JWT gilt bis zum Ablauf — wer sein iPad verliert, kann es nicht
  zurückrufen. `/api/auth/sessions` listet die offenen, `DELETE` beendet eine.
- **In der Datenbank steht nur der Hash der Marke.** Wer die Datenbank liest,
  hat damit keine gültige Sitzung in der Hand — so wie er mit den
  Passwort-Hashes noch kein Passwort hat.

Dazu: gleiche Antwort und gleiche Laufzeit für „E-Mail gibt es nicht" und
„Passwort falsch" (sonst ließen sich vorhandene Adressen abfragen), und eine
einfache Bremse nach acht Fehlversuchen in 15 Minuten.

Es gibt **keine Registrierung und kein „Passwort vergessen" im Browser**. Ein
offenes Anmeldeformular im Netz ist eine Einladung, und ein Zurücksetzen per
Mail wäre bei Selbstbetrieb die unsicherste Stelle im ganzen Aufbau. Beides
läuft am Rechner:

```bash
python scripts/nutzer.py anlegen ferhat@example.com
python scripts/nutzer.py passwort ferhat@example.com   # beendet alle Sitzungen
python scripts/nutzer.py abmelden ferhat@example.com
python scripts/nutzer.py liste
```

### Wem gehören die Daten

Mit der Anmeldung entsteht eine Frage, die es vorher nicht gab: Sieht ein
Nutzer die Daten eines anderen? Die Antwort hängt an einer einzigen Stelle —
`filter_aus_query` prüft das angefragte Konto und setzt sonst die Liste der
eigenen. Ein Endpunkt, der den Filter benutzt, kann die Prüfung nicht
vergessen.

Das war nötig, weil vorher genau das schieflag: `/api/accounts` gab *jedes*
Konto in der Datenbank zurück, `/api/trades` ohne `account_id` alle Trades,
`/api/tags` die Tags aller Nutzer. Mit einem einzigen Nutzer sah alles
richtig aus. `tests/test_api_anmeldung.py` hält beide Fragen fest: 17
Endpunkte antworten ohne Anmeldung mit 401, und ein zweiter Nutzer kommt an
nichts heran.

## Loslegen

```bash
# Kern und API
pip install -e ".[dev]"
python scripts/seed_db.py                     # Beispieldaten + Zugang
python -m uvicorn tradediary.api.main:app --port 8000

# Oberfläche
cd web && npm install && npm run dev          # http://localhost:3000
```

`seed_db.py` gibt ein **zufälliges** Passwort aus, einmal. Es steht nirgends
im Quelltext: Standardpasswörter sind der häufigste Weg, auf dem
selbstbetriebene Software übernommen wird. Verloren? `scripts/nutzer.py
passwort <email>`.

### Im Heimnetz erreichbar machen

```bash
export TRADEDIARY_CORS="http://192.168.1.42:3000"   # IP des Ubuntu-Rechners
python -m uvicorn tradediary.api.main:app --host 0.0.0.0 --port 8000
cd web && NEXT_PUBLIC_API_BASE="http://192.168.1.42:8000" npm run dev -- -H 0.0.0.0
```

Dann `http://192.168.1.42:3000` vom Mac und vom iPad. **Nur im eigenen WLAN** —
keine Portfreigabe im Router, solange kein TLS davor steht: Ohne HTTPS gehen
Passwort und Sitzungs-Cookie im Klartext über die Leitung.

### In Betrieb nehmen

Vollständig in [`deploy/README.md`](../deploy/README.md), in einem Zug:

```bash
sudo apt install python3-venv nodejs npm rsync curl caddy
sudo ./deploy/einrichten.sh
```

Das legt einen Systemnutzer an, baut Python-Umgebung und Oberfläche, richtet
systemd-Dienste und die tägliche Sicherung ein. Wiederholbar: Ein zweiter
Lauf aktualisiert, ohne Datenbank oder Zugangsdaten anzufassen.

**Ein Ursprung für alles.** Caddy liegt davor und verteilt: `/api/*` an die
API, alles andere an die Oberfläche. API und Oberfläche hören nur auf
`127.0.0.1`. Damit gibt es kein CORS, das Cookie ist same-site, und nach
außen ist nur ein Port offen. Möglich macht das eine leere
`NEXT_PUBLIC_API_BASE` beim Bauen — dann stehen relative Pfade im Bundle.

`TRADEDIARY_COOKIE_SECURE` steht in der Entwicklung auf `false`, weil das
Cookie sonst über `http://` nie gesetzt würde und die Anmeldung fehlschlüge,
ohne dass irgendwo etwas rot wird. Hinter TLS gehört es auf `true`; das
Einrichtungsskript schreibt es so in `/etc/tradediary/api.env`.

### Sicherung

Täglich um vier, 30 Tage lang, mit Nachprüfung der Kopie. Eine Sicherung,
die nie geöffnet wurde, ist keine Sicherung, sondern eine Hoffnung — und
eine gültige, *leere* Datenbank ist der gefährlichste Fall, weil sie jede
Prüfung besteht und beim Zurückspielen alles durch nichts ersetzt. Beides
fängt `deploy/sicherung.py` ab.

| Umgebungsvariable | Standard | Wofür |
|---|---|---|
| `TRADEDIARY_DB` | `sqlite:///tradediary.db` | Datenbank; für Postgres die URL |
| `TRADEDIARY_CORS` | localhost/127.0.0.1 :3000,:3001 | erlaubte Ursprünge, kommagetrennt |
| `TRADEDIARY_COOKIE_SECURE` | `false` | auf `true`, sobald HTTPS steht |
| `TRADEDIARY_COOKIE_SAMESITE` | `lax` | nur ändern, wenn Oberfläche und API auf verschiedenen Domains liegen |
| `NEXT_PUBLIC_API_BASE` | `http://127.0.0.1:8000` | wohin die Oberfläche fragt |

## Tests

```bash
pytest                                        # Kern, Regeln, Import, API
cd web && npm test                            # outcome() und Formatierung
cd web && npm run typecheck
```

Ein Test je Randfall — Umkehr, Teilausführungen, gleiche Zeitstempel,
Balance-Buchungen, mehrere Konten, jede Kennzahlen-Falle einzeln.

`test_abfragen.py` zählt stattdessen SQL-Abfragen. Es misst keine Zeit —
Zeitmessungen in einer Suite fallen auf einer ausgelasteten Maschine
grundlos um —, sondern fängt den einen Fehler, der sich einschleicht, ohne
dass etwas rot wird: ein Nachladen je Zeile. An 1.200 Trades nachgemessen
kostete ein Report **1.207 Abfragen und 570 ms**, weil `trade_block` von
jeder Zeile die Tags las und von jeder Regel-Antwort, zu welchem Playbook
sie gehört. Mit dem Vorladen in `zeilen_laden` sind es 11 Abfragen und
416 ms; der Rest ist die Decimal-Rechnung und keine Datenbanksache mehr.
Bei fünfzig Trades fällt so etwas nicht auf und wächst dann linear mit.

Die Frontend-Tests laufen über Nodes eigenen Test-Runner, ohne zusätzliche
Abhängigkeit. Damit Node denselben Quellcode lädt wie Next.js — der schreibt
Importe ohne Dateiendung — hängt `tools/ts-resolve.mjs` die Endung bei der
Auflösung nach.

### Die Oberfläche im Browser prüfen

```bash
cd web
export TD_EMAIL=… TD_PASSWORT=…        # aus der Ausgabe von seed_db.py
node tools/pruefe-anmeldung.mjs        # Anmeldung, Cookie, Abmelden
node tools/pruefe-oberflaeche.mjs      # Darstellung auf drei Breiten
node tools/pruefe-schreiben.mjs        # Speichern und Wiederfinden
node tools/pruefe-konten.mjs           # Konto anlegen, Grenzwerte, Löschen
node tools/pruefe-playbooks.mjs        # Playbook, Regel-Häkchen, Regeltreue
node tools/pruefe-nacharbeit.mjs       # was noch aussteht, wiederfinden
node tools/pruefe-oberflaeche.mjs --bilder   # zusätzlich Screenshots
```

Alle sechs sind **wiederholbar**: Zweimal hintereinander auf derselben
Datenbank ergibt zweimal grün. Das war nicht von Anfang an so.
`pruefe-konten.mjs` trug einen festen Grenzwert ein und lief damit genau
einmal — beim zweiten Lauf stand die Zahl schon im Feld, nichts änderte
sich, und die Prüfung meldete einen Fehler, den es nicht gab. Der
naheliegende zweite Anlauf, den Wert einfach zu senken, drückte ihn unter
den Tagesverlust; der Server lehnte zu Recht ab, und wieder sah es nach
einem Fehler in der App aus. Jetzt wechselt der Wert zwischen zwei
gültigen hin und her, und eine eigene Zusicherung sagt es, wenn ein
Speichern abgelehnt wurde — sonst ist das von einem wirkungslosen
Grenzwert nicht zu unterscheiden.

Rückgabewert 0 wenn alles stimmt, 1 bei Befunden, 2 wenn die Anmeldung
scheitert — nachgemessen, nicht angenommen.

Ein Hinweis zum Nebeneinander: `npm run build` schreibt nach `.next-build`,
`npm run dev` nach `.next`. Ohne die Trennung überschreibt ein Bau das
Verzeichnis, aus dem der laufende Dev-Server gerade liest; der antwortet
dann auf jeder Seite mit 500. Das sieht aus wie ein Fehler in der App und
kostet eine halbe Stunde Suche an der falschen Stelle — hier zweimal
passiert, bevor `distDir` in `next.config.mjs` stand.

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

Derselbe Fehler ist beim Regel-Feld ein zweites Mal entstanden und dort
wieder vom Browser-Lauf gefunden worden — die API-Tests waren grün, die
Häkchen standen nach dem Neuladen richtig, und trotzdem sah der Nutzer
beim Klick auf Speichern nichts. Ein Muster, das man einmal repariert
hat, baut man beim nächsten Mal wieder ein; nur der Lauf im Browser merkt
es.

`pruefe-playbooks.mjs` prüft zusätzlich die teuerste denkbare Verwechslung:
eine Regel umformulieren und dabei die Häkchen von Dutzenden Trades
verlieren. Der Verlust fiele nicht auf — die Kästchen wären danach einfach
leer. Und es räumt hinter sich auf, damit nicht jeder Lauf ein Playbook
mehr in der Datenbank hinterlässt.

## Was noch nicht da ist

Damit der Stand nicht besser klingt, als er ist:

- **Der erste Lauf des Sammlers an einem echten MT5.** Er ist gebaut und
  gegen ein nachgebautes MT5 durchgemessen (`collector/probelauf.py`), aber
  ob das echte Terminal dieselben Felder unter denselben Namen liefert und
  ob die Annahme über die Zeitzone am Server von Alpha Capital stimmt, lässt
  sich nur dort prüfen. Der erste Lauf gehört gegen ein Demo-Konto.
- **Regeln, die den Kontext brauchen.** Fünf Prüfungen beantworten sich
  aus den Deals, aber „nur in der ersten Handelsstunde" oder „nicht gegen
  den Trend" nicht: Für die erste fehlt die Handelszeitzone des Kontos,
  für die zweite ein Trendmass. Solche Regeln bleiben abhakbar, und die
  Quote bleibt an dieser Stelle selbstberichtet.
- **Spaltenzuordnung für den CSV-Import** lässt sich nur über die API
  mitgeben, nicht in der Oberfläche einstellen. Die Erkennung trifft die
  gängigen Broker-Exporte von selbst; bei einem exotischen Format braucht es
  einen API-Aufruf von Hand.
- **Der erste Lauf von `einrichten.sh` auf dem Zielrechner.** Der Aufbau ist
  gegen echtes Caddy durchgemessen und alle systemd-Units validieren, aber
  `useradd`, Systempfade und das Zusammenspiel unter laufendem systemd liessen
  sich hier nicht ausprobieren — in diesem Container ist systemd offline.
- **Zwei-Faktor-Anmeldung.** Für ein Konto, das ins Internet zeigt, wäre sie
  angebracht; für den Betrieb im Heimnetz ist sie es nicht.

## Als Nächstes

1. **Auf dem Ubuntu-Rechner einrichten** und den Sammler an ein Demo-Konto
   hängen. Die beiden verbliebenen ungeprüften Punkte, beide nur dort prüfbar.
2. **Schema-Wanderungen.** `trade_rule_checks` ist die erste Tabelle, die zu
   einer schon laufenden Installation dazukäme. Das geht noch von selbst:
   `init_db()` ruft beim Start `create_all`, und an einer Datenbank ohne
   diese Tabelle nachgemessen — sie ist nach dem nächsten Start da, mit
   allen drei Spalten. Was `create_all` *nicht* kann, ist eine geänderte
   Spalte. Spätestens dafür braucht es Alembic.
3. **Weitere Prüfungen**, sobald sich im Betrieb zeigt, welche Regeln man
   wirklich jeden Abend abhakt. Die Registry in `core/regelpruefung.py`
   nimmt eine neue in wenigen Zeilen auf; die Oberfläche baut ihre
   Auswahlliste aus `/api/pruefungen` und muss dafür nicht angefasst
   werden.

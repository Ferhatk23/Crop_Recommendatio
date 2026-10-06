# Der MT5-Sammler

Liest die Handelshistorie aus MetaTrader 5 und schickt sie an TradeDiary.
Läuft unter Wine auf dem Ubuntu-Dauerrechner, neben dem Terminal.

## Warum unter Wine

Die offizielle Python-Anbindung von MetaTrader (`MetaTrader5`) gibt es nur
für Windows. Unter Linux-Python lässt sie sich nicht installieren — das ist
keine Fehlkonfiguration, sondern der Stand der Dinge. Wine ist der Weg, der
ohne zweiten Rechner und ohne Cloud-Dienst auskommt.

## Das hier ist kein Expert Advisor

Wichtig für Prop-Konten: **Alpha Capital verlangt für jeden EA vorherige
Genehmigung.** Ein EA läuft *im* Terminal und kann handeln.

Dieses Skript ist keiner. Es ist ein externes Programm, das über die
offizielle Python-Anbindung *liest* — dieselbe Schnittstelle, die auch
Portfolio-Werkzeuge und Steuersoftware benutzen. Es sendet keine Order und
kann keine senden.

Damit das nachprüfbar bleibt und nicht nur behauptet ist: **Nimm das
Investor-Passwort.** Das ist der Lesezugang; damit kann niemand handeln,
auch dieses Skript nicht. Trägst du stattdessen das Master-Passwort ein,
gibst du einem Programm Handelsrechte, das sie nicht braucht.

## Einrichten

### 1. Wine und Windows-Python

```bash
sudo apt install wine64 winbind
export WINEPREFIX=~/.mt5
winecfg                                   # einmal, auf Windows 10 stellen

# Windows-Python 3.11 (64 bit) herunterladen und installieren
wine python-3.11.9-amd64.exe

# Die MT5-Anbindung
wine ~/.mt5/drive_c/users/$USER/AppData/Local/Programs/Python/Python311/python.exe \
     -m pip install MetaTrader5
```

MT5 selbst wird ganz normal unter Wine installiert und einmal von Hand
gestartet: Konto einloggen, unter *Ansicht → Marktübersicht* die Symbole
sichtbar machen, die du handelst.

### 2. Zugang anlegen

Auf dem Server, wo die API läuft:

```bash
python scripts/marke.py anlegen 1 --label "Ubuntu-Sammler"
```

Die Marke wird **einmal** ausgegeben. Sie darf nur einliefern, nicht lesen.

### 3. Zugangsdaten eintragen

```bash
cp collector/.env.beispiel collector/.env
$EDITOR collector/.env
```

### 4. Prüfen

```bash
cd collector
wine python.exe sammler.py --pruefen
```

Meldet, ob das Terminal antwortet, ob die Marke gilt und ob sich der
Zeitversatz gerade messen lässt.

### 5. Alt-Historie einmal nachholen

```bash
wine python.exe sammler.py --tage 365
```

### 6. Dauerbetrieb

```bash
wine python.exe sammler.py --dauer
```

Als systemd-Dienst, damit er den Neustart überlebt — `~/.config/systemd/user/tradediary-sammler.service`:

```ini
[Unit]
Description=TradeDiary MT5-Sammler
After=network-online.target

[Service]
Type=simple
Environment=WINEPREFIX=%h/.mt5
Environment=WINEDEBUG=-all
WorkingDirectory=%h/tradediary/collector
ExecStart=/usr/bin/wine %h/.mt5/drive_c/users/%u/AppData/Local/Programs/Python/Python311/python.exe sammler.py --dauer
Restart=always
RestartSec=60

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now tradediary-sammler
systemctl --user status tradediary-sammler
loginctl enable-linger $USER      # läuft auch ohne Anmeldung weiter
```

## Die Zeitfalle

Die einzige Stelle, an der dieses Skript etwas rechnet — und die, an der
man sich verrechnet.

MT5 liefert Zeitstempel in der Zeitzone des **Broker-Servers**, nicht in
UTC. Alpha Capital fährt wie die meisten auf EET/EEST, also UTC+2 im Winter
und UTC+3 im Sommer. Ohne Korrektur landet jeder Trade zwei bis drei Stunden
zu spät — und das sieht in jeder Ansicht gleich plausibel aus:

- Der Kalender ordnet Trades kurz nach Mitternacht dem falschen Tag zu.
- Die Auswertung nach Uhrzeit misst eine Stunde, in der nie gehandelt wurde.
- Der Tagesverlust-Puffer rechnet mit dem falschen Tag und kann eine
  Regelverletzung übersehen.

Deshalb wird der Versatz **je Lauf gemessen** statt fest eingetragen: Der
Sommerzeitwechsel des Brokers erledigt sich damit von selbst.

Gemessen wird an einem Kurs-Tick — aber nur, wenn der Markt offen ist. Das
prüft der Sammler, indem er zweimal im Abstand von anderthalb Sekunden
schaut, ob der Tick vorrückt. Der Grund ist unangenehm konkret: Aus einem
einzelnen Tick lässt sich sein eigenes Alter nicht ablesen, und ein
20 Minuten alter Tick ergibt einen sauber gerundeten, plausiblen und
falschen Versatz. Nachgemessen:

| Tick-Alter | gemessener Versatz | |
|---|---|---|
| 0 min | +2,00 h | richtig |
| 7 min | +2,00 h | richtig (Rundung fängt es auf) |
| 20 min | +1,75 h | **falsch** |
| 90 min | +0,50 h | **falsch** |

Ist der Markt zu, meldet der Sammler `null` und die API behält den zuletzt
bekannten Versatz. Auf null zurückzufallen hiesse zu behaupten, der Server
laufe auf UTC.

Beide Zeiten werden gespeichert: `time_utc` zum Rechnen, `time_broker` zum
Anzeigen. Wer eine Order um 09:31 gesetzt hat, findet sie im Journal um
09:31 wieder.

## Ohne MT5 prüfen

```bash
python collector/probelauf.py        # Markt offen
python collector/probelauf.py --zu   # Markt geschlossen
```

Legt ein nachgebautes `MetaTrader5` in den Modulcache und lässt `sammler.py`
unverändert dagegen laufen. Prüft das Auslesen der Felder, die
Lebendprüfung, das Nachtragen der Stops und die Wiederholbarkeit der
Lieferung — alles, was sich ohne echtes Terminal prüfen lässt.

**Was es nicht prüft:** ob das echte MT5 dieselben Felder unter denselben
Namen liefert, und ob die Annahme über die Zeitzone am echten Server
stimmt. Beides geht nur an einem echten Terminal. Der erste Lauf gehört
deshalb gegen ein Demo-Konto, mit einem Blick in die Trade-Liste: Stimmen
die Uhrzeiten mit dem überein, was im Terminal steht?

## Wenn etwas nicht läuft

**`MetaTrader5` lässt sich nicht installieren** — du bist mit Linux-Python
unterwegs. Es muss das Windows-Python unter Wine sein.

**„MT5 antwortet nicht"** — läuft das Terminal? Es muss offen sein; die
Anbindung redet mit dem laufenden Prozess, nicht mit den Dateien.

**Keine Deals, obwohl gehandelt wurde** — steht das Symbol in der
Marktübersicht? Und liegt der Handel im abgefragten Zeitraum? `--tage 365`
holt weiter zurück.

**Zeiten um Stunden daneben** — der Versatz wurde bei geschlossenem Markt
nie gemessen. Einmal während der Handelszeit laufen lassen; danach steht er.

**Der Dienst läuft, aber nichts kommt an** — `journalctl --user -u
tradediary-sammler -f`. Der Sammler protokolliert jeden Lauf mit Zeitstempel,
auch die leeren.

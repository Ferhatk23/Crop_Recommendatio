# TradeDiary in Betrieb nehmen

Auf dem Ubuntu-Dauerrechner. Danach erreichst du das Journal vom Mac, vom
iPad und vom iPhone — verschlüsselt, mit Anmeldung, mit täglicher Sicherung.

## In einem Zug

```bash
git clone -b claude/tradezella-neues-projekt-ob2nbi \
    https://github.com/Ferhatk23/Crop_Recommendatio tradediary
cd tradediary
sudo apt install python3-venv nodejs npm rsync curl caddy
sudo ./deploy/einrichten.sh --caddy auto --email ferhat@example.com
```

Das war es. `--caddy auto` ermittelt die Adresse dieses Rechners im
Heimnetz, baut daraus die Proxy-Konfiguration, lässt Caddy ein eigenes
Zertifikat ausstellen und prüft die Konfiguration, bevor es sie lädt.
`--email` legt dich als Nutzer an und fragt nach deinem Passwort.

Hast du eine eigene Domain, dann `--caddy journal.example.com` statt
`auto` — dann holt Caddy ein Zertifikat von Let's Encrypt. Beides ohne
Flags lässt das Skript die Dienste einrichten und sonst nichts anfassen.

Das Skript ist wiederholbar. Ein zweiter Lauf aktualisiert den Code und baut
neu, ohne die Datenbank oder die Zugangsdaten anzufassen — genau deshalb kann
man es zum Aktualisieren benutzen und muss es nicht vorher jedes Mal lesen.

## Und dann: die ersten Minuten in der App

Die Reihenfolge ist nicht beliebig. Das Handelskonto entsteht in der
Oberfläche, und erst wenn es da ist, lässt sich eine Marke dafür anlegen.

1. **`https://<adresse>` öffnen** — die Adresse hat das Skript am Ende
   ausgegeben. Beim ersten Mal warnt der Browser wegen des selbst
   ausgestellten Zertifikats; auf dem iPhone lässt sich Caddys
   Wurzelzertifikat einmal unter Einstellungen → Profil installieren,
   dann ist Ruhe.

2. **Anmelden** mit der E-Mail und dem Passwort von oben.

3. **Handelskonto anlegen** unter ⚙ Einstellungen → „Konto hinzufügen".
   Die Grenzwerte deiner Prop-Firma stehen in der Kontoeröffnungs-Mail.
   Die Konsistenzregel wird als Anteil eingetragen: 40 % sind `0,4`.
   Ohne dieses Konto bleibt das Dashboard leer — es gibt dann nichts, auf
   das sich ein Puffer beziehen könnte.

4. **Marke für den Sammler** — jetzt erst, denn sie hängt am Konto:

   ```bash
   sudo -u tradediary env TRADEDIARY_DB=sqlite:////var/lib/tradediary/tradediary.db \
        /opt/tradediary/.venv/bin/python \
        /opt/tradediary/scripts/marke.py anlegen 1
   ```

   Die Nummer ist die des Kontos aus Schritt 3. Stimmt sie nicht, zeigt
   das Skript die vorhandenen Konten an. Die ausgegebene Zeile erscheint
   **genau einmal** — sie gehört in `collector/.env`.

5. **Sammler anschliessen** — MT5 unter Wine, dann `collector/README.md`.
   Das ist der fummeligste Teil und darf warten: Das Journal läuft auch
   ohne ihn, nur stehen dann noch keine Trades drin.

## Wie es aufgebaut ist

```
                    Internet
                       │
                    :443 TLS
                       │
                 ┌─────▼─────┐
                 │   Caddy   │  Zertifikat holt es sich selbst
                 └─────┬─────┘
              /api/*   │   alles andere
            ┌──────────┴──────────┐
            ▼                     ▼
    127.0.0.1:8000        127.0.0.1:3000
      uvicorn               next start
         │
    /var/lib/tradediary/tradediary.db
```

**Ein Ursprung für alles.** Oberfläche und API liegen hinter derselben
Domain: `/api/*` geht an die API, alles andere an die Oberfläche. Das ist
keine Bequemlichkeit, sondern spart drei Fehlerquellen:

- **Kein CORS.** Keine Freigabeliste, die man beim Umzug auf eine neue Domain
  nachziehen muss und deren Vergessen sich als „Failed to fetch" zeigt.
- **Kein Cookie-Ärger.** Das Sitzungs-Cookie ist same-site.
- **Nur ein Port nach draußen.** API und Oberfläche hören ausschließlich auf
  `127.0.0.1` — von außen nicht erreichbar, auch nicht bei offener Firewall.

Möglich macht das eine leere `NEXT_PUBLIC_API_BASE` beim Bauen: Dann sind die
Pfade im Bundle relativ (`/api/trades`), und der Proxy verteilt sie.

## Die Dienste

| Dienst | Was | Wo |
|---|---|---|
| `tradediary-api` | uvicorn | 127.0.0.1:8000 |
| `tradediary-web` | Next.js | 127.0.0.1:3000 |
| `tradediary-sicherung.timer` | tägliche Sicherung, 04:00 | — |
| `caddy` | TLS und Verteilung | :80, :443 |

```bash
systemctl status tradediary-api tradediary-web
journalctl -u tradediary-api -f
systemctl restart tradediary-api          # nach Änderung an /etc/tradediary/api.env
```

Beide Dienste laufen als Systemnutzer `tradediary` ohne Anmeldemöglichkeit,
mit `ProtectSystem=strict`. Die API darf genau ein Verzeichnis beschreiben —
`/var/lib/tradediary`. Die Oberfläche darf nirgends schreiben, sie liefert nur
Vorgebautes aus.

## Einstellungen

`/etc/tradediary/api.env`, Rechte 640, Eigentümer `root:tradediary`. Sie steht
bewusst nicht in der Unit-Datei: `systemctl cat` zeigt eine Unit jedem an, der
auf dem Rechner ein Terminal hat.

| Variable | Standard | Wofür |
|---|---|---|
| `TRADEDIARY_DB` | `sqlite:///…/tradediary.db` | Datenbank |
| `TRADEDIARY_COOKIE_SECURE` | `true` | hinter TLS immer `true` |
| `TRADEDIARY_CORS` | leer | leer lassen — ein Ursprung, kein CORS |

### Warum SQLite und nicht Postgres

Ein Nutzer, ein paar tausend Trades im Jahr, ein Schreiber. SQLite ist dafür
nicht die Sparlösung, sondern die richtige: eine Datei, kein zweiter Dienst,
keine Verbindungsverwaltung, und die Sicherung ist ein Dateikopie. Postgres
brächte hier nur Betriebsaufwand.

## Sicherung

Läuft täglich um vier über `tradediary-sicherung.timer`, nach
`/var/backups/tradediary`, 30 Tage lang.

```bash
systemctl start tradediary-sicherung        # von Hand auslösen
systemctl list-timers tradediary-sicherung  # wann läuft sie das nächste Mal
ls -la /var/backups/tradediary
```

Das Skript macht drei Dinge, die ein `cp` nicht macht:

1. **Es kopiert im laufenden Betrieb sicher.** SQLites Sicherungs-API zieht
   einen in sich stimmigen Abzug, auch während die API schreibt. Ein `cp` auf
   eine offene Datenbank liefert gelegentlich eine halbe Transaktion — und das
   merkt man erst beim Zurückspielen.
2. **Es prüft die Kopie**, statt sie nur abzulegen. Eine Sicherung, die nie
   geöffnet wurde, ist keine Sicherung, sondern eine Hoffnung.
3. **Es verwirft eine leere Sicherung.** Das ist der gefährlichste Fall: Eine
   gültige, leere Datenbank besteht jede Prüfung und ersetzt beim
   Zurückspielen alles durch nichts.

`Persistent=true` im Timer ist wichtig: War der Rechner um vier aus, läuft die
Sicherung beim nächsten Start nach. Ohne das gäbe es an jedem Tag mit Neustart
schlicht keine.

### Zurückspielen

```bash
sudo systemctl stop tradediary-api tradediary-web
sudo /opt/tradediary/.venv/bin/python /opt/tradediary/deploy/sicherung.py \
    --zurueckspielen /var/backups/tradediary/tradediary_2026-09-04_0400.db.gz
sudo systemctl start tradediary-api tradediary-web
```

Hier stand bis vor kurzem ein `gunzip -c … > datenbank.db`. Es wurde
einmal wirklich ausprobiert, und dabei kamen drei Fehler heraus — jeder
davon hätte im Ernstfall zugeschlagen, also an dem Tag, an dem man eine
Sicherung braucht:

1. **Die Umleitung legt das Ziel an, bevor das Entpacken läuft.**
   Scheitert es — falscher Pfad, kaputte Datei, volle Platte —, steht
   eine *leere* Datei da, wo das Journal war. Und das Original ist weg.
2. **`sudo -u tradediary … > datei` schreibt als Aufrufer.** Die
   Umleitung macht die eigene Shell, nicht sudo. Die Datenbank gehörte
   danach root; der Dienst läuft als `tradediary` und könnte in seine
   eigene Datenbank nicht schreiben.
3. **Es prüfte nichts.** Eine leere oder beschädigte Sicherung ersetzte
   alles durch nichts.

`--zurueckspielen` macht es in dieser Reihenfolge: Sicherung öffnen und
zählen, danebenschreiben, Rechte von der alten Datei übernehmen, die alte
Datei als `tradediary.db.vorher_<datum>` beiseitelegen, erst dann
umbenennen. Ein Fehlschlag lässt die vorhandene Datenbank unberührt, und
wer die falsche Sicherung erwischt hat, hat danach noch beides.

Läuft die API noch, bricht es ab und sagt welcher Prozess — sonst
schreibt der Dienst weiter in die alte, inzwischen ersetzte Datei, und
beim nächsten Neustart ist das alles weg. Mit `--trotzdem` geht es doch.

Vorher ansehen, was drin ist:

```bash
/opt/tradediary/.venv/bin/python /opt/tradediary/deploy/sicherung.py \
    --pruefen /var/backups/tradediary/tradediary_2026-09-04_0400.db.gz
```

**Die Sicherung liegt auf derselben Platte wie die Datenbank.** Gegen einen
Bedienfehler hilft das, gegen einen Plattendefekt nicht. Wer das schließen
will, kopiert `/var/backups/tradediary` zusätzlich woandershin — ein
`rsync` auf ein NAS oder in eine Cloud reicht.

## Aktualisieren

```bash
cd ~/tradediary && git pull
sudo ./deploy/einrichten.sh
```

Datenbank und Zugangsdaten bleiben. Das Schema wird beim Start ergänzt; für
größere Umbauten steht nichts Automatisches bereit — vorher sichern.

## Ohne öffentliche Domain

Im Heimnetz gibt es kein Zertifikat von Let's Encrypt. Dann den zweiten,
auskommentierten Block im `Caddyfile` benutzen: `tls internal` stellt ein
eigenes aus. Der Browser warnt einmal; auf dem iPhone lässt sich Caddys
Wurzelzertifikat als Profil installieren, dann ist Ruhe.

`TRADEDIARY_COOKIE_SECURE` bleibt dabei auf `true` — die Verbindung ist ja
verschlüsselt. Nur bei reinem `http://` gehört es auf `false`, sonst wird das
Sitzungs-Cookie nie gesetzt und die Anmeldung schlägt fehl, ohne dass
irgendwo etwas rot wird.

## Was hier geprüft ist — und was nicht

Der Aufbau ist gegen echtes Caddy durchgemessen: Produktionsbau der
Oberfläche, uvicorn mit `--proxy-headers`, Caddy mit `tls internal` davor,
und alle drei Browser-Prüfungen laufen durch den Proxy. Bestätigt wurde
dabei:

- Die Pfade im Bundle sind relativ, `127.0.0.1:8000` steht nirgends drin.
- Das Sitzungs-Cookie kommt als `HttpOnly; SameSite=lax; Secure` an.
- Die Kopfzeilen (HSTS, `X-Frame-Options`, `nosniff`) stehen an jeder Antwort,
  und Caddy verrät sich nicht über `Server:`.
- Alle vier systemd-Units gehen sauber durch `systemd-analyze verify`.
- Die Sicherung erkennt Rotation, leere und beschädigte Datenbanken — jeweils
  mit Rückgabewert 1 und einer Zeile Klartext statt eines Stacktraces.

**Nicht geprüft**, weil es diesen Rechner nicht gibt: das Zusammenspiel unter
laufendem systemd (hier ist es offline), das Holen eines echten Zertifikats
von Let's Encrypt, und `einrichten.sh` als Ganzes mit `useradd` und
Systempfaden. Der erste Lauf gehört auf den Zielrechner — er bricht bei jedem
Schritt mit einer Meldung ab statt halbfertig weiterzulaufen.

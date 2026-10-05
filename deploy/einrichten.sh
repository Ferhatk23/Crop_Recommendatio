#!/usr/bin/env bash
#
# Richtet TradeDiary auf einem Ubuntu-Rechner ein.
#
#   sudo ./deploy/einrichten.sh
#
# Was passiert:
#   1. Systemnutzer `tradediary` anlegen (ohne Anmeldemöglichkeit)
#   2. Code nach /opt/tradediary, Datenbank nach /var/lib/tradediary
#   3. Python-Umgebung und Frontend-Bau
#   4. systemd-Dienste und Sicherungs-Timer
#
# Das Skript ist wiederholbar: Ein zweiter Lauf aktualisiert, ohne die
# Datenbank oder die Zugangsdaten anzufassen. Das ist der Punkt -- ein
# Aktualisierungsskript, das man vor jedem Lauf lesen muss, benutzt man
# irgendwann nicht mehr.

set -euo pipefail

NUTZER=tradediary
ZIEL=/opt/tradediary
DATEN=/var/lib/tradediary
SICHERUNGEN=/var/backups/tradediary
EINSTELLUNGEN=/etc/tradediary
QUELLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

melde() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warne() { printf '\033[33m    %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo starten."; exit 1; }

# --- Voraussetzungen --------------------------------------------------------

melde "Voraussetzungen prüfen"
fehlt=()
command -v python3 >/dev/null || fehlt+=("python3")
command -v node    >/dev/null || fehlt+=("nodejs")
command -v npm     >/dev/null || fehlt+=("npm")
command -v rsync   >/dev/null || fehlt+=("rsync")
command -v curl    >/dev/null || fehlt+=("curl")
python3 -c "import venv" 2>/dev/null || fehlt+=("python3-venv")

if [ ${#fehlt[@]} -gt 0 ]; then
    echo "Fehlt: ${fehlt[*]}"
    echo "  sudo apt install ${fehlt[*]}"
    exit 1
fi
NODE_PFAD="$(command -v node)"
echo "    python3 $(python3 -V | cut -d' ' -f2), node $(node -v) unter $NODE_PFAD"

# --- Nutzer und Verzeichnisse ----------------------------------------------

melde "Nutzer und Verzeichnisse"
if ! id "$NUTZER" >/dev/null 2>&1; then
    # Systemnutzer ohne Anmeldemöglichkeit: Der Dienst braucht keine Shell,
    # und ein Konto ohne Shell ist eine Angriffsfläche weniger.
    useradd --system --home-dir "$ZIEL" --shell /usr/sbin/nologin "$NUTZER"
    echo "    Nutzer $NUTZER angelegt"
else
    echo "    Nutzer $NUTZER gibt es schon"
fi

install -d -o "$NUTZER" -g "$NUTZER" -m 750 "$ZIEL" "$DATEN" "$SICHERUNGEN"
install -d -o root -g "$NUTZER" -m 750 "$EINSTELLUNGEN"

# --- Code ------------------------------------------------------------------

melde "Code nach $ZIEL"
# --delete räumt Entferntes weg, aber niemals die Datenbank oder die
# Zugangsdaten des Sammlers -- die liegen ausserhalb bzw. sind
# ausgenommen.
rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
    --exclude '.next' --exclude '.next-build' --exclude '*.db' \
    --exclude 'collector/.env' \
    "$QUELLE/" "$ZIEL/"
chown -R "$NUTZER:$NUTZER" "$ZIEL"

# --- Python ----------------------------------------------------------------

melde "Python-Umgebung"
if [ ! -d "$ZIEL/.venv" ]; then
    sudo -u "$NUTZER" python3 -m venv "$ZIEL/.venv"
fi
sudo -u "$NUTZER" "$ZIEL/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$NUTZER" "$ZIEL/.venv/bin/pip" install --quiet -e "$ZIEL"
echo "    fertig"

# --- Einstellungen ---------------------------------------------------------

melde "Einstellungen"
if [ ! -f "$EINSTELLUNGEN/api.env" ]; then
    cat > "$EINSTELLUNGEN/api.env" <<ENDE
# Zugangsdaten und Einstellungen der API.
# Nach jeder Änderung: systemctl restart tradediary-api

TRADEDIARY_DB=sqlite:///$DATEN/tradediary.db

# Hinter einem Proxy mit TLS gehört das auf true -- sonst schickt der
# Browser das Sitzungs-Cookie auch über unverschlüsselte Verbindungen.
TRADEDIARY_COOKIE_SECURE=true

# Oberfläche und API liegen hinter derselben Domain, also braucht es
# keine CORS-Freigabe. Der Wert bleibt leer und ist Absicht.
TRADEDIARY_CORS=
ENDE
    chown root:"$NUTZER" "$EINSTELLUNGEN/api.env"
    chmod 640 "$EINSTELLUNGEN/api.env"
    echo "    $EINSTELLUNGEN/api.env angelegt"
else
    echo "    $EINSTELLUNGEN/api.env bleibt unverändert"
fi

# --- Datenbank -------------------------------------------------------------

melde "Datenbank"
if [ ! -f "$DATEN/tradediary.db" ]; then
    sudo -u "$NUTZER" env TRADEDIARY_DB="sqlite:///$DATEN/tradediary.db" \
        "$ZIEL/.venv/bin/python" -c \
        "from tradediary.db.repository import engine_bauen, schema_anlegen; \
         import os; schema_anlegen(engine_bauen(os.environ['TRADEDIARY_DB']))"
    echo "    Leeres Schema angelegt"
    warne "Noch kein Nutzer. Nach dem Einrichten:"
    warne "  sudo -u $NUTZER $ZIEL/.venv/bin/python $ZIEL/scripts/nutzer.py anlegen <email>"
else
    echo "    Vorhandene Datenbank bleibt unangetastet"
fi

# --- Oberfläche ------------------------------------------------------------

melde "Oberfläche bauen"
cd "$ZIEL/web"
sudo -u "$NUTZER" npm ci --silent 2>/dev/null || sudo -u "$NUTZER" npm install --silent

# Die leere Basis ist der Kern des Aufbaus: relative Pfade, ein Ursprung,
# kein CORS. Siehe web/lib/api.ts.
#
# Das Bauprotokoll geht über `mktemp` und nicht nach `/tmp/tradediary-bau.log`.
# Der feste Name war angreifbar: Dieses Skript läuft als root, und eine
# Umleitung folgt einem Verweis. Wer die Datei vorher als Symlink auf eine
# beliebige Systemdatei anlegt, lässt root sie überschreiben --
# nachgemessen, nicht vermutet. `mktemp` vergibt einen unvorhersagbaren
# Namen und legt die Datei selbst an.
BAU_LOG="$(mktemp -t tradediary-bau.XXXXXXXX)"
trap 'rm -f "$BAU_LOG"' EXIT

# Die Umleitung macht root, nicht `$NUTZER` -- und genau so soll es sein:
# Das Protokoll gehört dann root, und der unprivilegierte Bauprozess kann
# es nicht überschreiben. Der gefährliche Teil war der feste Pfad, nicht
# das.
# shellcheck disable=SC2024
sudo -u "$NUTZER" env NEXT_PUBLIC_API_BASE="" TD_DIST_DIR=.next-build \
    npx next build > "$BAU_LOG" 2>&1 || {
        echo "Bau fehlgeschlagen, letzte Zeilen:"; tail -20 "$BAU_LOG"; exit 1;
    }
echo "    fertig"

# --- Dienste ---------------------------------------------------------------

melde "systemd-Dienste"
install -m 644 "$ZIEL/deploy/tradediary-api.service"       /etc/systemd/system/
# Den ermittelten node-Pfad einsetzen statt einen zu raten.
sed "s|__NODE__|$NODE_PFAD|" "$ZIEL/deploy/tradediary-web.service" \
    > /etc/systemd/system/tradediary-web.service
chmod 644 /etc/systemd/system/tradediary-web.service
install -m 644 "$ZIEL/deploy/tradediary-sicherung.service" /etc/systemd/system/
install -m 644 "$ZIEL/deploy/tradediary-sicherung.timer"   /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now tradediary-api tradediary-web tradediary-sicherung.timer

sleep 3
for dienst in tradediary-api tradediary-web; do
    if systemctl is-active --quiet "$dienst"; then
        echo "    $dienst läuft"
    else
        echo "    $dienst läuft NICHT:"
        journalctl -u "$dienst" -n 15 --no-pager | sed 's/^/      /'
        exit 1
    fi
done

# --- Probe -----------------------------------------------------------------

melde "Probe"
if curl -fsS http://127.0.0.1:8000/api/health >/dev/null; then
    echo "    API antwortet"
else
    echo "    API antwortet nicht"; exit 1
fi
if curl -fsS -o /dev/null http://127.0.0.1:3000/; then
    echo "    Oberfläche antwortet"
else
    echo "    Oberfläche antwortet nicht"; exit 1
fi

melde "Fertig"
cat <<ENDE
Beide Dienste laufen auf 127.0.0.1 -- von aussen noch nicht erreichbar.
Das ist Absicht: Davor gehört ein Proxy mit TLS.

  1. Nutzer anlegen
     sudo -u $NUTZER $ZIEL/.venv/bin/python $ZIEL/scripts/nutzer.py anlegen <email>

  2. Caddy einrichten
     sudo apt install caddy
     sudo cp $ZIEL/deploy/Caddyfile /etc/caddy/Caddyfile
     sudo \$EDITOR /etc/caddy/Caddyfile        # Domain eintragen
     sudo systemctl reload caddy

  3. Marke für den Sammler
     sudo -u $NUTZER $ZIEL/.venv/bin/python $ZIEL/scripts/marke.py anlegen 1

Protokolle:  journalctl -u tradediary-api -f
Sicherung:   systemctl start tradediary-sicherung   # von Hand auslösen
             ls -la $SICHERUNGEN
ENDE

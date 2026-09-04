"""Die HTTP-Schnittstelle vor dem Kern.

Bewusst dünn: Sie filtert, ruft `core` auf und formt das Ergebnis in JSON.
Gerechnet wird hier nichts -- jede Kennzahl kommt aus `core`, damit es
genau eine Stelle gibt, an der eine Definition steht.

Zwei Entwurfsentscheidungen, die man an der Ausgabe sieht:

* **Ein nicht bestimmbarer Wert ist `null`, niemals `0`.** Ein Profit
  Factor ohne Verluste, ein R ohne Stop -- die Oberfläche zeigt dafür
  einen Strich. Eine Null wäre eine Behauptung.
* **Rohwerte, keine formatierten Zeichenketten.** Der Einheiten-Umschalter
  (€/R/%/Pips) rechnet im Frontend aus derselben Quelle um; wer hier
  fertige Texte lieferte, machte ihn unmöglich.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import sicherheit
from ..core import instruments, metrics as kern_metrics, rules, score as kern_score
from ..core.metrics import daily_pnl
from ..core.models import Outcome
from ..db import models as db
from ..db.repository import (
    engine_bauen,
    kennzahlen,
    schema_anlegen,
    session_factory,
    sync_vermerken,
    trade_zu_kern,
    trades_laden,
    zeilen_laden,
)
from ..sources.csv_source import importiere

DB_URL = os.environ.get("TRADEDIARY_DB", "sqlite:///tradediary.db")

engine = engine_bauen(DB_URL)
Session_ = session_factory(engine)

app = FastAPI(
    title="TradeDiary API",
    version="0.1.0",
    description="Trading-Journal mit automatischer Übernahme aus MT5.",
)

# `localhost` und `127.0.0.1` sind für den Browser zwei verschiedene
# Ursprünge. Wer nur einen freigibt, bekommt je nachdem, welche Adresse
# im Browser steht, ein "Failed to fetch" -- und sucht den Fehler dann in
# der API, die per curl tadellos antwortet.
STANDARD_CORS = ",".join(
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (3000, 3001)
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("TRADEDIARY_CORS", STANDARD_CORS).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def hole_session():
    with Session_() as session:
        yield session


# ---------------------------------------------------------------------------
# Anmeldung
# ---------------------------------------------------------------------------
#
# Serverseitige Sitzungen in einem HttpOnly-Cookie. Drei Entscheidungen,
# die man an der Umsetzung sieht:
#
# * **HttpOnly.** Die Marke steht nicht im `localStorage`, sondern in
#   einem Cookie, das JavaScript nicht lesen kann. Ein eingeschleustes
#   Skript kann damit zwar noch Anfragen stellen, aber die Marke nicht
#   ausleiten und nicht anderswo weiterverwenden.
# * **Serverseitig statt JWT.** Eine Sitzung in der Datenbank lässt sich
#   beenden. Ein JWT gilt bis zum Ablauf -- wer sein iPad verliert, kann
#   es nicht zurückrufen.
# * **Gleiche Antwort für falsche E-Mail und falsches Passwort**, und
#   gleiche Laufzeit dazu. Sonst ließe sich herausfinden, welche Adressen
#   es gibt, ohne ein einziges Passwort zu erraten.

COOKIE = "tradediary_sitzung"

#: Wie lange eine Anmeldung hält. Lang, und das ist Absicht: Das hier ist
#: ein persönliches Journal auf dem eigenen Telefon. Wer sich jeden Tag
#: neu anmelden muss, schaut seltener hinein -- und ein Journal, in das
#: man nicht schaut, ist wertlos. Die Sitzung lässt sich jederzeit
#: beenden, das ist der Ausgleich.
SITZUNGSDAUER = timedelta(days=30)

#: Ab wann die Restlaufzeit beim Benutzen wieder aufgefüllt wird. Ohne
#: das würde man nach genau 30 Tagen mitten im Betrieb ausgeloggt.
VERLAENGERN_AB = timedelta(days=7)

#: `Secure` verlangt HTTPS. Im Heimnetz läuft die App auf http://, dort
#: würde das Cookie sonst nie gesetzt -- und die Anmeldung schlüge fehl,
#: ohne dass irgendwo etwas rot wird. Beim Veröffentlichen mit TLS gehört
#: der Wert auf `true`.
COOKIE_SECURE = os.environ.get("TRADEDIARY_COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.environ.get("TRADEDIARY_COOKIE_SAMESITE", "lax")

#: Einfache Bremse gegen das Durchprobieren von Passwörtern.
#:
#: Im Prozessspeicher, nicht in der Datenbank: Bei einem Neustart ist sie
#: weg, und bei mehreren Arbeitsprozessen zählt jeder für sich. Für eine
#: selbstbetriebene App mit einem Nutzer reicht das und kostet nichts.
#: Wer sie ernsthaft braucht, gehört hinter einen Reverse Proxy, der das
#: besser kann.
ANMELDE_VERSUCHE = 8
ANMELDE_FENSTER = timedelta(minutes=15)
_fehlversuche: dict[str, list[datetime]] = {}


def _zu_viele_versuche(kennung: str) -> bool:
    jetzt = datetime.now(timezone.utc)
    versuche = [
        z for z in _fehlversuche.get(kennung, []) if jetzt - z < ANMELDE_FENSTER
    ]
    _fehlversuche[kennung] = versuche
    return len(versuche) >= ANMELDE_VERSUCHE


def _versuch_vermerken(kennung: str) -> None:
    _fehlversuche.setdefault(kennung, []).append(datetime.now(timezone.utc))


def _geraet(request: Request) -> str | None:
    """Grob, wofür es reicht -- nicht der vollständige User-Agent."""
    ua = request.headers.get("user-agent", "")
    if not ua:
        return None
    for muster, name in (
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Macintosh", "Mac"),
        ("Android", "Android"),
        ("Windows", "Windows"),
        ("Linux", "Linux"),
    ):
        if muster in ua:
            return name
    return ua[:60]


def aktueller_nutzer(
    request: Request, session: Session = Depends(hole_session)
) -> db.User:
    """Der angemeldete Nutzer. 401, wenn keiner.

    Jeder Endpunkt mit Daten hängt daran. Das ist bewusst keine Option
    mit Standardwert: Ein Endpunkt, der die Abhängigkeit vergisst, fällt
    beim Test auf, weil er dann ohne Anmeldung antwortet -- und genau das
    prüfen die Tests.
    """
    marke = request.cookies.get(COOKIE)
    if not marke:
        raise HTTPException(401, "Nicht angemeldet")

    sitzung = session.scalars(
        select(db.Sitzung).where(db.Sitzung.token_hash == sicherheit.marken_hash(marke))
    ).first()
    if sitzung is None:
        raise HTTPException(401, "Nicht angemeldet")

    ablauf = sitzung.expires_at
    if ablauf.tzinfo is None:
        ablauf = ablauf.replace(tzinfo=timezone.utc)

    jetzt = datetime.now(timezone.utc)
    if ablauf <= jetzt:
        session.delete(sitzung)
        session.commit()
        raise HTTPException(401, "Sitzung abgelaufen")

    # Restlaufzeit auffüllen, wenn sie zur Neige geht.
    if ablauf - jetzt < SITZUNGSDAUER - VERLAENGERN_AB:
        sitzung.expires_at = jetzt + SITZUNGSDAUER
    sitzung.last_seen = jetzt
    session.commit()

    nutzer = session.get(db.User, sitzung.user_id)
    if nutzer is None:
        raise HTTPException(401, "Nicht angemeldet")
    return nutzer


class Anmeldung(BaseModel):
    email: str
    password: str


def _nutzer_block(nutzer: db.User) -> dict:
    return {"id": nutzer.id, "email": nutzer.email}


@app.post("/api/auth/login")
def anmelden(
    daten: Anmeldung,
    request: Request,
    antwort: Response,
    session: Session = Depends(hole_session),
):
    email = daten.email.strip().lower()

    if _zu_viele_versuche(email):
        raise HTTPException(
            429,
            "Zu viele Fehlversuche. Bitte in einigen Minuten noch einmal versuchen.",
        )

    nutzer = session.scalars(
        select(db.User).where(func.lower(db.User.email) == email)
    ).first()

    # Gibt es die Adresse nicht, wird trotzdem gerechnet -- sonst wäre die
    # Antwort für unbekannte Adressen messbar schneller.
    if nutzer is None:
        sicherheit.blindprüfung(daten.password)
        _versuch_vermerken(email)
        raise HTTPException(401, "E-Mail oder Passwort stimmt nicht")

    if not sicherheit.pruefe_passwort(daten.password, nutzer.password_hash):
        _versuch_vermerken(email)
        raise HTTPException(401, "E-Mail oder Passwort stimmt nicht")

    _fehlversuche.pop(email, None)

    marke = sicherheit.neue_marke()
    session.add(
        db.Sitzung(
            user_id=nutzer.id,
            token_hash=marke.hash,
            expires_at=datetime.now(timezone.utc) + SITZUNGSDAUER,
            device=_geraet(request),
        )
    )
    session.commit()

    antwort.set_cookie(
        COOKIE,
        marke.klartext,
        max_age=int(SITZUNGSDAUER.total_seconds()),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )
    return _nutzer_block(nutzer)


@app.post("/api/auth/logout")
def abmelden(
    request: Request, antwort: Response, session: Session = Depends(hole_session)
):
    """Beendet die Sitzung -- auch die in der Datenbank.

    Nur das Cookie zu löschen reichte nicht: Wer die Marke vorher
    abgegriffen hat, könnte sie weiter verwenden.
    """
    marke = request.cookies.get(COOKIE)
    if marke:
        sitzung = session.scalars(
            select(db.Sitzung).where(
                db.Sitzung.token_hash == sicherheit.marken_hash(marke)
            )
        ).first()
        if sitzung is not None:
            session.delete(sitzung)
            session.commit()

    antwort.delete_cookie(COOKIE, path="/")
    return {"status": "abgemeldet"}


@app.get("/api/auth/me")
def wer_bin_ich(nutzer: db.User = Depends(aktueller_nutzer)):
    return _nutzer_block(nutzer)


@app.get("/api/auth/sessions")
def sitzungen(
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Die offenen Anmeldungen -- damit man ein verlorenes Gerät abmelden kann."""
    zeilen = session.scalars(
        select(db.Sitzung)
        .where(db.Sitzung.user_id == nutzer.id)
        .order_by(db.Sitzung.last_seen.desc())
    ).all()
    return [
        {
            "id": s.id,
            "device": s.device,
            "created_at": _iso(s.created_at),
            "last_seen": _iso(s.last_seen),
            "expires_at": _iso(s.expires_at),
        }
        for s in zeilen
    ]


@app.delete("/api/auth/sessions/{sitzung_id}")
def sitzung_beenden(
    sitzung_id: int,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    zeile = session.get(db.Sitzung, sitzung_id)
    # Dieselbe Antwort für "gibt es nicht" und "gehört jemand anderem":
    # Sonst ließe sich durch Probieren zählen, wie viele Sitzungen es gibt.
    if zeile is None or zeile.user_id != nutzer.id:
        raise HTTPException(404, "Sitzung nicht gefunden")
    session.delete(zeile)
    session.commit()
    return {"status": "beendet"}


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def z(wert: Decimal | float | None) -> float | None:
    """Decimal zu JSON-Zahl. `None` bleibt `None` -- das ist der Punkt."""
    return None if wert is None else float(wert)


def _iso(zeit: datetime | None) -> str | None:
    """Zeitstempel als ISO-Text, immer mit Zeitzone.

    SQLite gibt naive Zeitstempel zurück. Ohne das `Z` läse der Browser
    sie als Ortszeit -- und eine Sitzung sähe je nach Zeitzone abgelaufen
    aus oder um Stunden zu lang.
    """
    if zeit is None:
        return None
    return (zeit if zeit.tzinfo else zeit.replace(tzinfo=timezone.utc)).isoformat()


def zeitraum(
    von: str | None, bis: str | None
) -> tuple[datetime | None, datetime | None]:
    def lies(text: str | None, ende: bool) -> datetime | None:
        if not text:
            return None
        try:
            tag = date.fromisoformat(text)
        except ValueError:
            raise HTTPException(400, f"Datum nicht lesbar: {text}")
        stunde = datetime.combine(
            tag, datetime.max.time() if ende else datetime.min.time()
        )
        return stunde.replace(tzinfo=timezone.utc)

    return lies(von, False), lies(bis, True)


class Filter(BaseModel):
    account_id: int | None = None
    von: str | None = None
    bis: str | None = None
    symbol: str | None = None
    direction: str | None = None


def eigene_konten(session: Session, nutzer: db.User) -> list[int]:
    """Die Konten-IDs des Nutzers."""
    return list(
        session.scalars(
            select(db.Account.id).where(db.Account.user_id == nutzer.id)
        ).all()
    )


def pruefe_konto(session: Session, nutzer: db.User, account_id: int) -> db.Account:
    """Holt ein Konto und stellt sicher, dass es dem Nutzer gehört.

    Dieselbe Antwort für "gibt es nicht" und "gehört jemand anderem".
    Ein 403 wäre die Auskunft, dass das Konto existiert -- und schon das
    ist mehr, als jemand erfahren soll, der es nicht sehen darf.
    """
    konto = session.get(db.Account, account_id)
    if konto is None or konto.user_id != nutzer.id:
        raise HTTPException(404, "Konto nicht gefunden")
    return konto


def hole_eigenen_trade(session: Session, nutzer: db.User, trade_id: int) -> db.Trade:
    """Holt einen Trade und stellt sicher, dass er dem Nutzer gehört.

    Der Weg führt über das Konto: Ein Trade hat keinen Nutzer, ein Konto
    schon. Wieder dieselbe Antwort für "gibt es nicht" und "gehört jemand
    anderem" -- sonst ließe sich durch Hochzählen der IDs herausfinden,
    wie viele Trades andere Nutzer haben.
    """
    zeile = session.get(db.Trade, trade_id)
    if zeile is None:
        raise HTTPException(404, "Trade nicht gefunden")
    konto = session.get(db.Account, zeile.account_id)
    if konto is None or konto.user_id != nutzer.id:
        raise HTTPException(404, "Trade nicht gefunden")
    return zeile


def filter_aus_query(
    account_id: int | None = Query(None),
    von: str | None = Query(None),
    bis: str | None = Query(None),
    symbol: str | None = Query(None),
    direction: str | None = Query(None),
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
) -> dict:
    """Der Filter -- und zugleich die Stelle, an der die Berechtigung hängt.

    Beides zusammen, und das ist Absicht. Vorher war `account_id` ein
    reiner Filter: Wer ihn wegließ, bekam *alle* Konten -- auch die
    fremder Nutzer. Solange es nur einen gab, fiel das nicht auf; mit der
    Anmeldung wäre es ein Berechtigungsfehler geworden.

    Deshalb setzt diese Abhängigkeit immer `account_ids`: Entweder das
    eine geprüfte Konto oder alle eigenen. Ein Endpunkt, der den Filter
    benutzt, kann die Prüfung damit nicht vergessen -- und einer, der ihn
    nicht benutzt, hat auch keine Daten zu schützen.
    """
    start, ende = zeitraum(von, bis)

    if account_id is not None:
        pruefe_konto(session, nutzer, account_id)
        erlaubt = [account_id]
    else:
        erlaubt = eigene_konten(session, nutzer)

    return {
        "account_id": account_id,
        "account_ids": erlaubt,
        "von": start,
        "bis": ende,
        "symbol": symbol,
        "direction": direction,
    }


# ---------------------------------------------------------------------------
# Konten und Zustand
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    """Lebenszeichen -- bewusst ohne Anmeldung und bewusst ohne Zahlen.

    Ein Überwachungsdienst muss wissen, ob die App antwortet. Er muss
    nicht wissen, wie viele Trades darin stehen: Das war vorher der Fall
    und verriet einem Unangemeldeten, wie aktiv das Konto ist.
    """
    return {"status": "ok"}


@app.get("/api/accounts")
def accounts(
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Die Konten des Nutzers. Prop-Trader haben über die Zeit mehrere.

    Hier stand vorher `select(db.Account)` ohne Bedingung -- also *alle*
    Konten, auch fremde. Mit einem einzigen Nutzer fiel das nicht auf.
    """
    zeilen = session.scalars(
        select(db.Account)
        .where(db.Account.user_id == nutzer.id)
        .order_by(db.Account.id)
    ).all()
    return [konto_block(session, a) for a in zeilen]


def konto_block(session: Session, a: db.Account) -> dict:
    zustand = session.get(db.SyncState, a.id)
    return {
        "id": a.id,
        "label": a.label,
        "login": a.login,
        "broker": a.broker,
        "server": a.server,
        "currency": a.currency,
        "phase": a.phase.value if hasattr(a.phase, "value") else a.phase,
        "status": a.status.value if hasattr(a.status, "value") else a.status,
        "starting_balance": z(a.starting_balance),
        "limits": {
            "daily_loss": z(a.daily_loss_limit),
            "max_loss": z(a.max_loss_limit),
            "consistency": z(a.consistency_limit),
            "warn_threshold": z(a.warn_threshold),
            "profit_target": z(a.profit_target),
        },
        # Wie viele Ausführungen daran hängen -- die Oberfläche braucht
        # das, um zu entscheiden, ob ein Konto noch löschbar ist und ob
        # eine Änderung am Startkapital die Equity-Kurve verschiebt.
        "deal_count": session.scalar(
            select(func.count()).select_from(db.Deal).where(db.Deal.account_id == a.id)
        )
        or 0,
        "sync": sync_block(zustand),
    }


# ---------------------------------------------------------------------------
# Konten anlegen und ändern
# ---------------------------------------------------------------------------
#
# Ohne diese Endpunkte ist die App nach einer frischen Installation nicht
# benutzbar: `einrichten.sh` legt ein leeres Schema an, `nutzer.py` einen
# Nutzer -- und dann fehlte jeder Weg, das eigene Handelskonto einzutragen,
# ausser von Hand per SQL.
#
# Die Grenzwerte sind dabei nicht Beiwerk, sondern der Grund, warum es die
# Regel-Puffer gibt. Ein falsch eingetragenes Tagesverlust-Limit zeigt
# einen Puffer, den es nicht gibt -- und das ist schlimmer als gar keiner,
# weil man sich darauf verlässt.


class KontoEingabe(BaseModel):
    label: str
    login: str | None = None
    broker: str | None = None
    server: str | None = None
    currency: str = "EUR"
    phase: str = "challenge"
    status: str = "aktiv"
    starting_balance: float = 0
    daily_loss_limit: float | None = None
    max_loss_limit: float | None = None
    consistency_limit: float | None = None
    warn_threshold: float = 0.8
    profit_target: float | None = None


class KontoAenderung(BaseModel):
    """Wie bei den Trades: Nur was dasteht, wird geändert."""

    label: str | None = None
    login: str | None = None
    broker: str | None = None
    server: str | None = None
    currency: str | None = None
    phase: str | None = None
    status: str | None = None
    starting_balance: float | None = None
    daily_loss_limit: float | None = None
    max_loss_limit: float | None = None
    consistency_limit: float | None = None
    warn_threshold: float | None = None
    profit_target: float | None = None


#: Feldname -> wie das Feld in der Oberfläche heisst.
#:
#: Eine Fehlermeldung, die "consistency_limit" sagt, hilft niemandem, der
#: gerade in ein Feld namens "Konsistenzregel" getippt hat. Der Nutzer
#: soll die Stelle wiederfinden, nicht den Quelltext lesen müssen.
FELDNAMEN = {
    "label": "Bezeichnung",
    "daily_loss_limit": "Tagesverlust",
    "max_loss_limit": "Gesamtverlust",
    "consistency_limit": "Konsistenzregel",
    "warn_threshold": "Warnschwelle",
    "profit_target": "Gewinnziel",
    "starting_balance": "Startkapital",
    "phase": "Phase",
    "status": "Status",
}


def _pruefe_kontowerte(werte: dict) -> None:
    """Die Grenzwerte auf Plausibilität prüfen.

    Jede Prüfung hier steht für eine Zahl, die in der Oberfläche als
    Sicherheit erscheinen würde, ohne eine zu sein.
    """
    name = lambda feld: FELDNAMEN.get(feld, feld)
    if "label" in werte and not (werte["label"] or "").strip():
        raise HTTPException(400, "Das Konto braucht eine Bezeichnung")

    for feld in ("phase", "status"):
        wert = werte.get(feld)
        if wert is None:
            continue
        typ = db.KontoPhase if feld == "phase" else db.KontoStatus
        try:
            typ(wert)
        except ValueError:
            erlaubt = ", ".join(x.value for x in typ)
            raise HTTPException(
                400, f"Unbekannte {name(feld)}: {wert} (möglich: {erlaubt})"
            )

    # Ein Limit von 0 wäre kein Limit, sondern ein sofort gerissenes:
    # Der Puffer stünde von der ersten Sekunde an auf null.
    for feld in ("daily_loss_limit", "max_loss_limit", "profit_target"):
        wert = werte.get(feld)
        if wert is not None and wert <= 0:
            raise HTTPException(
                400,
                f"{name(feld)} muss grösser als null sein — ein Limit von 0 "
                "wäre vom ersten Augenblick an gerissen. Leer lassen, wenn "
                "es diese Grenze bei deinem Konto nicht gibt.",
            )

    # Anteile, keine Prozentzahlen. Wer 40 statt 0.4 einträgt, bekäme eine
    # Konsistenzregel, die nie greift.
    for feld in ("consistency_limit", "warn_threshold"):
        wert = werte.get(feld)
        if wert is not None and not 0 < wert <= 1:
            raise HTTPException(
                400,
                f"{name(feld)} ist ein Anteil zwischen 0 und 1 — "
                "40 % werden als 0,4 eingetragen, nicht als 40.",
            )

    if werte.get("starting_balance") is not None and werte["starting_balance"] < 0:
        raise HTTPException(400, "Das Startkapital kann nicht negativ sein")

    if "label" in werte and len((werte["label"] or "").strip()) > 120:
        raise HTTPException(400, "Die Bezeichnung ist zu lang (höchstens 120 Zeichen)")

    tag = werte.get("daily_loss_limit")
    gesamt = werte.get("max_loss_limit")
    if tag is not None and gesamt is not None and tag > gesamt:
        raise HTTPException(
            400,
            "Der Tagesverlust darf nicht über dem Gesamtverlust liegen — "
            "sonst wäre das Konto verloren, bevor das Tageslimit greift.",
        )


@app.post("/api/accounts", status_code=201)
def konto_anlegen(
    eingabe: KontoEingabe,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    werte = eingabe.model_dump()
    _pruefe_kontowerte(werte)

    konto = db.Account(
        user_id=nutzer.id,
        label=werte["label"].strip(),
        login=(werte["login"] or "").strip() or None,
        broker=(werte["broker"] or "").strip() or None,
        server=(werte["server"] or "").strip() or None,
        currency=werte["currency"].strip().upper() or "EUR",
        phase=db.KontoPhase(werte["phase"]),
        status=db.KontoStatus(werte["status"]),
        starting_balance=werte["starting_balance"],
        daily_loss_limit=werte["daily_loss_limit"],
        max_loss_limit=werte["max_loss_limit"],
        consistency_limit=werte["consistency_limit"],
        warn_threshold=werte["warn_threshold"],
        profit_target=werte["profit_target"],
    )
    session.add(konto)
    session.commit()
    session.refresh(konto)
    return konto_block(session, konto)


@app.patch("/api/accounts/{account_id}")
def konto_aendern(
    account_id: int,
    aenderung: KontoAenderung,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    konto = pruefe_konto(session, nutzer, account_id)
    gesetzt = aenderung.model_fields_set
    werte = {k: v for k, v in aenderung.model_dump().items() if k in gesetzt}

    # Beim Prüfen die *neuen* Werte gegen die vorhandenen halten: Wer nur
    # das Tageslimit ändert, muss trotzdem gegen den gespeicherten
    # Gesamtverlust geprüft werden.
    vollstaendig = {
        "daily_loss_limit": konto.daily_loss_limit,
        "max_loss_limit": konto.max_loss_limit,
        **werte,
    }
    _pruefe_kontowerte(vollstaendig)

    for feld, wert in werte.items():
        if feld == "phase":
            konto.phase = db.KontoPhase(wert)
        elif feld == "status":
            konto.status = db.KontoStatus(wert)
        elif feld in ("label", "currency"):
            konto.__setattr__(feld, (wert or "").strip() or konto.__getattribute__(feld))
        elif feld in ("login", "broker", "server"):
            konto.__setattr__(feld, (wert or "").strip() or None)
        else:
            konto.__setattr__(feld, wert)

    session.commit()
    session.refresh(konto)
    return konto_block(session, konto)


@app.delete("/api/accounts/{account_id}")
def konto_loeschen(
    account_id: int,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Löscht ein Konto -- aber nur ein leeres.

    Ein Konto mit Ausführungen zu löschen hiesse, Handelshistorie
    wegzuwerfen, die nirgends sonst steht. Ein verlorenes Challenge-Konto
    gehört auf `status: verloren`, nicht in den Papierkorb: Seine Trades
    sind die Lehre, für die man bezahlt hat.
    """
    konto = pruefe_konto(session, nutzer, account_id)

    anzahl = session.scalar(
        select(func.count()).select_from(db.Deal).where(db.Deal.account_id == konto.id)
    ) or 0
    if anzahl:
        raise HTTPException(
            409,
            f"Das Konto hat {anzahl} Ausführungen und wird nicht gelöscht. "
            "Ein abgeschlossenes Konto gehört auf 'archiviert' oder "
            "'verloren' -- seine Trades sind die Lehre, für die du bezahlt hast.",
        )

    # Was noch daran hängt, geht mit: Marken und Sync-Zustand haben ohne
    # das Konto keine Bedeutung.
    session.execute(
        delete(db.Zugangsmarke).where(db.Zugangsmarke.account_id == konto.id)
    )
    zustand = session.get(db.SyncState, konto.id)
    if zustand is not None:
        session.delete(zustand)
    session.delete(konto)
    session.commit()
    return {"status": "geloescht", "id": account_id}


def sync_block(zustand: db.SyncState | None) -> dict:
    """Der Herzschlag.

    Kein Detail, sondern die Statuszeile des Produkts: Ein stiller Ausfall
    der Anbindung darf niemals genauso aussehen wie "heute keine Trades".
    """
    if zustand is None or zustand.last_success_at is None:
        return {
            "state": "nie",
            "minutes_ago": None,
            "last_success": None,
            "last_error": None,
            "source": None,
        }

    letzte = zustand.last_success_at
    if letzte.tzinfo is None:
        letzte = letzte.replace(tzinfo=timezone.utc)
    minuten = int((datetime.now(timezone.utc) - letzte).total_seconds() // 60)

    if zustand.last_error:
        stand = "fehler"
    elif minuten > 180:
        stand = "still"
    elif minuten > 30:
        stand = "verzoegert"
    else:
        stand = "gesund"

    return {
        "state": stand,
        "minutes_ago": minuten,
        "last_success": letzte.isoformat(),
        "last_error": zustand.last_error,
        "source": zustand.source,
        "deals_imported": zustand.deals_imported,
    }


# ---------------------------------------------------------------------------
# Übersicht: Kennzahlen, Score, Regel-Puffer
# ---------------------------------------------------------------------------

def metrics_block(m: kern_metrics.Metrics) -> dict:
    return {
        "trade_count": m.trade_count,
        "wins": m.wins,
        "losses": m.losses,
        "scratches": m.scratches,
        "net_pnl": z(m.net_pnl),
        "gross_profit": z(m.gross_profit),
        "gross_loss": z(m.gross_loss),
        "total_costs": z(m.total_costs),
        "win_rate": z(m.win_rate),
        "profit_factor": z(m.profit_factor),
        "avg_win": z(m.avg_win),
        "avg_loss": z(m.avg_loss),
        "win_loss_ratio": z(m.win_loss_ratio),
        "expectancy": z(m.expectancy),
        "expectancy_r": z(m.expectancy_r),
        "max_drawdown": z(m.max_drawdown),
        "recovery_factor": z(m.recovery_factor),
        "consistency": z(m.consistency),
        "largest_win": z(m.largest_win),
        "largest_loss": z(m.largest_loss),
        "max_consecutive_wins": m.max_consecutive_wins,
        "max_consecutive_losses": m.max_consecutive_losses,
        "trading_days": m.trading_days,
        "trades_without_stop": m.trades_without_stop,
    }


def puffer_block(p: rules.Puffer) -> dict:
    return {
        "label": p.label,
        "used": z(p.verbraucht),
        "limit": z(p.limit),
        "remaining": z(p.rest),
        "ratio": z(p.anteil),
        "warn_at": z(p.warn_ab),
        "state": p.ampel,
        "measurable": p.messbar,
        "reason": p.grund,
    }


@app.get("/api/overview")
def overview(
    f: dict = Depends(filter_aus_query), session: Session = Depends(hole_session)
):
    """Alles, was das Dashboard in einem Zug braucht."""
    trades = trades_laden(session, **f)
    m = kern_metrics.compute(trades)
    s = kern_score.compute(m)

    konto = session.get(db.Account, f["account_id"]) if f["account_id"] else None
    stand = rules.bewerten(
        trades,
        daily_loss_limit=Decimal(str(konto.daily_loss_limit))
        if konto and konto.daily_loss_limit
        else None,
        max_loss_limit=Decimal(str(konto.max_loss_limit))
        if konto and konto.max_loss_limit
        else None,
        consistency_limit=Decimal(str(konto.consistency_limit))
        if konto and konto.consistency_limit
        else None,
        warn_ab=Decimal(str(konto.warn_threshold)) if konto else Decimal("0.8"),
    )

    # Equity-Kurve über die geschlossenen Trades, chronologisch.
    geschlossen = sorted(
        (t for t in trades if not t.is_open),
        key=lambda t: t.closed_at or t.opened_at,
    )
    kurve, laufend, hoch = [], Decimal(0), Decimal(0)
    for t in geschlossen:
        laufend += t.net_pnl
        hoch = max(hoch, laufend)
        kurve.append(
            {
                "t": (t.closed_at or t.opened_at).isoformat(),
                "equity": z(laufend),
                "drawdown": z(hoch - laufend),
            }
        )

    return {
        "metrics": metrics_block(m),
        "score": {
            "total": z(s.total),
            "parts": {k: z(v) for k, v in s.parts.items()},
            "missing": list(s.missing),
        },
        "rules": {
            "daily_loss": puffer_block(stand.tagesverlust),
            "max_loss": puffer_block(stand.gesamtverlust),
            "consistency": puffer_block(stand.konsistenz),
            "account_lost": stand.konto_verloren,
            "most_urgent": stand.dringendste.label,
        },
        "equity_curve": kurve,
        "sync": sync_block(
            session.get(db.SyncState, f["account_id"]) if f["account_id"] else None
        ),
    }


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def trade_block(zeile: db.Trade) -> dict:
    kern = trade_zu_kern(zeile)
    return {
        "id": zeile.id,
        "position_id": zeile.position_id,
        "symbol": zeile.symbol,
        # Die Stellenzahl gehört zum Preis wie die Währung zum Betrag.
        # Ohne sie setzt die Oberfläche jeden Kurs mit fünf Stellen --
        # und ein Index liest sich dann als "39.498,47676".
        "digits": instruments.nachkommastellen(zeile.symbol),
        "direction": zeile.direction,
        "opened_at": kern.opened_at.isoformat() if kern.opened_at else None,
        "closed_at": kern.closed_at.isoformat() if kern.closed_at else None,
        "duration_seconds": (
            int(kern.duration.total_seconds()) if kern.duration else None
        ),
        "volume": z(kern.volume),
        "exit_volume": z(kern.exit_volume),
        "avg_entry": z(kern.avg_entry),
        "avg_exit": z(kern.avg_exit),
        "gross_pnl": z(kern.gross_pnl),
        "costs": z(kern.costs),
        "net_pnl": z(kern.net_pnl),
        "initial_sl": z(kern.initial_sl),
        "risk_amount": z(kern.risk_amount),
        "r_multiple": z(kern.r_multiple),
        "outcome": kern.outcome.value,
        "is_open": kern.is_open,
        "partial": zeile.partial,
        "note": zeile.note,
        # Die Zuordnung war schon immer setzbar, kam aber nie zurück -- die
        # Oberfläche konnte ein Playbook auswählen und danach nicht mehr
        # sagen, welches dransteht.
        "playbook_id": zeile.playbook_id,
        "tags": [
            {"id": tt.tag.id, "label": tt.tag.label,
             "kind": tt.tag.kind.value if hasattr(tt.tag.kind, "value") else tt.tag.kind}
            for tt in zeile.tags
        ],
        # Nur die Antworten zum *zugeordneten* Playbook. Wer ein Playbook
        # wechselt, dessen alte Antworten bleiben stehen, zählen aber
        # nirgends mit -- sie beantworten Regeln, die für diesen Trade
        # nicht mehr gelten. Zurückgewechselt sind sie wieder da.
        "rule_checks": (
            [
                {"rule_id": c.rule_id, "checked": c.checked}
                for c in zeile.rule_checks
                if c.rule.playbook_id == zeile.playbook_id
            ]
            if zeile.playbook_id is not None
            else []
        ),
    }


@app.get("/api/trades")
def liste(
    f: dict = Depends(filter_aus_query),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    outcome: str | None = Query(None, description="win | loss | scratch"),
    session: Session = Depends(hole_session),
):
    frage = select(db.Trade)
    # Erst die Schranke, dann der Filter. Eine leere Liste heißt "keine
    # Konten" und muss nichts liefern -- nicht alles.
    if not f["account_ids"]:
        return {"total": 0, "limit": limit, "offset": offset, "trades": []}
    frage = frage.where(db.Trade.account_id.in_(f["account_ids"]))
    if f["account_id"]:
        frage = frage.where(db.Trade.account_id == f["account_id"])
    if f["von"]:
        frage = frage.where(db.Trade.opened_at >= f["von"])
    if f["bis"]:
        frage = frage.where(db.Trade.opened_at <= f["bis"])
    if f["symbol"]:
        frage = frage.where(db.Trade.symbol == f["symbol"])
    if f["direction"]:
        frage = frage.where(db.Trade.direction == f["direction"])
    if outcome == "win":
        frage = frage.where(db.Trade.net_pnl > 0)
    elif outcome == "loss":
        frage = frage.where(db.Trade.net_pnl < 0)
    elif outcome == "scratch":
        frage = frage.where(db.Trade.net_pnl == 0)

    gesamt = session.scalar(
        select(func.count()).select_from(frage.subquery())
    ) or 0

    zeilen = session.scalars(
        frage.order_by(db.Trade.opened_at.desc())
        .limit(limit)
        .offset(offset)
        # Ohne das eine Abfrage je Regel-Antwort: `trade_block` fragt jede
        # danach, zu welchem Playbook sie gehört. Bei 200 Trades mit je
        # acht Häkchen wären das 1.600 Abfragen für eine Seite.
        .options(selectinload(db.Trade.rule_checks).joinedload(db.TradeRuleCheck.rule))
    ).all()

    return {
        "total": gesamt,
        "limit": limit,
        "offset": offset,
        "trades": [trade_block(t) for t in zeilen],
    }


@app.get("/api/trades/{trade_id}")
def detail(
    trade_id: int,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    zeile = hole_eigenen_trade(session, nutzer, trade_id)

    ausfuehrungen = session.scalars(
        select(db.Deal)
        .where(
            db.Deal.account_id == zeile.account_id,
            db.Deal.position_id == zeile.position_id,
        )
        .order_by(db.Deal.time_utc)
    ).all()

    daten = trade_block(zeile)
    daten["executions"] = [
        {
            "ticket": d.ticket,
            "time": (
                d.time_utc if d.time_utc.tzinfo else d.time_utc.replace(tzinfo=timezone.utc)
            ).isoformat(),
            "type": d.type,
            "entry": d.entry,
            "volume": z(d.volume),
            "price": z(d.price),
            "profit": z(d.profit),
            "commission": z(d.commission),
            "swap": z(d.swap),
            "fee": z(d.fee),
        }
        for d in ausfuehrungen
    ]
    return daten


# ---------------------------------------------------------------------------
# Kalender
# ---------------------------------------------------------------------------

@app.get("/api/calendar")
def kalender(
    year: int,
    month: int,
    f: dict = Depends(filter_aus_query),
    session: Session = Depends(hole_session),
):
    """Tageswerte eines Monats plus Wochensummen.

    Das Raster ist der eigentliche Wert des Kalenders: Man sieht den Monat
    als Muster, nicht als Nachschlagewerk. Deshalb liefert die API auch
    Tage ohne Handel mit -- eine Lücke im Raster ist eine Information.
    """
    if not 1 <= month <= 12:
        raise HTTPException(400, "Monat muss zwischen 1 und 12 liegen")

    account_id = f["account_id"]
    erlaubte = f["account_ids"]

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    ende = datetime(
        year + (month == 12), (month % 12) + 1, 1, tzinfo=timezone.utc
    ) - timedelta(microseconds=1)

    trades = trades_laden(
        session,
        account_id=account_id,
        von=start,
        bis=ende,
        account_ids=erlaubte,
    )
    geschlossen = [t for t in trades if not t.is_open]

    pro_tag = daily_pnl(geschlossen)
    anzahl_tag: dict[date, int] = {}
    gewinner_tag: dict[date, int] = {}
    for t in geschlossen:
        tag = (t.closed_at or t.opened_at).date()
        anzahl_tag[tag] = anzahl_tag.get(tag, 0) + 1
        if t.outcome is Outcome.WIN:
            gewinner_tag[tag] = gewinner_tag.get(tag, 0) + 1

    tage = []
    zeiger = start.date()
    letzter = ende.date()
    while zeiger <= letzter:
        ergebnis = pro_tag.get(zeiger)
        anzahl = anzahl_tag.get(zeiger, 0)
        tage.append(
            {
                "date": zeiger.isoformat(),
                "weekday": zeiger.weekday(),
                "iso_week": zeiger.isocalendar().week,
                "pnl": z(ergebnis) if anzahl else None,
                "trades": anzahl,
                "wins": gewinner_tag.get(zeiger, 0),
                "win_rate": (
                    gewinner_tag.get(zeiger, 0) / anzahl if anzahl else None
                ),
                "weekend": zeiger.weekday() >= 5,
            }
        )
        zeiger += timedelta(days=1)

    wochen: dict[int, dict] = {}
    for tag in tage:
        w = wochen.setdefault(
            tag["iso_week"], {"iso_week": tag["iso_week"], "pnl": 0.0, "trades": 0, "days": 0}
        )
        if tag["trades"]:
            w["pnl"] += tag["pnl"] or 0.0
            w["trades"] += tag["trades"]
            w["days"] += 1

    monatswert = sum(t["pnl"] or 0.0 for t in tage if t["trades"])
    mit_handel = [t for t in tage if t["trades"]]

    return {
        "year": year,
        "month": month,
        "days": tage,
        "weeks": sorted(wochen.values(), key=lambda w: w["iso_week"]),
        "month_pnl": monatswert,
        "trading_days": len(mit_handel),
        "best_day": max(mit_handel, key=lambda t: t["pnl"], default=None),
        "worst_day": min(mit_handel, key=lambda t: t["pnl"], default=None),
    }


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

DIMENSIONEN = {
    "weekday": lambda t: str((t.closed_at or t.opened_at).weekday()),
    "hour": lambda t: f"{(t.closed_at or t.opened_at).hour:02d}",
    "month": lambda t: (t.closed_at or t.opened_at).strftime("%Y-%m"),
    "symbol": lambda t: instruments.normalisiere(t.symbol),
    "direction": lambda t: t.direction.value,
    "duration": lambda t: _dauerklasse(t),
    "volume": lambda t: _volumenklasse(t),
}


def _dauerklasse(t) -> str:
    if t.duration is None:
        return "offen"
    minuten = t.duration.total_seconds() / 60
    for grenze, label in ((15, "0-15m"), (60, "15-60m"), (240, "1-4h"), (1440, "4-24h")):
        if minuten < grenze:
            return label
    return ">1T"


def _volumenklasse(t) -> str:
    v = float(t.volume)
    for grenze, label in ((0.3, "<0.3"), (0.6, "0.3-0.6"), (1.1, "0.6-1.1"), (2.1, "1.1-2.1")):
        if v < grenze:
            return label
    return ">2.1"


# Dimensionen, bei denen ein Trade in *mehrere* Gruppen fällt.
#
# Tags sind der Grund, warum es diese zweite Sorte gibt: Ein Trade kann
# zwei Setups tragen oder keins. Damit ist die Gruppierung keine
# Aufteilung mehr, und zwei Dinge müssen ausdrücklich geregelt sein:
#
# * Die Summe der Gruppengrößen ist größer als die Zahl der Trades. Die
#   Antwort sagt das mit `overlapping`, damit die Oberfläche nicht den
#   Eindruck einer Aufteilung erweckt.
# * Trades ohne Tag bekommen eine eigene Gruppe. Ließe man sie weg,
#   beschriebe der Report nur den beschrifteten Teil -- sähe aber aus wie
#   eine Aussage über alle. Das ist die stillste Art, sich selbst zu
#   belügen: "Breakout verdient Geld" stimmt dann vielleicht nur, weil
#   die schlechten Breakouts nie getaggt wurden.

def _tag_schluessel(zeile, art: str | None = None) -> list[str]:
    marken = [
        tt.tag for tt in zeile.tags
        if art is None or (
            tt.tag.kind.value if hasattr(tt.tag.kind, "value") else tt.tag.kind
        ) == art
    ]
    if not marken:
        return ["ohne Tag"] if art is None else [f"ohne {art.capitalize()}"]
    return [m.label for m in marken]


MEHRFACH_DIMENSIONEN = {
    "tag": lambda z: _tag_schluessel(z),
    "setup": lambda z: _tag_schluessel(z, "setup"),
    "fehler": lambda z: _tag_schluessel(z, "fehler"),
    "emotion": lambda z: _tag_schluessel(z, "emotion"),
}


# Vor `/api/reports/{dimension}` eingehängt -- FastAPI nimmt die erste
# passende Route, und der Platzhalter darunter schluckt sonst jeden Namen.


@app.get("/api/reports/regeltreue")
def regeltreue(
    f: dict = Depends(filter_aus_query),
    min_sample: int = Query(8, ge=1, description="Mindestanzahl je Gruppe"),
    session: Session = Depends(hole_session),
):
    """Was die eigenen Regeln wert sind.

    Zwei Fragen, und die zweite ist die eigentliche:

    1. Wie oft halte ich mich an welche Regel?
    2. **Verdiene ich mehr, wenn ich mich daran halte?** Eine Regel, deren
       Bruch nichts kostet, ist keine Regel, sondern eine Angewohnheit.

    Die Einteilung ist mit Absicht streng:

    * **gebrochen** -- mindestens eine abhakbare Regel ausdrücklich mit
      Nein beantwortet. Ein bestätigter Bruch bleibt ein Bruch, auch wenn
      der Rest der Liste offen ist.
    * **eingehalten** -- *alle* abhakbaren Regeln beantwortet, keine
      gebrochen. Nicht "keine gebrochene gefunden": Sonst zählte ein
      Trade, bei dem man nur die bequemen drei Häkchen gesetzt hat, als
      sauber -- und die Quote misst dann Fleiss beim Abhaken.
    * **offen** -- der Rest. Er steht getrennt in der Antwort und geht in
      keinen Vergleich ein; ein Trade, den man noch nicht durchgegangen
      ist, ist keine Aussage über Disziplin.

    Alles hier ist selbstberichtet. Aus MT5 kommt keine dieser Antworten.
    """
    paare = [
        (zeile, trade_zu_kern(zeile))
        for zeile in zeilen_laden(session, **f)
        if zeile.playbook_id is not None
    ]
    paare = [(z_, k) for z_, k in paare if not k.is_open]

    buecher: dict[int, db.Playbook] = {}
    for zeile, _ in paare:
        if zeile.playbook_id not in buecher:
            buch = session.get(db.Playbook, zeile.playbook_id)
            if buch is not None:
                buecher[zeile.playbook_id] = buch

    eingehalten: list = []
    gebrochen: list = []
    offen: list = []

    # Je Regel: beantwortet, gehalten -- und was der Bruch gekostet hat.
    je_regel: dict[int, dict] = {}

    for zeile, kern in paare:
        buch = buecher.get(zeile.playbook_id)
        if buch is None:
            continue
        pruefbar = {r.id for r in buch.rules if r.checkable}
        antworten = {
            c.rule_id: c.checked
            for c in zeile.rule_checks
            if c.rule_id in pruefbar
        }

        for rule_id, gehalten in antworten.items():
            eintrag = je_regel.setdefault(
                rule_id, {"gehalten": [], "verletzt": []}
            )
            eintrag["gehalten" if gehalten else "verletzt"].append(kern)

        if any(not v for v in antworten.values()):
            gebrochen.append(kern)
        elif pruefbar and len(antworten) == len(pruefbar):
            eingehalten.append(kern)
        else:
            offen.append(kern)

    # Dieselben Felder wie bei den übrigen Rubriken -- die Oberfläche
    # zeichnet beide mit demselben Bauteil.
    def gruppe(name: str, menge: list) -> dict:
        m = kern_metrics.compute(menge)
        return {
            "key": name,
            "trades": m.trade_count,
            "below_min_sample": m.trade_count < min_sample,
            "net_pnl": z(m.net_pnl),
            "win_rate": z(m.win_rate),
            "profit_factor": z(m.profit_factor),
            "expectancy": z(m.expectancy),
            "expectancy_r": z(m.expectancy_r),
            "avg_win": z(m.avg_win),
            "avg_loss": z(m.avg_loss),
            "wins": m.wins,
            "losses": m.losses,
        }

    regeln = []
    for buch in sorted(buecher.values(), key=lambda b: b.name):
        for regel in sorted(buch.rules, key=lambda r: r.sort_order):
            if not regel.checkable:
                continue
            eintrag = je_regel.get(regel.id, {"gehalten": [], "verletzt": []})
            gehalten, verletzt = eintrag["gehalten"], eintrag["verletzt"]
            beantwortet = len(gehalten) + len(verletzt)
            regeln.append(
                {
                    "rule_id": regel.id,
                    "playbook_id": buch.id,
                    "playbook": buch.name,
                    "group": regel.group_label,
                    "text": regel.text,
                    "answered": beantwortet,
                    "kept": len(gehalten),
                    "broken": len(verletzt),
                    # Ohne eine einzige Antwort gibt es keine Quote. Null
                    # wäre hier gelogen -- das hiesse "nie eingehalten".
                    "rate": (
                        z(Decimal(len(gehalten)) / Decimal(beantwortet))
                        if beantwortet
                        else None
                    ),
                    "below_min_sample": beantwortet < min_sample,
                    "pnl_kept": z(kern_metrics.compute(gehalten).net_pnl),
                    "pnl_broken": z(kern_metrics.compute(verletzt).net_pnl),
                }
            )

    return {
        "min_sample": min_sample,
        "groups": [
            gruppe("eingehalten", eingehalten),
            gruppe("gebrochen", gebrochen),
        ],
        "unanswered": len(offen),
        "total_trades": len(paare),
        "rules": regeln,
        # Kein Trade zählt in zwei Gruppen -- anders als bei den Tags.
        "overlapping": False,
        "self_reported": True,
    }


@app.get("/api/reports/{dimension}")
def report(
    dimension: str,
    f: dict = Depends(filter_aus_query),
    min_sample: int = Query(8, ge=1, description="Mindestanzahl je Gruppe"),
    session: Session = Depends(hole_session),
):
    """Gruppiert die Trades und rechnet je Gruppe die Kennzahlen.

    `min_sample` ist keine Kosmetik: Eine Gruppe mit vier Trades trägt
    keine Aussage. Sie wird geliefert, aber als `below_min_sample`
    gekennzeichnet, damit die Oberfläche sie dämpfen und beschriften kann
    -- „Dienstag sieht am besten aus, bei vier Trades ist das Rauschen".
    """
    mehrfach = dimension in MEHRFACH_DIMENSIONEN
    if dimension not in DIMENSIONEN and not mehrfach:
        verfuegbar = list(DIMENSIONEN) + list(MEHRFACH_DIMENSIONEN)
        raise HTTPException(
            400, f"Unbekannte Dimension. Verfügbar: {', '.join(verfuegbar)}"
        )

    gruppen: dict[str, list] = {}

    if mehrfach:
        # Über die Zeilen, weil Tags am Trade des Nutzers hängen und
        # nicht am gerechneten Kern.
        schluessel_mehrfach = MEHRFACH_DIMENSIONEN[dimension]
        paare = [
            (zeile, trade_zu_kern(zeile)) for zeile in zeilen_laden(session, **f)
        ]
        trades = [kern for _, kern in paare if not kern.is_open]
        for zeile, kern in paare:
            if kern.is_open:
                continue
            for name in schluessel_mehrfach(zeile):
                gruppen.setdefault(name, []).append(kern)
    else:
        schluessel = DIMENSIONEN[dimension]
        trades = [t for t in trades_laden(session, **f) if not t.is_open]
        for t in trades:
            gruppen.setdefault(schluessel(t), []).append(t)

    heraus = []
    for name, menge in gruppen.items():
        m = kern_metrics.compute(menge)
        heraus.append(
            {
                "key": name,
                "trades": m.trade_count,
                "below_min_sample": m.trade_count < min_sample,
                "net_pnl": z(m.net_pnl),
                "win_rate": z(m.win_rate),
                "profit_factor": z(m.profit_factor),
                "expectancy": z(m.expectancy),
                "expectancy_r": z(m.expectancy_r),
                "avg_win": z(m.avg_win),
                "avg_loss": z(m.avg_loss),
                "wins": m.wins,
                "losses": m.losses,
            }
        )

    heraus.sort(key=lambda g: g["key"])
    return {
        "dimension": dimension,
        "min_sample": min_sample,
        "groups": heraus,
        "total_trades": len(trades),
        # Bei Tags zählt ein Trade in mehreren Gruppen. Die Oberfläche
        # muss das sagen können -- sonst rechnet der Leser die Gruppen
        # zusammen und wundert sich über die Summe.
        "overlapping": mehrfach,
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class ImportAnfrage(BaseModel):
    account_id: int
    content: str
    mapping: dict[str, str] | None = None


@app.post("/api/import/csv")
def csv_import(
    anfrage: ImportAnfrage,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Nimmt einen Broker-Export entgegen.

    Antwortet mit dem vollständigen Bericht -- auch mit dem, was *nicht*
    geklappt hat. Ein Import, der stillschweigend Zeilen wegwirft, ist
    gefährlicher als einer, der abbricht: Die Summe stimmt dann nicht mehr
    und niemand weiß warum.
    """
    from ..db.repository import aufnehmen

    # Vor allem anderen: Gehört das Konto überhaupt diesem Nutzer? Ohne
    # die Prüfung könnte jeder Angemeldete in fremde Konten importieren.
    pruefe_konto(session, nutzer, anfrage.account_id)

    bericht = importiere(
        anfrage.content, account_id=str(anfrage.account_id), zuordnung=anfrage.mapping
    )

    if not bericht.erfolgreich:
        return {
            "ok": False,
            "mapping": bericht.zuordnung,
            "missing_fields": bericht.fehlende_pflichtfelder,
            "rows": bericht.zeilen_gesamt,
            "skipped": bericht.zeilen_uebersprungen,
            "problems": bericht.probleme[:50],
            "summary": bericht.zusammenfassung(),
        }

    neu, anzahl = aufnehmen(session, anfrage.account_id, bericht.deals, source="csv")
    return {
        "ok": True,
        "mapping": bericht.zuordnung,
        "rows": bericht.zeilen_gesamt,
        "skipped": bericht.zeilen_uebersprungen,
        "deals_new": neu,
        "trades_total": anzahl,
        "problems": bericht.probleme[:50],
        "summary": bericht.zusammenfassung(),
    }


@app.get("/api/symbols")
def symbole(
    f: dict = Depends(filter_aus_query), session: Session = Depends(hole_session)
):
    if not f["account_ids"]:
        return []
    frage = select(db.Trade.symbol).distinct().where(
        db.Trade.account_id.in_(f["account_ids"])
    )
    if f["account_id"]:
        frage = frage.where(db.Trade.account_id == f["account_id"])
    return sorted(session.scalars(frage).all())


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------
#
# Ab hier wird die App vom Betrachter zum Journal. Drei Festlegungen, die
# für alles darunter gelten:
#
# * **PATCH ändert nur, was dasteht.** Ein weggelassenes Feld bleibt, wie
#   es war; ein ausdrückliches `null` löscht. Ohne diese Unterscheidung
#   könnte die Oberfläche keine Notiz speichern, ohne zugleich das
#   Playbook zu überschreiben.
# * **Die Tag-Liste wird als Ganzes gesetzt, nicht einzeln ergänzt.** Ein
#   PUT mit der vollständigen Liste ist wiederholbar: Zweimal geschickt
#   ergibt zweimal dasselbe. Bei getrenntem Hinzufügen und Entfernen
#   hinge das Ergebnis an der Reihenfolge der Aufrufe.
# * **Geschrieben wird nur, was der Nutzer geschrieben hat.** Kein
#   Endpunkt hier fasst eine gerechnete Größe an. Die kommen aus den
#   Deals und werden bei jedem Neuaufbau überschrieben -- eine Änderung
#   daran wäre beim nächsten Abgleich lautlos wieder weg.


class TradeAenderung(BaseModel):
    """Was an einem Trade von Hand änderbar ist."""

    note: str | None = None
    playbook_id: int | None = None


def _benutzer_von(session: Session, trade: db.Trade) -> int:
    """Der Besitzer eines Trades, über sein Konto.

    Solange es keine Anmeldung gibt, ist das der einzige belastbare Weg
    zu einer Nutzer-ID. Tags hängen am Nutzer, nicht am Konto -- wer sein
    Challenge-Konto verliert und ein neues bekommt, will seine
    Setup-Namen behalten.
    """
    konto = session.get(db.Account, trade.account_id)
    if konto is None:
        raise HTTPException(500, "Trade ohne Konto")
    return konto.user_id


@app.patch("/api/trades/{trade_id}")
def trade_aendern(
    trade_id: int,
    aenderung: TradeAenderung,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Notiz und Playbook-Zuordnung setzen.

    Nur die Felder, die im Rumpf stehen. `note: null` löscht die Notiz,
    ein fehlendes `note` lässt sie stehen.
    """
    zeile = hole_eigenen_trade(session, nutzer, trade_id)

    gesetzt = aenderung.model_fields_set

    if "note" in gesetzt:
        text = (aenderung.note or "").strip()
        if len(text) > 20_000:
            raise HTTPException(400, "Notiz zu lang (höchstens 20.000 Zeichen)")
        # Leer heißt "keine Notiz", nicht "eine leere Notiz". Sonst
        # unterschieden sich zwei Zustände, die für den Nutzer derselbe sind.
        zeile.note = text or None

    if "playbook_id" in gesetzt:
        if aenderung.playbook_id is not None:
            buch = session.get(db.Playbook, aenderung.playbook_id)
            if buch is None:
                raise HTTPException(404, "Playbook nicht gefunden")
            if buch.user_id != _benutzer_von(session, zeile):
                raise HTTPException(403, "Playbook gehört zu einem anderen Nutzer")
        zeile.playbook_id = aenderung.playbook_id

    session.commit()
    session.refresh(zeile)
    return trade_block(zeile)


class TagEingabe(BaseModel):
    label: str
    kind: str = "setup"


class TagListe(BaseModel):
    tags: list[TagEingabe]


@app.put("/api/trades/{trade_id}/tags")
def trade_tags_setzen(
    trade_id: int,
    liste: TagListe,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Setzt die Tags eines Trades auf genau diese Liste.

    Unbekannte Bezeichnungen werden angelegt, bekannte wiederverwendet --
    sonst stünde dasselbe Setup unter zwei IDs im Report. Doppelte in der
    Eingabe fallen zusammen.
    """
    zeile = hole_eigenen_trade(session, nutzer, trade_id)

    if len(liste.tags) > 20:
        raise HTTPException(400, "Höchstens 20 Tags je Trade")

    user_id = _benutzer_von(session, zeile)

    gewuenscht: list[tuple[str, db.TagArt]] = []
    gesehen: set[tuple[str, db.TagArt]] = set()
    for eingabe in liste.tags:
        text = eingabe.label.strip()
        if not text:
            continue
        if len(text) > 80:
            raise HTTPException(400, f"Tag zu lang: {text[:40]}…")
        try:
            art = db.TagArt(eingabe.kind)
        except ValueError:
            erlaubt = ", ".join(a.value for a in db.TagArt)
            raise HTTPException(400, f"Unbekannte Tag-Art: {eingabe.kind} ({erlaubt})")
        schluessel = (text, art)
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        gewuenscht.append(schluessel)

    ids: list[int] = []
    for text, art in gewuenscht:
        marke = session.scalars(
            select(db.Tag).where(
                db.Tag.user_id == user_id,
                db.Tag.label == text,
                db.Tag.kind == art,
            )
        ).first()
        if marke is None:
            marke = db.Tag(user_id=user_id, label=text, kind=art)
            session.add(marke)
            session.flush()
        ids.append(marke.id)

    session.execute(delete(db.TradeTag).where(db.TradeTag.trade_id == trade_id))
    for tag_id in ids:
        session.add(db.TradeTag(trade_id=trade_id, tag_id=tag_id))

    session.commit()
    session.refresh(zeile)
    return trade_block(zeile)


@app.get("/api/tags")
def tags(
    account_id: int | None = Query(None),
    ungenutzte: bool = Query(
        False, description="Auch Tags mitliefern, die an keinem Trade hängen"
    ),
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Die bereits vergebenen Tags -- als Vorschläge beim Tippen.

    Mit Anzahl, damit die häufigen oben stehen. Wer bei jedem Trade neu
    tippt, produziert "Breakout", "breakout" und "Break-out" und hat am
    Ende drei Zeilen im Report, wo eine hingehört.

    Tags, die an keinem Trade mehr hängen, fehlen hier. Das ist Absicht:
    Die Liste ist zum Wiederverwenden da, und an einer Bezeichnung mit
    null Trades gibt es nichts wiederzuverwenden. Sonst sammelte sich
    dort jeder Tippfehler, den man je vergeben und wieder entfernt hat --
    nach ein paar Monaten stünden dutzende tote Einträge unter jedem
    Trade. Gelöscht wird trotzdem nichts: Wer die Bezeichnung erneut
    tippt, bekommt dieselbe Marke wieder, und die alte Zuordnung im
    Report bleibt unberührt.
    """
    # Immer der angemeldete Nutzer -- vorher hing das am `account_id`, und
    # ohne den kamen die Tags *aller* Nutzer zurück.
    if account_id:
        pruefe_konto(session, nutzer, account_id)
    user_id = nutzer.id

    frage = (
        select(db.Tag, func.count(db.TradeTag.trade_id))
        .outerjoin(db.TradeTag, db.TradeTag.tag_id == db.Tag.id)
        .group_by(db.Tag.id)
        .order_by(func.count(db.TradeTag.trade_id).desc(), db.Tag.label)
    )
    if user_id is not None:
        frage = frage.where(db.Tag.user_id == user_id)
    if not ungenutzte:
        frage = frage.having(func.count(db.TradeTag.trade_id) > 0)

    return [
        {
            "id": marke.id,
            "label": marke.label,
            "kind": marke.kind.value if hasattr(marke.kind, "value") else marke.kind,
            "count": anzahl,
        }
        for marke, anzahl in session.execute(frage).all()
    ]


class JournalEingabe(BaseModel):
    body: str = ""
    mood: int | None = None


@app.get("/api/journal/{tag}")
def journal_lesen(
    tag: str,
    account_id: int = Query(...),
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Die Tagesnotiz. Fehlt sie, kommt eine leere zurück, kein 404.

    Ein fehlender Eintrag ist kein Fehler -- die meisten Tage haben
    keinen. Die Oberfläche soll ein leeres Feld zeigen können, ohne
    vorher einen Fehlerfall behandeln zu müssen.
    """
    try:
        datum = date.fromisoformat(tag)
    except ValueError:
        raise HTTPException(400, f"Datum nicht lesbar: {tag}")

    pruefe_konto(session, nutzer, account_id)

    eintrag = session.scalars(
        select(db.JournalEntry).where(
            db.JournalEntry.account_id == account_id,
            db.JournalEntry.entry_date == datum,
        )
    ).first()

    if eintrag is None:
        return {"date": tag, "body": "", "mood": None, "updated_at": None}
    return {
        "date": tag,
        "body": eintrag.body,
        "mood": eintrag.mood,
        "updated_at": (
            eintrag.updated_at.isoformat() if eintrag.updated_at else None
        ),
    }


@app.put("/api/journal/{tag}")
def journal_schreiben(
    tag: str,
    eingabe: JournalEingabe,
    account_id: int = Query(...),
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Tagesnotiz und Stimmung setzen."""
    try:
        datum = date.fromisoformat(tag)
    except ValueError:
        raise HTTPException(400, f"Datum nicht lesbar: {tag}")

    pruefe_konto(session, nutzer, account_id)

    text = eingabe.body.strip()
    if len(text) > 50_000:
        raise HTTPException(400, "Eintrag zu lang (höchstens 50.000 Zeichen)")
    if eingabe.mood is not None and not 1 <= eingabe.mood <= 5:
        raise HTTPException(400, "Stimmung liegt zwischen 1 und 5")

    eintrag = session.scalars(
        select(db.JournalEntry).where(
            db.JournalEntry.account_id == account_id,
            db.JournalEntry.entry_date == datum,
        )
    ).first()

    if eintrag is None:
        eintrag = db.JournalEntry(account_id=account_id, entry_date=datum)
        session.add(eintrag)

    eintrag.body = text
    eintrag.mood = eingabe.mood
    eintrag.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(eintrag)

    return {
        "date": tag,
        "body": eintrag.body,
        "mood": eintrag.mood,
        "updated_at": eintrag.updated_at.isoformat() if eintrag.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Playbooks
# ---------------------------------------------------------------------------
#
# Ein Playbook ist die schriftliche Fassung dessen, was man zu handeln
# behauptet. Es lohnt nur, wenn beides möglich ist: es festzuhalten und
# hinterher je Trade zu beantworten, ob man sich daran gehalten hat.
#
# Zwei Festlegungen, die alles darunter tragen:
#
# * **Regeln werden geändert, nicht ersetzt.** Ein `PUT` auf die Regelliste
#   führt Einträge mit `id` fort und legt nur die ohne neu an. Würde die
#   Liste jedes Mal gelöscht und neu geschrieben, verlöre jede Regel bei
#   jeder Tippfehlerkorrektur ihre ID -- und mit ihr sämtliche Antworten,
#   die je an ihr hingen.
# * **Antworten gehen nicht beiläufig verloren.** Eine Regel, an der
#   Antworten hängen, verschwindet nur auf ausdrückliche Ansage. Sonst
#   löschte ein unbedachtes Streichen die halbe Regeltreue-Statistik.


def regel_block(r: db.PlaybookRule) -> dict:
    return {
        "id": r.id,
        "group": r.group_label,
        "text": r.text,
        "checkable": r.checkable,
    }


def playbook_block(session: Session, b: db.Playbook) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "description": b.description,
        "rules": [regel_block(r) for r in sorted(b.rules, key=lambda r: r.sort_order)],
        # Wie viele Trades daran hängen -- die Oberfläche entscheidet
        # damit, ob sie das Löschen überhaupt anbietet.
        "trade_count": session.scalar(
            select(func.count())
            .select_from(db.Trade)
            .where(db.Trade.playbook_id == b.id)
        )
        or 0,
    }


def hole_eigenes_playbook(
    session: Session, nutzer: db.User, playbook_id: int
) -> db.Playbook:
    """Ein Playbook, aber nur das eigene.

    404 auch dann, wenn es fremd ist: Ein 403 verriete, dass es die ID
    gibt.
    """
    buch = session.get(db.Playbook, playbook_id)
    if buch is None or buch.user_id != nutzer.id:
        raise HTTPException(404, "Playbook nicht gefunden")
    return buch


class RegelEingabe(BaseModel):
    """Eine Regel in der Liste.

    `id` ist da, wenn die Regel schon existiert -- dann wird sie geändert
    statt neu angelegt, und ihre Antworten bleiben ihr erhalten.
    """

    id: int | None = None
    group: str = "Allgemein"
    text: str
    checkable: bool = True


class PlaybookEingabe(BaseModel):
    name: str
    description: str | None = None
    rules: list[RegelEingabe] = []


class PlaybookAenderung(BaseModel):
    name: str | None = None
    description: str | None = None


def _pruefe_regeln(regeln: list[RegelEingabe]) -> None:
    if len(regeln) > 60:
        raise HTTPException(400, "Höchstens 60 Regeln je Playbook")
    for r in regeln:
        if not r.text.strip():
            raise HTTPException(400, "Eine Regel ohne Text sagt nichts")
        if len(r.text) > 500:
            raise HTTPException(400, f"Regel zu lang: {r.text[:40]}…")
        if len(r.group) > 120:
            raise HTTPException(400, f"Gruppenname zu lang: {r.group[:40]}…")


def _pruefe_namen(name: str) -> str:
    text = name.strip()
    if not text:
        raise HTTPException(400, "Das Playbook braucht einen Namen")
    if len(text) > 120:
        raise HTTPException(400, "Name zu lang (höchstens 120 Zeichen)")
    return text


@app.get("/api/playbooks")
def playbooks(
    account_id: int | None = Query(None),
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Die Playbooks samt Regeln -- für die Auswahl am Trade."""
    if account_id:
        pruefe_konto(session, nutzer, account_id)
    frage = (
        select(db.Playbook)
        .where(db.Playbook.user_id == nutzer.id)
        .order_by(db.Playbook.name)
    )
    return [playbook_block(session, b) for b in session.scalars(frage).all()]


@app.post("/api/playbooks", status_code=201)
def playbook_anlegen(
    eingabe: PlaybookEingabe,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Ein neues Playbook, gleich mit seinen Regeln."""
    name = _pruefe_namen(eingabe.name)
    _pruefe_regeln(eingabe.rules)

    buch = db.Playbook(
        user_id=nutzer.id,
        name=name,
        description=(eingabe.description or "").strip() or None,
    )
    session.add(buch)
    session.flush()

    for i, r in enumerate(eingabe.rules):
        session.add(
            db.PlaybookRule(
                playbook_id=buch.id,
                group_label=r.group.strip() or "Allgemein",
                text=r.text.strip(),
                checkable=r.checkable,
                sort_order=i,
            )
        )

    session.commit()
    session.refresh(buch)
    return playbook_block(session, buch)


@app.patch("/api/playbooks/{playbook_id}")
def playbook_aendern(
    playbook_id: int,
    aenderung: PlaybookAenderung,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Name und Beschreibung. Die Regeln haben ihren eigenen Endpunkt."""
    buch = hole_eigenes_playbook(session, nutzer, playbook_id)
    gesetzt = aenderung.model_fields_set

    if "name" in gesetzt:
        buch.name = _pruefe_namen(aenderung.name or "")
    if "description" in gesetzt:
        text = (aenderung.description or "").strip()
        if len(text) > 5_000:
            raise HTTPException(400, "Beschreibung zu lang (höchstens 5.000 Zeichen)")
        buch.description = text or None

    session.commit()
    session.refresh(buch)
    return playbook_block(session, buch)


@app.put("/api/playbooks/{playbook_id}/regeln")
def playbook_regeln_setzen(
    playbook_id: int,
    liste: list[RegelEingabe],
    antworten_verwerfen: bool = Query(
        False,
        description="Regeln auch dann streichen, wenn Antworten daran hängen",
    ),
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Setzt die Regelliste auf genau diese Reihenfolge.

    Einträge mit `id` werden fortgeführt, Einträge ohne neu angelegt, und
    was fehlt, wird gestrichen. Die Reihenfolge in der Liste ist die
    Reihenfolge auf dem Bildschirm.

    Streichen ist der heikle Teil: An einer Regel können Antworten von
    Dutzenden Trades hängen, und die stehen nirgends sonst. Wer eine
    solche Regel entfernt, bekommt deshalb zuerst ein 409 mit der Zahl
    der betroffenen Antworten und muss ausdrücklich zustimmen.
    """
    buch = hole_eigenes_playbook(session, nutzer, playbook_id)
    _pruefe_regeln(liste)

    vorhanden = {r.id: r for r in buch.rules}

    # Eine fremde ID hier wäre entweder ein Fehler der Oberfläche oder ein
    # Versuch, eine fremde Regel unter das eigene Playbook zu hängen.
    for r in liste:
        if r.id is not None and r.id not in vorhanden:
            raise HTTPException(404, f"Regel {r.id} gehört nicht zu diesem Playbook")

    behalten = {r.id for r in liste if r.id is not None}
    zu_streichen = [r for r in buch.rules if r.id not in behalten]

    if zu_streichen:
        betroffen = (
            session.scalar(
                select(func.count())
                .select_from(db.TradeRuleCheck)
                .where(db.TradeRuleCheck.rule_id.in_([r.id for r in zu_streichen]))
            )
            or 0
        )
        if betroffen and not antworten_verwerfen:
            raise HTTPException(
                409,
                f"An den gestrichenen Regeln hängen {betroffen} Antworten. "
                "Zum Streichen ausdrücklich bestätigen.",
            )
        session.execute(
            delete(db.TradeRuleCheck).where(
                db.TradeRuleCheck.rule_id.in_([r.id for r in zu_streichen])
            )
        )
        for r in zu_streichen:
            session.delete(r)

    for i, eingabe in enumerate(liste):
        if eingabe.id is None:
            session.add(
                db.PlaybookRule(
                    playbook_id=buch.id,
                    group_label=eingabe.group.strip() or "Allgemein",
                    text=eingabe.text.strip(),
                    checkable=eingabe.checkable,
                    sort_order=i,
                )
            )
            continue
        regel = vorhanden[eingabe.id]
        regel.group_label = eingabe.group.strip() or "Allgemein"
        regel.text = eingabe.text.strip()
        regel.checkable = eingabe.checkable
        regel.sort_order = i

    session.commit()
    session.refresh(buch)
    return playbook_block(session, buch)


@app.delete("/api/playbooks/{playbook_id}")
def playbook_loeschen(
    playbook_id: int,
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Löscht ein Playbook, an dem kein Trade mehr hängt.

    Hängen welche daran, kommt 409 statt einer stillen Entkopplung: Die
    Zuordnung ist eine Aussage über vergangene Trades, und die verschwände
    hier mit.
    """
    buch = hole_eigenes_playbook(session, nutzer, playbook_id)

    anzahl = (
        session.scalar(
            select(func.count())
            .select_from(db.Trade)
            .where(db.Trade.playbook_id == playbook_id)
        )
        or 0
    )
    if anzahl:
        raise HTTPException(
            409,
            f"An diesem Playbook hängen {anzahl} Trades. "
            "Erst dort abwählen, dann löschen.",
        )

    ids = [r.id for r in buch.rules]
    if ids:
        session.execute(
            delete(db.TradeRuleCheck).where(db.TradeRuleCheck.rule_id.in_(ids))
        )
    session.delete(buch)
    session.commit()
    return {"status": "geloescht", "id": playbook_id}


class RegelAntwort(BaseModel):
    rule_id: int
    checked: bool


@app.put("/api/trades/{trade_id}/regeln")
def trade_regeln_setzen(
    trade_id: int,
    antworten: list[RegelAntwort],
    nutzer: db.User = Depends(aktueller_nutzer),
    session: Session = Depends(hole_session),
):
    """Setzt die Regel-Antworten eines Trades auf genau diese Liste.

    Wie bei den Tags: die ganze Liste, nicht einzelne Häkchen. Zweimal
    geschickt ergibt zweimal dasselbe.

    Was nicht in der Liste steht, gilt als **unbeantwortet** und wird
    entfernt -- nicht als "nicht eingehalten". Das ist der Unterschied,
    an dem die ganze Kennzahl hängt: Ein Trade, den man noch nicht
    durchgegangen ist, darf die Regeltreue nicht drücken.

    Beantwortbar sind nur Regeln des Playbooks, das an diesem Trade
    hängt. Ein Häkchen an einer Regel aus einem anderen Playbook wäre
    eine Antwort auf eine Frage, die für diesen Trade nie gestellt wurde.
    """
    zeile = hole_eigenen_trade(session, nutzer, trade_id)

    if zeile.playbook_id is None:
        if not antworten:
            return trade_block(zeile)
        raise HTTPException(
            400, "Erst ein Playbook zuordnen, dann die Regeln beantworten"
        )

    buch = hole_eigenes_playbook(session, nutzer, zeile.playbook_id)
    erlaubt = {r.id for r in buch.rules}

    gesehen: dict[int, bool] = {}
    for a in antworten:
        if a.rule_id not in erlaubt:
            raise HTTPException(
                400, f"Regel {a.rule_id} gehört nicht zum Playbook dieses Trades"
            )
        # Doppelte in der Eingabe: die letzte gilt.
        gesehen[a.rule_id] = a.checked

    session.execute(
        delete(db.TradeRuleCheck).where(
            db.TradeRuleCheck.trade_id == trade_id,
            db.TradeRuleCheck.rule_id.in_(erlaubt),
        )
    )
    for rule_id, gehalten in gesehen.items():
        session.add(
            db.TradeRuleCheck(trade_id=trade_id, rule_id=rule_id, checked=gehalten)
        )

    session.commit()
    session.refresh(zeile)
    return trade_block(zeile)


# ---------------------------------------------------------------------------
# Einlieferung durch den Sammler
# ---------------------------------------------------------------------------
#
# Der Sammler läuft unter Wine auf dem Dauerrechner und schickt hierher,
# was er in der MT5-Historie gefunden hat. Er rechnet nichts: Umwandlung,
# Round-Trip-Bildung und Kennzahlen passieren alle hier. Was drüben nicht
# steht, kann drüben nicht kaputtgehen.
#
# Der Zugang läuft über eine eigene Marke, nicht über eine Browser-Sitzung:
# Sie steht dauerhaft in einer Datei auf dem Dauerrechner und darf deshalb
# nur einliefern, nicht lesen.


def sammler_marke(
    request: Request, session: Session = Depends(hole_session)
) -> db.Zugangsmarke:
    """Prüft die Marke im `Authorization`-Kopf.

    Bewusst nicht über das Sitzungs-Cookie: Der Sammler hat keinen
    Browser, und ein Cookie mit 30 Tagen Laufzeit in einer
    Konfigurationsdatei wäre ein Vollzugang zum Journal.
    """
    kopf = request.headers.get("authorization", "")
    if not kopf.lower().startswith("bearer "):
        raise HTTPException(401, "Zugangsmarke fehlt")

    marke = session.scalars(
        select(db.Zugangsmarke).where(
            db.Zugangsmarke.token_hash == sicherheit.marken_hash(kopf[7:].strip())
        )
    ).first()
    if marke is None:
        raise HTTPException(401, "Zugangsmarke gilt nicht")

    marke.last_used = datetime.now(timezone.utc)
    session.commit()
    return marke


class Lieferung(BaseModel):
    """Was der Sammler schickt."""

    deals: list[dict] = []
    #: Gemessener Versatz der Serverzeit gegenüber UTC, in Sekunden.
    #: `None`, wenn bei geschlossenem Markt nicht gemessen werden konnte --
    #: dann gilt der zuletzt bekannte Wert weiter.
    server_utc_offset: int | None = None
    fetched_at: str | None = None
    #: Zeitraum, den der Sammler abgefragt hat -- nur fürs Protokoll.
    window_from: str | None = None
    window_to: str | None = None
    collector: str | None = None


@app.post("/api/ingest/deals")
def einliefern(
    lieferung: Lieferung,
    marke: db.Zugangsmarke = Depends(sammler_marke),
    session: Session = Depends(hole_session),
):
    """Nimmt eine Lieferung des Sammlers entgegen.

    Wiederholbar: Dieselben Deals beliebig oft geschickt ergeben dieselbe
    Datenlage. Das ist keine Bequemlichkeit, sondern die Grundlage des
    Überlappungsfensters -- jeder Lauf greift drei Tage zurück, damit am
    Rand nichts verlorengeht, und die Dubletten fallen hier still durch.
    """
    from ..db.repository import aufnehmen
    from ..sync.mt5_source import ergebnis_aus_lieferung

    konto = session.get(db.Account, marke.account_id)
    if konto is None:
        raise HTTPException(404, "Konto nicht gefunden")

    try:
        ergebnis, probleme = ergebnis_aus_lieferung(
            lieferung.model_dump(), account_id=str(konto.id)
        )
    except Exception as fehler:  # noqa: BLE001 -- gehört in den Herzschlag
        sync_vermerken(session, konto.id, "mt5", 0, str(fehler))
        raise HTTPException(400, f"Lieferung nicht lesbar: {fehler}")

    # Der Versatz wird nur überschrieben, wenn wirklich gemessen wurde.
    # Bei geschlossenem Markt liefert der Sammler `None` -- und der
    # zuletzt bekannte Wert ist dann besser als jede Neuberechnung.
    if ergebnis.server_utc_offset is not None:
        vorher = konto.server_utc_offset
        konto.server_utc_offset = ergebnis.server_utc_offset
        if vorher != ergebnis.server_utc_offset:
            # Ein Wechsel bedeutet fast immer Sommerzeit beim Broker. Die
            # schon gespeicherten Deals tragen den alten Versatz -- sie
            # bleiben richtig, weil er beim Einliefern angewandt wurde.
            session.commit()

    try:
        neu, anzahl = aufnehmen(session, konto.id, ergebnis.deals, source="mt5")
    except Exception as fehler:  # noqa: BLE001
        raise HTTPException(500, f"Speichern fehlgeschlagen: {fehler}")

    return {
        "ok": True,
        "account_id": konto.id,
        "deals_received": len(lieferung.deals),
        "deals_new": neu,
        "trades_total": anzahl,
        "server_utc_offset": konto.server_utc_offset,
        "offset_measured": ergebnis.server_utc_offset is not None,
        "problems": probleme[:50],
    }


@app.get("/api/ingest/ping")
def sammler_ping(marke: db.Zugangsmarke = Depends(sammler_marke)):
    """Damit der Sammler seine Marke prüfen kann, bevor er loslegt.

    Verrät nur, wofür die Marke gilt -- nicht, was in dem Konto steht.
    """
    return {"ok": True, "account_id": marke.account_id, "label": marke.label}


def init_db() -> None:
    schema_anlegen(engine)


init_db()

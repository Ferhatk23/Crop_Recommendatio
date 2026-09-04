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

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core import instruments, metrics as kern_metrics, rules, score as kern_score
from ..core.metrics import daily_pnl
from ..core.models import Outcome
from ..db import models as db
from ..db.repository import (
    engine_bauen,
    kennzahlen,
    schema_anlegen,
    session_factory,
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
# Hilfen
# ---------------------------------------------------------------------------

def z(wert: Decimal | float | None) -> float | None:
    """Decimal zu JSON-Zahl. `None` bleibt `None` -- das ist der Punkt."""
    return None if wert is None else float(wert)


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


def filter_aus_query(
    account_id: int | None = Query(None),
    von: str | None = Query(None),
    bis: str | None = Query(None),
    symbol: str | None = Query(None),
    direction: str | None = Query(None),
) -> dict:
    start, ende = zeitraum(von, bis)
    return {
        "account_id": account_id,
        "von": start,
        "bis": ende,
        "symbol": symbol,
        "direction": direction,
    }


# ---------------------------------------------------------------------------
# Konten und Zustand
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health(session: Session = Depends(hole_session)):
    anzahl = session.scalar(select(func.count()).select_from(db.Trade)) or 0
    return {"status": "ok", "trades": anzahl}


@app.get("/api/accounts")
def accounts(session: Session = Depends(hole_session)):
    """Alle Konten. Prop-Trader haben über die Zeit mehrere."""
    zeilen = session.scalars(select(db.Account).order_by(db.Account.id)).all()
    heraus = []
    for a in zeilen:
        zustand = session.get(db.SyncState, a.id)
        heraus.append(
            {
                "id": a.id,
                "label": a.label,
                "broker": a.broker,
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
                "sync": sync_block(zustand),
            }
        )
    return heraus


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
        "tags": [
            {"id": tt.tag.id, "label": tt.tag.label,
             "kind": tt.tag.kind.value if hasattr(tt.tag.kind, "value") else tt.tag.kind}
            for tt in zeile.tags
        ],
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
        frage.order_by(db.Trade.opened_at.desc()).limit(limit).offset(offset)
    ).all()

    return {
        "total": gesamt,
        "limit": limit,
        "offset": offset,
        "trades": [trade_block(t) for t in zeilen],
    }


@app.get("/api/trades/{trade_id}")
def detail(trade_id: int, session: Session = Depends(hole_session)):
    zeile = session.get(db.Trade, trade_id)
    if zeile is None:
        raise HTTPException(404, "Trade nicht gefunden")

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
    account_id: int | None = Query(None),
    session: Session = Depends(hole_session),
):
    """Tageswerte eines Monats plus Wochensummen.

    Das Raster ist der eigentliche Wert des Kalenders: Man sieht den Monat
    als Muster, nicht als Nachschlagewerk. Deshalb liefert die API auch
    Tage ohne Handel mit -- eine Lücke im Raster ist eine Information.
    """
    if not 1 <= month <= 12:
        raise HTTPException(400, "Monat muss zwischen 1 und 12 liegen")

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    ende = datetime(
        year + (month == 12), (month % 12) + 1, 1, tzinfo=timezone.utc
    ) - timedelta(microseconds=1)

    trades = trades_laden(session, account_id=account_id, von=start, bis=ende)
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
def csv_import(anfrage: ImportAnfrage, session: Session = Depends(hole_session)):
    """Nimmt einen Broker-Export entgegen.

    Antwortet mit dem vollständigen Bericht -- auch mit dem, was *nicht*
    geklappt hat. Ein Import, der stillschweigend Zeilen wegwirft, ist
    gefährlicher als einer, der abbricht: Die Summe stimmt dann nicht mehr
    und niemand weiß warum.
    """
    from ..db.repository import aufnehmen

    konto = session.get(db.Account, anfrage.account_id)
    if konto is None:
        raise HTTPException(404, "Konto nicht gefunden")

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
    account_id: int | None = Query(None), session: Session = Depends(hole_session)
):
    frage = select(db.Trade.symbol).distinct()
    if account_id:
        frage = frage.where(db.Trade.account_id == account_id)
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
    session: Session = Depends(hole_session),
):
    """Notiz und Playbook-Zuordnung setzen.

    Nur die Felder, die im Rumpf stehen. `note: null` löscht die Notiz,
    ein fehlendes `note` lässt sie stehen.
    """
    zeile = session.get(db.Trade, trade_id)
    if zeile is None:
        raise HTTPException(404, "Trade nicht gefunden")

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
    session: Session = Depends(hole_session),
):
    """Setzt die Tags eines Trades auf genau diese Liste.

    Unbekannte Bezeichnungen werden angelegt, bekannte wiederverwendet --
    sonst stünde dasselbe Setup unter zwei IDs im Report. Doppelte in der
    Eingabe fallen zusammen.
    """
    zeile = session.get(db.Trade, trade_id)
    if zeile is None:
        raise HTTPException(404, "Trade nicht gefunden")

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
    user_id = None
    if account_id:
        konto = session.get(db.Account, account_id)
        if konto is None:
            raise HTTPException(404, "Konto nicht gefunden")
        user_id = konto.user_id

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
    session: Session = Depends(hole_session),
):
    """Tagesnotiz und Stimmung setzen."""
    try:
        datum = date.fromisoformat(tag)
    except ValueError:
        raise HTTPException(400, f"Datum nicht lesbar: {tag}")

    if session.get(db.Account, account_id) is None:
        raise HTTPException(404, "Konto nicht gefunden")

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


@app.get("/api/playbooks")
def playbooks(
    account_id: int | None = Query(None), session: Session = Depends(hole_session)
):
    """Die Playbooks samt Regeln -- für die Auswahl am Trade."""
    frage = select(db.Playbook).order_by(db.Playbook.name)
    if account_id:
        konto = session.get(db.Account, account_id)
        if konto is None:
            raise HTTPException(404, "Konto nicht gefunden")
        frage = frage.where(db.Playbook.user_id == konto.user_id)

    return [
        {
            "id": b.id,
            "name": b.name,
            "description": b.description,
            "rules": [
                {
                    "id": r.id,
                    "group": r.group_label,
                    "text": r.text,
                    "checkable": r.checkable,
                }
                for r in sorted(b.rules, key=lambda r: r.sort_order)
            ],
        }
        for b in session.scalars(frage).all()
    ]


def init_db() -> None:
    schema_anlegen(engine)


init_db()

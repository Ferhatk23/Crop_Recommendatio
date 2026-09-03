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
from sqlalchemy import func, select
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
    if dimension not in DIMENSIONEN:
        raise HTTPException(
            400, f"Unbekannte Dimension. Verfügbar: {', '.join(DIMENSIONEN)}"
        )

    schluessel = DIMENSIONEN[dimension]
    trades = [t for t in trades_laden(session, **f) if not t.is_open]

    gruppen: dict[str, list] = {}
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


def init_db() -> None:
    schema_anlegen(engine)


init_db()

"""Zwischen Datenbankzeilen und den Dataclasses des Kerns übersetzen.

Der Kern rechnet auf `Decimal` und kennt keine Datenbank. Die Datenbank
kennt keine Geschäftslogik. Diese Datei ist die einzige Stelle, an der
beide sich begegnen -- und damit auch die einzige, die man anfassen muss,
wenn eine von beiden Seiten sich ändert.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker

from ..core import instruments, metrics as kern_metrics
from ..core.models import ZERO, Deal, DealEntry, DealType, Direction
from ..core.models import Trade as KernTrade
from ..core.roundtrip import trades_from_executions, trades_from_positions
from . import models as db


def engine_bauen(url: str = "sqlite:///tradediary.db"):
    """Erzeugt die Engine. SQLite in der Entwicklung, Postgres im Betrieb."""
    kwargs = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def schema_anlegen(engine) -> None:
    db.Base.metadata.create_all(engine)


def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


# ---------------------------------------------------------------------------
# Umwandlung
# ---------------------------------------------------------------------------

def _dec(wert) -> Decimal:
    """DB-Zahl zu Decimal. SQLite gibt je nach Typ float zurück."""
    if wert is None:
        return ZERO
    if isinstance(wert, Decimal):
        return wert
    return Decimal(str(wert))


def _utc(zeit: datetime | None) -> datetime | None:
    """Stellt sicher, dass eine Zeit zeitzonenbehaftet ist.

    SQLite gibt naive datetimes zurück, auch wenn sie mit Zeitzone
    gespeichert wurden. Ein Vergleich zwischen naiv und bewusst wirft --
    und zwar erst beim Sortieren, weit weg von der Ursache.
    """
    if zeit is None:
        return None
    return zeit if zeit.tzinfo else zeit.replace(tzinfo=timezone.utc)


def deal_zu_kern(zeile: db.Deal) -> Deal:
    return Deal(
        ticket=zeile.ticket,
        account_id=str(zeile.account_id),
        position_id=zeile.position_id,
        symbol=zeile.symbol,
        type=DealType(zeile.type),
        entry=DealEntry(zeile.entry),
        volume=_dec(zeile.volume),
        price=_dec(zeile.price),
        time_utc=_utc(zeile.time_utc),
        profit=_dec(zeile.profit),
        commission=_dec(zeile.commission),
        swap=_dec(zeile.swap),
        fee=_dec(zeile.fee),
        time_broker=zeile.time_broker,
        stop_loss=_dec(zeile.stop_loss) if zeile.stop_loss is not None else None,
    )


def trade_zu_kern(zeile: db.Trade) -> KernTrade:
    t = KernTrade(
        account_id=str(zeile.account_id),
        symbol=zeile.symbol,
        direction=Direction(zeile.direction),
        opened_at=_utc(zeile.opened_at),
        volume=_dec(zeile.volume),
        avg_entry=_dec(zeile.avg_entry) if zeile.avg_entry is not None else None,
        closed_at=_utc(zeile.closed_at),
        avg_exit=_dec(zeile.avg_exit) if zeile.avg_exit is not None else None,
        exit_volume=_dec(zeile.exit_volume),
        gross_pnl=_dec(zeile.gross_pnl),
        costs=_dec(zeile.costs),
        position_id=zeile.position_id,
        partial=zeile.partial,
        initial_sl=_dec(zeile.initial_sl) if zeile.initial_sl is not None else None,
    )
    if zeile.risk_amount is not None:
        t.risk_amount = _dec(zeile.risk_amount)
    return t


# ---------------------------------------------------------------------------
# Aufnahme
# ---------------------------------------------------------------------------

def deals_speichern(session: Session, account_id: int, deals: list[Deal]) -> int:
    """Speichert Ausführungen und weist bereits bekannte still ab.

    Genau das macht den wiederholten Abgleich desselben Zeitraums
    ungefährlich -- und damit die ganze Kette ausfallsicher: Verpasst der
    Sammler einen Lauf, holt der nächste alles nach, ohne dass etwas
    doppelt gezählt wird.
    """
    if not deals:
        return 0

    bekannt = set(
        session.scalars(
            select(db.Deal.ticket).where(db.Deal.account_id == account_id)
        ).all()
    )

    neu = 0
    for d in deals:
        if d.ticket in bekannt:
            continue
        bekannt.add(d.ticket)
        session.add(
            db.Deal(
                ticket=d.ticket,
                account_id=account_id,
                position_id=d.position_id,
                symbol=d.symbol,
                type=d.type.value,
                entry=d.entry.value,
                volume=d.volume,
                price=d.price,
                time_utc=d.time_utc,
                time_broker=d.time_broker,
                profit=d.profit,
                commission=d.commission,
                swap=d.swap,
                fee=d.fee,
                stop_loss=d.stop_loss,
            )
        )
        neu += 1

    session.commit()
    return neu


def trades_neu_berechnen(session: Session, account_id: int) -> int:
    """Baut die Trades des Kontos aus den Deals neu auf.

    Bewusst vollständig statt inkrementell: Die Deals sind die Wahrheit,
    die Trades nur ihr Abbild. Ein Neuaufbau ist billig und kann nicht in
    einen halben Zustand geraten -- und er ist der Weg, auf dem eine
    korrigierte Zuordnungslogik rückwirkend greift.
    """
    zeilen = session.scalars(
        select(db.Deal).where(db.Deal.account_id == account_id)
    ).all()
    if not zeilen:
        return 0

    deals = [deal_zu_kern(z) for z in zeilen]

    # Notizen, Tags, Playbook-Zuordnung und Regel-Antworten hängen am Trade
    # und dürfen einen Neuaufbau überleben. Sie werden über die position_id
    # wiedergefunden -- die ist die einzige Größe, die ein Neuaufbau
    # unverändert lässt.
    #
    # Die Tag-Verknüpfungen müssen dabei ausdrücklich mitgeführt werden.
    # `Trade.tags` trägt zwar `cascade="all, delete-orphan"`, aber das ist
    # eine ORM-Regel: Sie greift bei `session.delete(trade)` und wird von
    # einem Bulk-DELETE wie dem unten übergangen. Ohne die Zeilen hier
    # blieben Verknüpfungen zurück, die auf gelöschte IDs zeigen -- und
    # SQLite vergibt nach einem vollständigen Löschen wieder ab 1.
    #
    # Nachgemessen, nicht vermutet: Ein Tag auf Gold (position 300, ID 3)
    # hing nach einem Nachimport älterer Historie an EURUSD (position 100),
    # weil das nach der Neuvergabe die ID 3 war. Genau der schlimmste
    # Fehler, den ein Journal machen kann -- er sieht nach nichts aus und
    # verfälscht still die Auswertung nach Setup.
    alte = session.scalars(
        select(db.Trade).where(db.Trade.account_id == account_id)
    ).all()
    bewahrt = {t.position_id: (t.note, t.playbook_id) for t in alte}
    bewahrte_tags = {
        t.position_id: [tt.tag_id for tt in t.tags] for t in alte if t.tags
    }
    # Dieselbe Falle wie bei den Tags, und aus demselben Grund ausdrücklich:
    # Die Regel-Antworten sind von Hand gesetzt und stehen nirgends sonst.
    bewahrte_regeln = {
        t.position_id: [(c.rule_id, c.checked) for c in t.rule_checks]
        for t in alte
        if t.rule_checks
    }

    if alte:
        alte_ids = [t.id for t in alte]
        session.execute(
            delete(db.TradeTag).where(db.TradeTag.trade_id.in_(alte_ids))
        )
        session.execute(
            delete(db.TradeRuleCheck).where(
                db.TradeRuleCheck.trade_id.in_(alte_ids)
            )
        )
    session.execute(delete(db.Trade).where(db.Trade.account_id == account_id))

    # Über die position_id des Brokers, wenn sie etwas hergibt -- sonst über
    # die Ausführungsreihenfolge.
    hat_positionen = len({d.position_id for d in deals}) > 1
    trades = (
        trades_from_positions(deals) if hat_positionen else trades_from_executions(deals)
    )

    neue: list[tuple[int, db.Trade]] = []
    for t in trades:
        note, playbook_id = bewahrt.get(t.position_id, (None, None))
        # Das R-Multiple ist die einzige Größe, die der Broker nicht
        # mitliefert -- der Trade ist ja nie am Stop gelandet. Sie wird
        # hier aus Stop-Abstand und Kontraktwert gebildet; fehlt eine der
        # Angaben, bleibt sie None statt geraten zu werden.
        if t.risk_amount is None:
            t.risk_amount = instruments.risiko(
                t.symbol, t.avg_entry, t.initial_sl, t.volume
            )
        zeile = db.Trade(
            account_id=account_id,
            position_id=t.position_id or 0,
            symbol=t.symbol,
            direction=t.direction.value,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
            volume=t.volume,
            exit_volume=t.exit_volume,
            avg_entry=t.avg_entry,
            avg_exit=t.avg_exit,
            gross_pnl=t.gross_pnl,
            costs=t.costs,
            net_pnl=t.net_pnl,
            initial_sl=t.initial_sl,
            risk_amount=t.risk_amount,
            r_multiple=t.r_multiple,
            partial=t.partial,
            note=note,
            playbook_id=playbook_id,
        )
        session.add(zeile)
        neue.append((t.position_id or 0, zeile))

    # Erst nach dem Flush stehen die neuen IDs fest -- vorher gäbe es
    # nichts, woran die Verknüpfungen hängen könnten.
    session.flush()
    for position_id, zeile in neue:
        for tag_id in bewahrte_tags.get(position_id, ()):
            session.add(db.TradeTag(trade_id=zeile.id, tag_id=tag_id))
        for rule_id, gehalten in bewahrte_regeln.get(position_id, ()):
            session.add(
                db.TradeRuleCheck(
                    trade_id=zeile.id, rule_id=rule_id, checked=gehalten
                )
            )

    session.commit()
    return len(trades)


def sync_vermerken(
    session: Session,
    account_id: int,
    source: str,
    neue_deals: int,
    fehler: str | None = None,
) -> None:
    """Schreibt den Herzschlag fort."""
    zustand = session.get(db.SyncState, account_id)
    if zustand is None:
        zustand = db.SyncState(account_id=account_id)
        session.add(zustand)

    jetzt = datetime.now(timezone.utc)
    zustand.source = source
    zustand.last_run_at = jetzt
    zustand.last_error = fehler
    if fehler is None:
        zustand.last_success_at = jetzt
        zustand.deals_imported = (zustand.deals_imported or 0) + neue_deals
        letzte = session.scalar(
            select(db.Deal.time_utc)
            .where(db.Deal.account_id == account_id)
            .order_by(db.Deal.time_utc.desc())
            .limit(1)
        )
        if letzte is not None:
            zustand.last_deal_time = _utc(letzte)

    session.commit()


def aufnehmen(
    session: Session, account_id: int, deals: list[Deal], source: str = "csv"
) -> tuple[int, int]:
    """Der ganze Weg: speichern, neu zuordnen, Herzschlag setzen."""
    try:
        neu = deals_speichern(session, account_id, deals)
        anzahl = trades_neu_berechnen(session, account_id)
        sync_vermerken(session, account_id, source, neu)
        return neu, anzahl
    except Exception as fehler:  # noqa: BLE001 -- Fehler gehört in den Herzschlag
        session.rollback()
        sync_vermerken(session, account_id, source, 0, str(fehler))
        raise


# ---------------------------------------------------------------------------
# Abfragen
# ---------------------------------------------------------------------------

def zeilen_laden(
    session: Session,
    account_id: int | None = None,
    von: datetime | None = None,
    bis: datetime | None = None,
    symbol: str | None = None,
    direction: str | None = None,
    account_ids: list[int] | None = None,
) -> list[db.Trade]:
    """Die gefilterten Trades als Datenbankzeilen.

    Der Kern kennt keine Tags und kein Playbook -- das sind Zutaten des
    Nutzers, keine des Handels. Wer danach auswerten will, braucht die
    Zeile; wer rechnen will, den Kern. Deshalb zwei Wege auf dieselbe
    Abfrage statt einer Dataclass, die beides vermischt.

    `account_ids` ist die Berechtigungsschranke, `account_id` der Filter.
    Zwei Begriffe, weil es zwei Dinge sind: Der Nutzer *darf* seine drei
    Konten sehen und *möchte* gerade eines davon. Eine leere Liste heißt
    "keins" und liefert nichts -- niemals versehentlich alles.

    Tags und Regel-Antworten kommen ausdrücklich mit. Wer die Zeile statt
    des Kerns lädt, will genau die -- und ohne das Vorladen stellt jeder
    Zugriff darauf eine eigene Abfrage. Nachgemessen an 1.200 Trades:
    1.207 Abfragen und 570 ms für einen Report, weil jede Zeile einzeln
    nachgefragt wurde. Es fällt bei fünfzig Trades nicht auf und wächst
    dann linear mit, bis der Report auf dem Telefon eine Sekunde steht.
    """
    frage = select(db.Trade).options(
        selectinload(db.Trade.tags).joinedload(db.TradeTag.tag),
        selectinload(db.Trade.rule_checks).joinedload(db.TradeRuleCheck.rule),
    )
    if account_ids is not None:
        if not account_ids:
            return []
        frage = frage.where(db.Trade.account_id.in_(account_ids))
    if account_id is not None:
        frage = frage.where(db.Trade.account_id == account_id)
    if von is not None:
        frage = frage.where(db.Trade.opened_at >= von)
    if bis is not None:
        frage = frage.where(db.Trade.opened_at <= bis)
    if symbol:
        frage = frage.where(db.Trade.symbol == symbol)
    if direction:
        frage = frage.where(db.Trade.direction == direction)

    return list(session.scalars(frage.order_by(db.Trade.opened_at.desc())).all())


def trades_laden(
    session: Session,
    account_id: int | None = None,
    von: datetime | None = None,
    bis: datetime | None = None,
    symbol: str | None = None,
    direction: str | None = None,
    account_ids: list[int] | None = None,
) -> list[KernTrade]:
    return [
        trade_zu_kern(z)
        for z in zeilen_laden(
            session, account_id, von, bis, symbol, direction, account_ids
        )
    ]


def kennzahlen(session: Session, **filter) -> kern_metrics.Metrics:
    """Kennzahlen über die gefilterten Trades -- gerechnet vom Kern."""
    return kern_metrics.compute(trades_laden(session, **filter))

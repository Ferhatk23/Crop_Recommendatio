"""Tests für Speichern und Neuberechnen.

Der Neuaufbau ist die gefährlichste Stelle der Datenhaltung: Er löscht
alle Trades eines Kontos und baut sie aus den Deals wieder auf. Alles,
was der Nutzer selbst geschrieben hat -- Notiz, Tags, Playbook-Zuordnung --
hängt am Trade und muss diesen Vorgang überstehen. Und zwar am *richtigen*
Trade.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from tradediary.db import models as db
from tradediary.db.repository import (
    deals_speichern,
    engine_bauen,
    schema_anlegen,
    session_factory,
    trades_neu_berechnen,
)

from .conftest import close_long, close_short, open_long, open_short


@pytest.fixture()
def session():
    """Eine leere Datenbank im Speicher, je Test frisch."""
    engine = engine_bauen("sqlite://")
    schema_anlegen(engine)
    Session_ = session_factory(engine)
    with Session_() as s:
        s.add(db.User(id=1, email="test@example.invalid", password_hash="x"))
        s.add(db.Account(id=1, user_id=1, label="Testkonto"))
        s.commit()
        yield s


def _drei_trades():
    """Drei abgeschlossene Round-Trips mit verschiedenen position_ids."""
    return [
        open_long(1, 100, "1.00", "1.08000", 0),
        close_long(2, 100, "1.00", "1.08300", 30, profit=300),
        open_short(3, 200, "1.00", "1.26000", 60),
        close_short(4, 200, "1.00", "1.25800", 90, profit=200),
        open_long(5, 300, "0.50", "2400.00", 120, symbol="XAUUSD"),
        close_long(6, 300, "0.50", "2390.00", 150, symbol="XAUUSD", profit=-500),
    ]


def test_neuberechnen_bewahrt_die_notiz(session):
    deals_speichern(session, 1, _drei_trades())
    trades_neu_berechnen(session, 1)

    trade = session.scalars(
        select(db.Trade).where(db.Trade.position_id == 200)
    ).one()
    trade.note = "Zu früh raus, Plan war 1,25500."
    session.commit()

    trades_neu_berechnen(session, 1)

    danach = session.scalars(
        select(db.Trade).where(db.Trade.position_id == 200)
    ).one()
    assert danach.note == "Zu früh raus, Plan war 1,25500."


def test_neuberechnen_bewahrt_die_tags(session):
    """Der einfache Fall: Neuaufbau ohne neue Daten."""
    deals_speichern(session, 1, _drei_trades())
    trades_neu_berechnen(session, 1)

    marke = db.Tag(user_id=1, label="Breakout", kind=db.TagArt.SETUP)
    session.add(marke)
    session.flush()

    gold = session.scalars(
        select(db.Trade).where(db.Trade.position_id == 300)
    ).one()
    session.add(db.TradeTag(trade_id=gold.id, tag_id=marke.id))
    session.commit()

    trades_neu_berechnen(session, 1)

    danach = session.scalars(
        select(db.Trade).where(db.Trade.position_id == 300)
    ).one()
    assert [tt.tag.label for tt in danach.tags] == ["Breakout"]


def test_tag_bleibt_am_trade_wenn_aeltere_historie_nachkommt(session):
    """Der Kern der Sache -- und der Fall, der wirklich vorkommt.

    Der Neuaufbau löscht alle Trades und legt sie neu an. Werden die
    Tag-Verknüpfungen dabei nicht mitgeführt, zeigen sie auf IDs, die es
    nicht mehr gibt, und SQLite vergibt nach vollständigem Löschen wieder
    ab 1.

    Ohne neue Daten fällt das nicht auf: Es entstehen dieselben Trades in
    derselben Reihenfolge und damit dieselben IDs -- die verwaiste
    Verknüpfung landet zufällig wieder richtig. Ein Test, der nur das
    prüft, ist deshalb grün, ohne etwas zu beweisen.

    Erst ein Nachimport älterer Historie -- der Normalfall beim ersten
    CSV-Rückwärtsfüllen -- verschiebt die Reihenfolge. Nachgemessen: Der
    Tag lag auf Gold (position 300, ID 3) und hing danach an EURUSD
    (position 100), weil das nach der Neuvergabe die ID 3 war.

    Das ist der schlimmste Fehler, den ein Journal machen kann. Er sieht
    nach nichts aus und verfälscht still die Auswertung nach Setup.
    """
    deals_speichern(session, 1, _drei_trades())
    trades_neu_berechnen(session, 1)

    marke = db.Tag(user_id=1, label="Breakout", kind=db.TagArt.SETUP)
    session.add(marke)
    session.flush()

    gold = session.scalars(
        select(db.Trade).where(db.Trade.position_id == 300)
    ).one()
    session.add(db.TradeTag(trade_id=gold.id, tag_id=marke.id))
    session.commit()

    # Zwei ältere Trades kommen nach und schieben sich davor.
    deals_speichern(
        session,
        1,
        [
            open_long(7, 50, "1.00", "1.07000", -300),
            close_long(8, 50, "1.00", "1.07200", -280, profit=200),
            open_long(9, 60, "1.00", "1.07500", -200),
            close_long(10, 60, "1.00", "1.07400", -180, profit=-100),
        ],
    )
    trades_neu_berechnen(session, 1)

    getaggt = [
        (t.position_id, t.symbol)
        for t in session.scalars(select(db.Trade)).all()
        if t.tags
    ]
    assert getaggt == [(300, "XAUUSD")], (
        f"Tag ist auf einen fremden Trade gerutscht: {getaggt}"
    )

    # Und keine Verknüpfung zeigt ins Leere.
    verknuepfungen = session.scalars(select(db.TradeTag)).all()
    ids = {t.id for t in session.scalars(select(db.Trade)).all()}
    assert {v.trade_id for v in verknuepfungen} <= ids
    assert len(verknuepfungen) == 1


def test_notiz_bleibt_am_trade_wenn_aeltere_historie_nachkommt(session):
    """Dieselbe Probe für die Notiz. Sie war schon richtig -- und soll es bleiben."""
    deals_speichern(session, 1, _drei_trades())
    trades_neu_berechnen(session, 1)

    gold = session.scalars(
        select(db.Trade).where(db.Trade.position_id == 300)
    ).one()
    gold.note = "Gold: Stop zu eng gesetzt."
    session.commit()

    deals_speichern(
        session,
        1,
        [
            open_long(7, 50, "1.00", "1.07000", -300),
            close_long(8, 50, "1.00", "1.07200", -280, profit=200),
        ],
    )
    trades_neu_berechnen(session, 1)

    mit_notiz = [
        (t.position_id, t.symbol)
        for t in session.scalars(select(db.Trade)).all()
        if t.note
    ]
    assert mit_notiz == [(300, "XAUUSD")]


def test_neuberechnen_bewahrt_das_playbook(session):
    deals_speichern(session, 1, _drei_trades())
    trades_neu_berechnen(session, 1)

    buch = db.Playbook(user_id=1, name="London Breakout")
    session.add(buch)
    session.flush()

    trade = session.scalars(
        select(db.Trade).where(db.Trade.position_id == 100)
    ).one()
    trade.playbook_id = buch.id
    session.commit()

    trades_neu_berechnen(session, 1)

    danach = session.scalars(
        select(db.Trade).where(db.Trade.position_id == 100)
    ).one()
    assert danach.playbook_id == buch.id


def test_neuberechnen_ist_wiederholbar(session):
    """Zweimal aufgerufen kommt zweimal dasselbe heraus."""
    deals_speichern(session, 1, _drei_trades())
    erste = trades_neu_berechnen(session, 1)
    zweite = trades_neu_berechnen(session, 1)
    assert erste == zweite == 3
    assert len(session.scalars(select(db.Trade)).all()) == 3


def test_deals_speichern_ist_idempotent(session):
    """Derselbe Deal zweimal geliefert bleibt ein Deal.

    Der Abgleich holt sich bewusst ein überlappendes Fenster, damit am
    Rand kein Deal verlorengeht. Ohne Idempotenz zählte dann jeder Trade
    aus der Überlappung doppelt.
    """
    deals = _drei_trades()
    assert deals_speichern(session, 1, deals) == 6
    assert deals_speichern(session, 1, deals) == 0
    assert len(session.scalars(select(db.Deal)).all()) == 6


def test_tags_anderer_konten_bleiben_unberuehrt(session):
    """Ein Neuaufbau für Konto 1 fasst Konto 2 nicht an."""
    session.add(db.Account(id=2, user_id=1, label="Zweitkonto"))
    session.commit()

    deals_speichern(session, 1, _drei_trades())
    deals_speichern(
        session,
        2,
        [
            open_long(11, 500, "1.00", "1.08000", 0),
            close_long(12, 500, "1.00", "1.08100", 30, profit=100),
        ],
    )
    trades_neu_berechnen(session, 1)
    trades_neu_berechnen(session, 2)

    marke = db.Tag(user_id=1, label="Pullback", kind=db.TagArt.SETUP)
    session.add(marke)
    session.flush()
    fremd = session.scalars(
        select(db.Trade).where(db.Trade.account_id == 2)
    ).one()
    session.add(db.TradeTag(trade_id=fremd.id, tag_id=marke.id))
    session.commit()

    trades_neu_berechnen(session, 1)

    danach = session.scalars(
        select(db.Trade).where(db.Trade.account_id == 2)
    ).one()
    assert [tt.tag.label for tt in danach.tags] == ["Pullback"]

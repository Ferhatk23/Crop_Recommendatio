"""Wie viele SQL-Abfragen ein Aufruf kostet.

Diese Tests messen keine Zeit -- Zeitmessungen in einer Testsuite sind
launisch und fallen auf einer ausgelasteten Maschine grundlos um. Sie
zählen Abfragen, und das ist die Größe, um die es geht: Ein Nachladen je
Zeile bleibt bei fünfzig Trades unbemerkt und wächst dann linear mit.

Nachgemessen an 1.200 Trades mit je vier Regel-Antworten und zwei Tags:
Ein Report kostete 1.207 Abfragen und 570 ms, weil `trade_block` von
jeder Zeile die Tags las und von jeder Antwort, zu welchem Playbook sie
gehört. Mit dem Vorladen sind es 11 Abfragen und 416 ms -- der Rest ist
die Decimal-Rechnung über 1.200 Trades und keine Datenbanksache mehr.

Die Schranken hier sind bewusst grob. Sie sollen nicht jede zusätzliche
Abfrage anschlagen, sondern den einen Fehler fangen, der sich
einschleicht, ohne dass irgendetwas rot wird: ein Zugriff je Zeile.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from tradediary.db import models as db
from tradediary.db.repository import deals_speichern, trades_neu_berechnen

from .conftest import close_long, open_long
from .test_api_playbooks import anlegen  # noqa: F401
from .test_api_schreiben import PASSWORT, client, roh_client  # noqa: F401


ANZAHL = 40


@pytest.fixture()
def viele(client):
    """Genug Trades, dass ein Zugriff je Zeile sich deutlich abhebt.

    Vierzig, nicht vierhundert: Die Zahl muss nur weit genug über der
    festen Grundlast liegen, damit ein N+1 nicht in ihr untergeht.
    """
    buch = anlegen(client)
    with client.session_factory() as s:  # type: ignore[attr-defined]
        deals = []
        for i in range(ANZAHL):
            ticket = 1000 + i * 2
            deals.append(open_long(ticket, 1000 + i, "1.00", "1.08000", i * 120))
            deals.append(
                close_long(ticket + 1, 1000 + i, "1.00", "1.08100", i * 120 + 60,
                           profit=100)
            )
        deals_speichern(s, 1, deals)
        trades_neu_berechnen(s, 1)

    trades = client.get("/api/trades?limit=500").json()["trades"]
    for t in trades:
        client.patch(f"/api/trades/{t['id']}", json={"playbook_id": buch["id"]})
        client.put(
            f"/api/trades/{t['id']}/regeln",
            json=[{"rule_id": r["id"], "checked": True} for r in buch["rules"][:2]],
        )
        client.put(
            f"/api/trades/{t['id']}/tags",
            json={"tags": [{"label": "Breakout", "kind": "setup"}]},
        )
    return {"buch": buch, "anzahl": len(trades)}


@pytest.fixture()
def zaehle(client):
    """Zählt die Abfragen eines Aufrufs."""
    stand = {"n": 0}
    engine = client.main.engine  # type: ignore[attr-defined]

    def mitzaehlen(*args, **kwargs):
        stand["n"] += 1

    def messen(pfad: str) -> int:
        stand["n"] = 0
        event.listen(engine, "before_cursor_execute", mitzaehlen)
        try:
            antwort = client.get(pfad)
            assert antwort.status_code == 200, antwort.text
        finally:
            event.remove(engine, "before_cursor_execute", mitzaehlen)
        return stand["n"]

    return messen


# Grosszügig: Die Grundlast (Sitzung, Nutzer, Konten, Zählabfragen) liegt
# bei einer Handvoll. Alles unter der Zahl der Trades ist der Beweis, dass
# nicht je Zeile nachgeladen wird.
SCHRANKE = 20


def test_die_trade_liste_laedt_nicht_je_zeile_nach(client, viele, zaehle):
    """`trade_block` liest von jeder Zeile die Tags und die Regel-Antworten.

    Ohne Vorladen ist das eine Abfrage je Trade und noch eine je Antwort --
    die Liste kostet dann ein Vielfaches dessen, was sie muss.
    """
    assert viele["anzahl"] >= ANZAHL
    assert zaehle("/api/trades?limit=500") < SCHRANKE


def test_die_regeltreue_laedt_nicht_je_zeile_nach(client, viele, zaehle):
    assert zaehle("/api/reports/regeltreue?account_id=1") < SCHRANKE


def test_der_tag_report_laedt_nicht_je_zeile_nach(client, viele, zaehle):
    """Er greift über `zeilen_laden` auf die Tags jeder Zeile zu."""
    assert zaehle("/api/reports/setup?account_id=1") < SCHRANKE


def test_die_schranke_greift_ueberhaupt(client, viele, zaehle):
    """Gegenprobe: Ohne Vorladen müsste die Schranke reissen.

    Ohne diesen Test wäre nicht zu erkennen, ob die Schranke etwas misst
    oder ob sie bloss weit genug oben liegt, um immer zu halten.
    """
    from tradediary.db import repository

    echt = repository.zeilen_laden

    def nackt(session, **kwargs):
        # Dieselbe Abfrage, nur ohne die `options(...)`.
        zeilen = echt(session, **kwargs)
        for z in zeilen:
            session.expire(z, ["tags", "rule_checks"])
        return zeilen

    repository.zeilen_laden = nackt
    client.main.zeilen_laden = nackt  # type: ignore[attr-defined]
    try:
        assert zaehle("/api/reports/setup?account_id=1") > SCHRANKE
    finally:
        repository.zeilen_laden = echt
        client.main.zeilen_laden = echt  # type: ignore[attr-defined]

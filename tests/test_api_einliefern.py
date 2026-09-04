"""Tests für die Einlieferung durch den Sammler.

Zwei Fragen stehen im Mittelpunkt:

1. Ist der Weg wiederholbar? Das Überlappungsfenster schickt jeden Deal
   mehrfach -- absichtlich, damit am Rand nichts verlorengeht. Wären
   Dubletten nicht abgewiesen, zählte jeder Trade aus der Überlappung
   doppelt.
2. Kann die Marke mehr, als sie soll? Sie steht dauerhaft in einer Datei
   auf dem Dauerrechner. Wer sie findet, darf Deals schicken -- aber
   keine Notizen lesen und keine Kontostände sehen.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from tradediary.db import models as db
from tradediary.sicherheit import neue_marke

from .test_api_schreiben import PASSWORT, client, roh_client, zweiter_nutzer  # noqa: F401

EET = 2 * 3600
STEMPEL = datetime(2026, 3, 2, 9, 31, tzinfo=timezone.utc).timestamp()


@pytest.fixture()
def marke(client):
    """Eine Zugangsmarke für Konto 1, samt Klartext."""
    frisch = neue_marke()
    with client.session_factory() as s:
        s.add(
            db.Zugangsmarke(
                user_id=1, account_id=1, token_hash=frisch.hash, label="Testsammler"
            )
        )
        s.commit()
    return frisch.klartext


def kopf(marke):
    return {"Authorization": f"Bearer {marke}"}


def paar(ticket=700001, position=910001, zeit=STEMPEL, **kw):
    """Ein Deal-Paar: Eröffnung und Schließung eines Round-Trips."""
    auf = {
        "ticket": ticket, "time": zeit, "type": 0, "entry": 0,
        "position_id": position, "symbol": "EURUSD", "volume": 1.0,
        "price": 1.08000, "profit": 0.0, "commission": -3.5,
        "swap": 0.0, "fee": 0.0, "sl": 1.07700,
    }
    zu = dict(auf, ticket=ticket + 1, time=zeit + 1800, type=1, entry=1,
              price=1.08300, profit=300.0, sl=0.0)
    auf.update(kw)
    return [auf, zu]


# ---------------------------------------------------------------------------
# Zugang
# ---------------------------------------------------------------------------

def test_ohne_marke_keine_einlieferung(roh_client):
    assert roh_client.post("/api/ingest/deals", json={"deals": []}).status_code == 401


def test_erfundene_marke_wird_abgewiesen(roh_client):
    antwort = roh_client.post(
        "/api/ingest/deals", json={"deals": []},
        headers={"Authorization": "Bearer voellig-ausgedacht"},
    )
    assert antwort.status_code == 401


def test_das_sitzungs_cookie_taugt_nicht_als_marke(client):
    """Getrennte Wege, absichtlich.

    Ein Browser-Cookie im Sammler wäre ein Vollzugang zum Journal in
    einer Konfigurationsdatei.
    """
    assert client.post("/api/ingest/deals", json={"deals": []}).status_code == 401


def test_die_marke_taugt_nicht_zum_lesen(roh_client, client, marke):
    """Der Kern der Trennung.

    Wer die Datei auf dem Dauerrechner findet, kann Deals schicken -- die
    erkennt man an den Tickets und löscht sie wieder. Er soll aber weder
    Notizen lesen noch sehen, wie das Konto steht.

    Das Abräumen der Cookies ist hier nicht Kosmetik, sondern die
    Voraussetzung dafür, dass der Test überhaupt etwas prüft: `client`
    und `roh_client` sind dasselbe Objekt -- die eine Fixture meldet die
    andere nur an. Ohne diese Zeile käme `/api/accounts` über das
    Sitzungs-Cookie durch, und der Test bescheinigte der Marke ein Recht,
    das sie gar nicht ausgeübt hat.
    """
    roh_client.cookies.clear()

    for pfad in (
        "/api/accounts", "/api/trades", "/api/overview",
        "/api/tags", "/api/playbooks", "/api/symbols",
        "/api/journal/2026-03-02?account_id=1",
        "/api/auth/me", "/api/auth/sessions",
    ):
        antwort = roh_client.get(pfad, headers=kopf(marke))
        assert antwort.status_code == 401, f"{pfad} liess die Sammler-Marke durch"

    # Gegenprobe -- ohne sie hiesse der Test bloss "alles antwortet 401".
    # Dieselbe Marke, dieselbe cookie-freie Sitzung, und Einliefern geht.
    assert roh_client.post(
        "/api/ingest/deals",
        json={"deals": paar(), "server_utc_offset": EET},
        headers=kopf(marke),
    ).status_code == 200


def test_die_marke_taugt_auch_nicht_zum_schreiben(roh_client, client, marke):
    """Weder Notizen noch Tags noch Import in ein anderes Konto."""
    roh_client.cookies.clear()

    assert roh_client.patch(
        "/api/trades/1", json={"note": "fremd"}, headers=kopf(marke)
    ).status_code == 401
    assert roh_client.put(
        "/api/trades/1/tags", json={"tags": []}, headers=kopf(marke)
    ).status_code == 401
    assert roh_client.post(
        "/api/import/csv", json={"account_id": 1, "content": "x"}, headers=kopf(marke)
    ).status_code == 401


def test_ping_verraet_nur_wofuer_die_marke_gilt(roh_client, client, marke):
    antwort = roh_client.get("/api/ingest/ping", headers=kopf(marke))
    assert antwort.status_code == 200
    assert antwort.json() == {"ok": True, "account_id": 1, "label": "Testsammler"}


def test_zurueckgezogene_marke_wirkt_nicht_mehr(roh_client, client, marke):
    with client.session_factory() as s:
        s.delete(s.scalars(select(db.Zugangsmarke)).one())
        s.commit()
    assert roh_client.get(
        "/api/ingest/ping", headers=kopf(marke)
    ).status_code == 401


def test_benutzung_wird_vermerkt(roh_client, client, marke):
    """Damit man in der Liste sieht, ob der Sammler noch lebt."""
    with client.session_factory() as s:
        assert s.scalars(select(db.Zugangsmarke)).one().last_used is None
    roh_client.get("/api/ingest/ping", headers=kopf(marke))
    with client.session_factory() as s:
        assert s.scalars(select(db.Zugangsmarke)).one().last_used is not None


# ---------------------------------------------------------------------------
# Einliefern
# ---------------------------------------------------------------------------

def test_deals_kommen_an_und_werden_zu_trades(roh_client, client, marke):
    antwort = roh_client.post(
        "/api/ingest/deals",
        json={"deals": paar(), "server_utc_offset": EET},
        headers=kopf(marke),
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["deals_received"] == 2
    assert daten["deals_new"] == 2

    trades = client.get("/api/trades").json()["trades"]
    neuer = [t for t in trades if t["position_id"] == 910001]
    assert len(neuer) == 1
    assert neuer[0]["net_pnl"] == pytest.approx(300.0 - 7.0)


def test_dieselbe_lieferung_zweimal_aendert_nichts(roh_client, client, marke):
    """Die Grundlage des Überlappungsfensters.

    Jeder Lauf greift drei Tage zurück, damit am Rand nichts
    verlorengeht. Ohne Wiederholbarkeit zählte jeder Trade daraus
    mehrfach -- und die Kennzahlen wären mit jedem Lauf falscher.
    """
    rumpf = {"deals": paar(), "server_utc_offset": EET}
    erste = roh_client.post("/api/ingest/deals", json=rumpf, headers=kopf(marke)).json()
    zweite = roh_client.post("/api/ingest/deals", json=rumpf, headers=kopf(marke)).json()

    assert erste["deals_new"] == 2
    assert zweite["deals_new"] == 0
    assert erste["trades_total"] == zweite["trades_total"]


def test_leere_lieferung_ist_ein_lebenszeichen(roh_client, client, marke):
    """Ein Wochenende ohne Trades muss sich von einem toten Sammler
    unterscheiden -- sonst sieht ein stiller Ausfall aus wie Ruhe."""
    antwort = roh_client.post(
        "/api/ingest/deals",
        json={"deals": [], "server_utc_offset": EET},
        headers=kopf(marke),
    )
    assert antwort.status_code == 200
    assert antwort.json()["deals_new"] == 0

    sync = client.get("/api/accounts").json()[0]["sync"]
    assert sync["state"] != "nie"


# ---------------------------------------------------------------------------
# Der Zeitversatz
# ---------------------------------------------------------------------------

def test_gemessener_versatz_wird_uebernommen(roh_client, client, marke):
    antwort = roh_client.post(
        "/api/ingest/deals",
        json={"deals": paar(), "server_utc_offset": EET},
        headers=kopf(marke),
    )
    assert antwort.json()["server_utc_offset"] == EET
    assert antwort.json()["offset_measured"] is True

    with client.session_factory() as s:
        assert s.get(db.Account, 1).server_utc_offset == EET


def test_ohne_messung_bleibt_der_alte_versatz_stehen(roh_client, client, marke):
    """Bei geschlossenem Markt schickt der Sammler `null`.

    Auf null zurückzufallen hiesse zu behaupten, der Server laufe auf
    UTC -- und verschöbe ab dem nächsten Wochenende jeden Trade um zwei
    Stunden.
    """
    roh_client.post(
        "/api/ingest/deals",
        json={"deals": [], "server_utc_offset": EET},
        headers=kopf(marke),
    )
    antwort = roh_client.post(
        "/api/ingest/deals",
        json={"deals": paar(), "server_utc_offset": None},
        headers=kopf(marke),
    )
    assert antwort.json()["offset_measured"] is False
    assert antwort.json()["server_utc_offset"] == EET

    with client.session_factory() as s:
        assert s.get(db.Account, 1).server_utc_offset == EET


def test_der_versatz_wirkt_auf_die_gespeicherte_zeit(roh_client, client, marke):
    """09:31 Serverzeit bei UTC+2 ist 07:31 UTC.

    Ohne die Rechnung stünde der Trade zwei Stunden zu spät -- und der
    Kalender ordnete einen Trade kurz nach Mitternacht dem falschen Tag zu.
    """
    roh_client.post(
        "/api/ingest/deals",
        json={"deals": paar(), "server_utc_offset": EET},
        headers=kopf(marke),
    )
    trade = [
        t for t in client.get("/api/trades").json()["trades"]
        if t["position_id"] == 910001
    ][0]
    assert trade["opened_at"].startswith("2026-03-02T07:31")


# ---------------------------------------------------------------------------
# Grenzen
# ---------------------------------------------------------------------------

def test_die_marke_liefert_nur_in_ihr_eigenes_konto(roh_client, client, marke):
    """Der Sammler für das Challenge-Konto hat im Funded-Konto nichts verloren.

    Das Zielkonto steht an der Marke, nicht in der Lieferung -- es lässt
    sich also gar nicht erst umbiegen.
    """
    fremd = zweiter_nutzer(client)
    antwort = roh_client.post(
        "/api/ingest/deals",
        json={
            "deals": paar(),
            "server_utc_offset": EET,
            "account_id": fremd["account_id"],  # Versuch, umzulenken
        },
        headers=kopf(marke),
    )
    assert antwort.status_code == 200
    assert antwort.json()["account_id"] == 1

    with client.session_factory() as s:
        fremde = s.scalars(
            select(db.Deal).where(db.Deal.account_id == fremd["account_id"])
        ).all()
    assert all(d.position_id != 910001 for d in fremde)


def test_kaputter_datensatz_bricht_die_lieferung_nicht_ab(roh_client, client, marke):
    """Ein einzelner unlesbarer Deal darf die anderen nicht mitnehmen --
    und muss trotzdem gemeldet werden."""
    deals = paar()
    deals.append({"ticket": "keine-zahl", "time": STEMPEL})
    antwort = roh_client.post(
        "/api/ingest/deals",
        json={"deals": deals, "server_utc_offset": EET},
        headers=kopf(marke),
    )
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["deals_new"] == 2
    assert len(daten["problems"]) == 1


def test_stornierter_auftrag_wird_nicht_gezaehlt(roh_client, client, marke):
    deals = paar()
    deals.append(dict(deals[0], ticket=999, type=13))  # BUY_CANCELED
    antwort = roh_client.post(
        "/api/ingest/deals",
        json={"deals": deals, "server_utc_offset": EET},
        headers=kopf(marke),
    )
    assert antwort.json()["deals_received"] == 3
    assert antwort.json()["deals_new"] == 2


def test_stop_null_ergibt_kein_risiko(roh_client, client, marke):
    """MT5 schreibt 0.0 statt None. Als Stop übernommen ergäbe das ein
    Risiko aus dem vollen Kontraktwert und ein R nahe null."""
    deals = paar(position=910002, ticket=700010)
    deals[0]["sl"] = 0.0
    roh_client.post(
        "/api/ingest/deals",
        json={"deals": deals, "server_utc_offset": EET},
        headers=kopf(marke),
    )
    trade = [
        t for t in client.get("/api/trades").json()["trades"]
        if t["position_id"] == 910002
    ][0]
    assert trade["initial_sl"] is None
    assert trade["risk_amount"] is None
    assert trade["r_multiple"] is None


def test_stop_ergibt_ein_r_multiple(roh_client, client, marke):
    """1,00 Lot EURUSD, Stop 30 Pips unter dem Einstieg: 300,00 € Risiko.

    Von Hand gerechnet: 0,00300 × 100.000 × 1,00 = 300,00.
    """
    roh_client.post(
        "/api/ingest/deals",
        json={"deals": paar(), "server_utc_offset": EET},
        headers=kopf(marke),
    )
    trade = [
        t for t in client.get("/api/trades").json()["trades"]
        if t["position_id"] == 910001
    ][0]
    assert trade["risk_amount"] == pytest.approx(300.0)
    assert trade["r_multiple"] == pytest.approx((300.0 - 7.0) / 300.0, abs=1e-4)

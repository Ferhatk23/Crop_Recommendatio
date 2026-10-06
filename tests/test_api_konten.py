"""Tests für die Kontoverwaltung.

Diese Endpunkte fehlten, und das war ein Blocker: Nach einer frischen
Installation legt `einrichten.sh` ein leeres Schema an und `nutzer.py`
einen Nutzer -- danach gab es keinen Weg mehr, das eigene Handelskonto
einzutragen, ausser von Hand per SQL.

Der Schwerpunkt liegt auf den Grenzwerten. Sie sind kein Beiwerk, sondern
der Grund, warum es die Regel-Puffer überhaupt gibt: Ein falsch
eingetragenes Limit zeigt einen Puffer, den es nicht gibt -- und das ist
schlimmer als gar keiner, weil man sich darauf verlässt.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tradediary.db import models as db

from .test_api_schreiben import PASSWORT, client, roh_client, zweiter_nutzer  # noqa: F401

NEU = {
    "label": "Alpha 100k · Funded",
    "broker": "Alpha Capital",
    "server": "AlphaCapital-Live02",
    "currency": "EUR",
    "phase": "funded",
    "status": "aktiv",
    "starting_balance": 100000,
    "daily_loss_limit": 5000,
    "max_loss_limit": 10000,
    "consistency_limit": 0.4,
    "profit_target": 10000,
}


# ---------------------------------------------------------------------------
# Anlegen
# ---------------------------------------------------------------------------

def test_konto_anlegen(client):
    antwort = client.post("/api/accounts", json=NEU)
    assert antwort.status_code == 201, antwort.text
    daten = antwort.json()
    assert daten["label"] == "Alpha 100k · Funded"
    assert daten["phase"] == "funded"
    assert daten["limits"]["daily_loss"] == 5000
    assert daten["limits"]["consistency"] == 0.4
    assert daten["deal_count"] == 0


def test_das_neue_konto_taucht_in_der_liste_auf(client):
    client.post("/api/accounts", json=NEU)
    labels = [k["label"] for k in client.get("/api/accounts").json()]
    assert "Alpha 100k · Funded" in labels


def test_ein_konto_gehoert_dem_der_es_anlegt(client):
    """Sonst könnte man Konten in fremde Nutzer schreiben."""
    client.post("/api/accounts", json=NEU)
    with client.session_factory() as s:
        konto = s.scalars(
            select(db.Account).where(db.Account.label == NEU["label"])
        ).one()
    assert konto.user_id == 1


def test_ohne_anmeldung_kein_konto(roh_client):
    assert roh_client.post("/api/accounts", json=NEU).status_code == 401


def test_bezeichnung_ist_pflicht(client):
    for leer in ("", "   "):
        antwort = client.post("/api/accounts", json={**NEU, "label": leer})
        assert antwort.status_code == 400


def test_waehrung_wird_gross_geschrieben(client):
    """Sonst stünden 'eur' und 'EUR' als zwei Währungen nebeneinander."""
    daten = client.post("/api/accounts", json={**NEU, "currency": "usd"}).json()
    assert daten["currency"] == "USD"


# ---------------------------------------------------------------------------
# Die Grenzwerte -- jede Prüfung steht für eine trügerische Zahl
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("feld", ["daily_loss_limit", "max_loss_limit", "profit_target"])
def test_ein_limit_von_null_wird_abgelehnt(client, feld):
    """Null wäre kein Limit, sondern ein vom ersten Augenblick gerissenes.

    Der Puffer stünde dauerhaft auf null, und die Oberfläche zeigte eine
    Regelverletzung, die es nicht gibt.
    """
    antwort = client.post("/api/accounts", json={**NEU, feld: 0})
    assert antwort.status_code == 400
    assert "null" in antwort.json()["detail"]


@pytest.mark.parametrize("feld", ["daily_loss_limit", "max_loss_limit"])
def test_ein_negatives_limit_wird_abgelehnt(client, feld):
    assert client.post("/api/accounts", json={**NEU, feld: -100}).status_code == 400


@pytest.mark.parametrize("wert", [40, 100, 1.5, 0, -0.4])
def test_konsistenz_als_prozentzahl_wird_abgelehnt(client, wert):
    """Der wahrscheinlichste Eingabefehler.

    Alpha Capital nennt die Regel "40 %". Wer 40 einträgt statt 0.4,
    bekäme eine Konsistenzregel, die nie greift -- und merkte es erst,
    wenn die Auszahlung abgelehnt wird.
    """
    antwort = client.post("/api/accounts", json={**NEU, "consistency_limit": wert})
    assert antwort.status_code == 400
    detail = antwort.json()["detail"]
    assert "0,4" in detail, "die Meldung muss sagen, wie es richtig geht"
    # Und sie nennt das Feld so, wie es in der Oberflaeche heisst.
    assert "Konsistenzregel" in detail
    assert "consistency_limit" not in detail


def test_tagesverlust_ueber_gesamtverlust_wird_abgelehnt(client):
    """Sonst wäre das Konto verloren, bevor das Tageslimit je greift."""
    antwort = client.post(
        "/api/accounts",
        json={**NEU, "daily_loss_limit": 10000, "max_loss_limit": 5000},
    )
    assert antwort.status_code == 400


def test_gleiche_limits_sind_erlaubt(client):
    """Ungewöhnlich, aber nicht falsch -- manche Anbieter machen das so."""
    antwort = client.post(
        "/api/accounts",
        json={**NEU, "daily_loss_limit": 5000, "max_loss_limit": 5000},
    )
    assert antwort.status_code == 201


def test_negatives_startkapital_wird_abgelehnt(client):
    assert client.post(
        "/api/accounts", json={**NEU, "starting_balance": -1}
    ).status_code == 400


def test_ohne_limits_geht_auch(client):
    """Ein normales Broker-Konto hat keine Prop-Grenzen.

    Die Oberfläche zeigt dann keinen Puffer statt eines erfundenen.
    """
    antwort = client.post(
        "/api/accounts",
        json={
            "label": "Privatkonto",
            "phase": "live",
            "starting_balance": 5000,
            "daily_loss_limit": None,
            "max_loss_limit": None,
            "consistency_limit": None,
            "profit_target": None,
        },
    )
    assert antwort.status_code == 201
    assert antwort.json()["limits"]["daily_loss"] is None


@pytest.mark.parametrize("feld, wert", [("phase", "quatsch"), ("status", "quatsch")])
def test_unbekannte_phase_oder_status(client, feld, wert):
    antwort = client.post("/api/accounts", json={**NEU, feld: wert})
    assert antwort.status_code == 400
    assert "quatsch" in antwort.json()["detail"]


@pytest.mark.parametrize(
    "feld, name",
    [
        ("daily_loss_limit", "Tagesverlust"),
        ("max_loss_limit", "Gesamtverlust"),
        ("profit_target", "Gewinnziel"),
    ],
)
def test_fehlermeldungen_nennen_das_feld_wie_die_oberflaeche(client, feld, name):
    """Wer gerade in ein Feld namens "Tagesverlust" getippt hat, findet
    mit "daily_loss_limit" die Stelle nicht wieder.

    Im Browser aufgefallen: Die Meldung zeigte den rohen API-Namen.
    """
    antwort = client.post("/api/accounts", json={**NEU, feld: 0})
    assert antwort.status_code == 400
    detail = antwort.json()["detail"]
    assert name in detail
    assert feld not in detail


# ---------------------------------------------------------------------------
# Ändern
# ---------------------------------------------------------------------------

def test_limit_nachtragen(client):
    tid = client.post("/api/accounts", json=NEU).json()["id"]
    antwort = client.patch(f"/api/accounts/{tid}", json={"daily_loss_limit": 4000})
    assert antwort.json()["limits"]["daily_loss"] == 4000


def test_patch_laesst_weggelassene_felder_in_ruhe(client):
    """Dieselbe Regel wie bei den Trades.

    Wer nur den Status auf 'bestanden' setzt, darf dabei nicht die
    Grenzwerte verlieren -- sonst stünde das Konto ohne Puffer da.
    """
    tid = client.post("/api/accounts", json=NEU).json()["id"]
    daten = client.patch(f"/api/accounts/{tid}", json={"status": "bestanden"}).json()
    assert daten["status"] == "bestanden"
    assert daten["limits"]["daily_loss"] == 5000
    assert daten["limits"]["max_loss"] == 10000
    assert daten["starting_balance"] == 100000


def test_aenderung_wird_gegen_die_gespeicherten_werte_geprueft(client):
    """Wer nur das Tageslimit ändert, muss trotzdem gegen den
    gespeicherten Gesamtverlust geprüft werden."""
    tid = client.post("/api/accounts", json=NEU).json()["id"]
    antwort = client.patch(f"/api/accounts/{tid}", json={"daily_loss_limit": 99999})
    assert antwort.status_code == 400


def test_fremdes_konto_ist_nicht_aenderbar(client):
    fremd = zweiter_nutzer(client)
    antwort = client.patch(
        f"/api/accounts/{fremd['account_id']}", json={"label": "gekapert"}
    )
    assert antwort.status_code == 404

    with client.session_factory() as s:
        assert s.get(db.Account, fremd["account_id"]).label == "Fremdkonto"


def test_die_wirkung_auf_den_regel_puffer(client):
    """Die Probe aufs Ganze: Ein geändertes Limit ändert den Puffer.

    Genau dafür gibt es die Grenzwerte -- wenn die Änderung nicht
    durchschlägt, ist die ganze Eingabe wirkungslos.
    """
    vorher = client.get("/api/overview?account_id=1").json()["rules"]["max_loss"]
    client.patch("/api/accounts/1", json={"max_loss_limit": 7500})
    nachher = client.get("/api/overview?account_id=1").json()["rules"]["max_loss"]

    assert nachher["limit"] == 7500
    assert nachher["limit"] != vorher["limit"]
    assert nachher["remaining"] != vorher["remaining"]


# ---------------------------------------------------------------------------
# Löschen
# ---------------------------------------------------------------------------

def test_leeres_konto_laesst_sich_loeschen(client):
    tid = client.post("/api/accounts", json=NEU).json()["id"]
    assert client.delete(f"/api/accounts/{tid}").status_code == 200
    assert tid not in [k["id"] for k in client.get("/api/accounts").json()]


def test_konto_mit_trades_wird_nicht_geloescht(client):
    """Handelshistorie steht nirgends sonst.

    Ein verlorenes Challenge-Konto gehört auf 'verloren', nicht in den
    Papierkorb -- seine Trades sind die Lehre, für die man bezahlt hat.
    """
    antwort = client.delete("/api/accounts/1")
    assert antwort.status_code == 409
    assert "Ausführungen" in antwort.json()["detail"]

    with client.session_factory() as s:
        assert s.get(db.Account, 1) is not None


def test_fremdes_konto_wird_nicht_geloescht(client):
    fremd = zweiter_nutzer(client)
    # Dasselbe 404 wie bei "gibt es nicht" -- sonst liesse sich durch
    # Probieren zählen, wie viele Konten es gibt.
    assert client.delete(f"/api/accounts/{fremd['account_id']}").status_code == 404
    with client.session_factory() as s:
        assert s.get(db.Account, fremd["account_id"]) is not None


def test_beim_loeschen_gehen_die_marken_mit(client):
    """Eine Marke ohne Konto hat keine Bedeutung -- und wäre ein
    Zugang, der auf nichts zeigt."""
    tid = client.post("/api/accounts", json=NEU).json()["id"]
    with client.session_factory() as s:
        s.add(
            db.Zugangsmarke(
                user_id=1, account_id=tid, token_hash="b" * 64, label="Test"
            )
        )
        s.commit()

    client.delete(f"/api/accounts/{tid}")

    with client.session_factory() as s:
        uebrig = s.scalars(
            select(db.Zugangsmarke).where(db.Zugangsmarke.account_id == tid)
        ).all()
    assert uebrig == []


# ---------------------------------------------------------------------------
# Der Weg nach der Installation
# ---------------------------------------------------------------------------

def test_frischer_nutzer_kann_sich_ein_konto_anlegen(client):
    """Der Fall, für den es diese Endpunkte gibt.

    Nach `einrichten.sh` gibt es einen Nutzer und sonst nichts. Ohne
    diesen Weg wäre die App an dieser Stelle unbenutzbar.
    """
    from tradediary.sicherheit import hashe_passwort

    with client.session_factory() as s:
        s.add(
            db.User(id=9, email="frisch@example.invalid",
                    password_hash=hashe_passwort(PASSWORT))
        )
        s.commit()

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "frisch@example.invalid", "password": PASSWORT},
    )

    assert client.get("/api/accounts").json() == []

    angelegt = client.post("/api/accounts", json=NEU)
    assert angelegt.status_code == 201

    konten = client.get("/api/accounts").json()
    assert len(konten) == 1
    assert konten[0]["label"] == NEU["label"]

    # Und die Übersicht funktioniert damit -- ohne Trades, aber ohne Fehler.
    uebersicht = client.get(f"/api/overview?account_id={konten[0]['id']}")
    assert uebersicht.status_code == 200
    assert uebersicht.json()["metrics"]["trade_count"] == 0

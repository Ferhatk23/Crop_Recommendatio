"""Tests für Anmeldung und Zugriffsschutz.

Zwei Fragen, die es ohne Anmeldung nicht gab und die jetzt beide
beantwortet sein müssen:

1. Kommt jemand *ohne* Anmeldung an Daten?
2. Kommt ein angemeldeter Nutzer an die Daten eines *anderen*?

Die zweite ist die unangenehmere. Sie fällt bei einem einzigen Nutzer nie
auf -- und genau so war es hier: `/api/accounts` gab jedes Konto in der
Datenbank zurück, `/api/tags` ohne `account_id` die Tags aller Nutzer.
Solange nur einer existierte, sah alles richtig aus.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tradediary.db import models as db
from tradediary.sicherheit import hashe_passwort, marken_hash

from .test_api_schreiben import PASSWORT, client, roh_client, zweiter_nutzer  # noqa: F401


# ---------------------------------------------------------------------------
# Anmelden und abmelden
# ---------------------------------------------------------------------------

def test_anmelden_setzt_ein_cookie(roh_client):
    antwort = roh_client.post(
        "/api/auth/login",
        json={"email": "test@example.invalid", "password": PASSWORT},
    )
    assert antwort.status_code == 200
    assert antwort.json()["email"] == "test@example.invalid"
    assert "tradediary_sitzung" in antwort.cookies


def test_das_cookie_ist_httponly(roh_client):
    """JavaScript darf die Marke nicht lesen können.

    Sonst könnte ein eingeschleustes Skript sie ausleiten und die Sitzung
    anderswo weiterverwenden -- das Cookie wäre dann so gut wie das
    Passwort selbst.
    """
    antwort = roh_client.post(
        "/api/auth/login",
        json={"email": "test@example.invalid", "password": PASSWORT},
    )
    gesetzt = antwort.headers["set-cookie"].lower()
    assert "httponly" in gesetzt
    assert "samesite" in gesetzt


def test_das_passwort_steht_nicht_in_der_antwort(client):
    text = client.get("/api/auth/me").text
    assert PASSWORT not in text
    assert "password" not in text.lower()


def test_falsches_passwort_wird_abgelehnt(roh_client):
    antwort = roh_client.post(
        "/api/auth/login",
        json={"email": "test@example.invalid", "password": "falsch aber lang"},
    )
    assert antwort.status_code == 401


def test_unbekannte_und_falsche_email_antworten_gleich(roh_client):
    """Sonst ließe sich herausfinden, welche Adressen es gibt.

    Wer weiß, dass eine Adresse existiert, hat die halbe Arbeit erledigt --
    und kann sich auf das Erraten des Passworts beschränken.
    """
    falsch = roh_client.post(
        "/api/auth/login",
        json={"email": "test@example.invalid", "password": "falsch aber lang"},
    )
    unbekannt = roh_client.post(
        "/api/auth/login",
        json={"email": "gibtsnicht@example.invalid", "password": "falsch aber lang"},
    )
    assert falsch.status_code == unbekannt.status_code == 401
    assert falsch.json()["detail"] == unbekannt.json()["detail"]


def test_email_ist_nicht_gross_klein_empfindlich(roh_client):
    antwort = roh_client.post(
        "/api/auth/login",
        json={"email": "  TEST@Example.Invalid  ", "password": PASSWORT},
    )
    assert antwort.status_code == 200


def test_abmelden_beendet_die_sitzung_auch_serverseitig(client):
    """Nur das Cookie zu löschen reichte nicht.

    Wer die Marke vorher abgegriffen hat, könnte sie sonst weiter
    verwenden -- das Abmelden wäre reine Kosmetik im Browser.
    """
    with client.session_factory() as s:
        marke_vorher = s.scalars(select(db.Sitzung)).one().token_hash

    assert client.post("/api/auth/logout").status_code == 200

    with client.session_factory() as s:
        assert s.scalars(select(db.Sitzung)).all() == []

    # Und die alte Marke wirkt nicht mehr, auch wenn man sie noch hat.
    client.cookies.set("tradediary_sitzung", "egal")
    assert client.get("/api/auth/me").status_code == 401
    assert marke_vorher  # nur zur Klarheit: es gab sie


def test_abgelaufene_sitzung_wird_abgewiesen_und_geraeumt(client):
    with client.session_factory() as s:
        sitzung = s.scalars(select(db.Sitzung)).one()
        sitzung.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.commit()

    assert client.get("/api/auth/me").status_code == 401

    with client.session_factory() as s:
        assert s.scalars(select(db.Sitzung)).all() == [], "abgelaufen, aber noch da"


def test_erfundene_marke_wirkt_nicht(roh_client):
    roh_client.cookies.set("tradediary_sitzung", "voellig-ausgedacht")
    assert roh_client.get("/api/auth/me").status_code == 401


def test_die_marke_steht_nicht_im_klartext_in_der_datenbank(client):
    """Ein Blick in die Datenbank darf keine gültige Sitzung hergeben."""
    marke = client.cookies["tradediary_sitzung"]
    with client.session_factory() as s:
        sitzung = s.scalars(select(db.Sitzung)).one()
    assert sitzung.token_hash != marke
    assert sitzung.token_hash == marken_hash(marke)


def test_zu_viele_fehlversuche_werden_gebremst(roh_client):
    for _ in range(8):
        roh_client.post(
            "/api/auth/login",
            json={"email": "test@example.invalid", "password": "falsch aber lang"},
        )
    gebremst = roh_client.post(
        "/api/auth/login",
        json={"email": "test@example.invalid", "password": PASSWORT},
    )
    assert gebremst.status_code == 429


def test_erfolgreiche_anmeldung_loescht_die_fehlversuche(roh_client):
    for _ in range(3):
        roh_client.post(
            "/api/auth/login",
            json={"email": "test@example.invalid", "password": "falsch aber lang"},
        )
    assert roh_client.post(
        "/api/auth/login",
        json={"email": "test@example.invalid", "password": PASSWORT},
    ).status_code == 200
    assert roh_client.main._fehlversuche.get("test@example.invalid") in (None, [])


# ---------------------------------------------------------------------------
# Ohne Anmeldung geht nichts
# ---------------------------------------------------------------------------

GESCHUETZT = [
    ("get", "/api/accounts"),
    ("get", "/api/overview"),
    ("get", "/api/trades"),
    ("get", "/api/trades/1"),
    ("get", "/api/calendar?year=2026&month=3"),
    ("get", "/api/reports/weekday"),
    ("get", "/api/symbols"),
    ("get", "/api/tags"),
    ("get", "/api/playbooks"),
    ("get", "/api/journal/2026-03-02?account_id=1"),
    ("get", "/api/auth/me"),
    ("get", "/api/auth/sessions"),
    ("patch", "/api/trades/1"),
    ("put", "/api/trades/1/tags"),
    ("put", "/api/journal/2026-03-02?account_id=1"),
    ("post", "/api/import/csv"),
    ("delete", "/api/auth/sessions/1"),
]


@pytest.mark.parametrize("verb, pfad", GESCHUETZT)
def test_ohne_anmeldung_kein_zugriff(roh_client, verb, pfad):
    antwort = getattr(roh_client, verb)(
        pfad, **({"json": {}} if verb in ("patch", "put", "post") else {})
    )
    assert antwort.status_code == 401, f"{verb.upper()} {pfad} antwortet ohne Anmeldung"


def test_health_geht_ohne_anmeldung_verraet_aber_nichts(roh_client):
    """Ein Überwachungsdienst muss wissen, ob die App antwortet.

    Er muss nicht wissen, wie viele Trades darin stehen -- das stand
    vorher drin und verriet einem Unangemeldeten, wie aktiv das Konto ist.
    """
    antwort = roh_client.get("/api/health")
    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Fremde Daten bleiben fremd
# ---------------------------------------------------------------------------

def test_konten_liste_zeigt_nur_die_eigenen(client):
    """Hier stand `select(db.Account)` ohne Bedingung.

    Mit einem einzigen Nutzer war das richtig. Mit zweien wäre es die
    Preisgabe jedes fremden Kontos gewesen.
    """
    zweiter_nutzer(client)
    konten = client.get("/api/accounts").json()
    assert [k["id"] for k in konten] == [1]


def test_trades_ohne_filter_zeigen_nur_eigene(client):
    """Der gefährlichste Fall: kein Filter gesetzt.

    Vorher hieß "kein account_id" schlicht "keine Bedingung" -- und damit
    alle Trades aller Nutzer.
    """
    fremd = zweiter_nutzer(client)
    trades = client.get("/api/trades").json()["trades"]
    assert trades, "eigene Trades fehlen"
    assert all(t["id"] != fremd["trade_id"] for t in trades)


def test_fremdes_konto_als_filter_wird_abgewiesen(client):
    fremd = zweiter_nutzer(client)
    for pfad in (
        f"/api/trades?account_id={fremd['account_id']}",
        f"/api/overview?account_id={fremd['account_id']}",
        f"/api/calendar?year=2026&month=3&account_id={fremd['account_id']}",
        f"/api/reports/weekday?account_id={fremd['account_id']}",
        f"/api/symbols?account_id={fremd['account_id']}",
        f"/api/tags?account_id={fremd['account_id']}",
        f"/api/playbooks?account_id={fremd['account_id']}",
    ):
        assert client.get(pfad).status_code == 404, pfad


def test_fremder_trade_ist_nicht_lesbar(client):
    fremd = zweiter_nutzer(client)
    assert client.get(f"/api/trades/{fremd['trade_id']}").status_code == 404


def test_fremder_trade_ist_nicht_schreibbar(client):
    """Der schlimmere Fall: nicht nur lesen, sondern verändern."""
    fremd = zweiter_nutzer(client)
    tid = fremd["trade_id"]

    assert client.patch(f"/api/trades/{tid}", json={"note": "fremd"}).status_code == 404
    assert client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "fremd", "kind": "setup"}]},
    ).status_code == 404

    with client.session_factory() as s:
        assert s.get(db.Trade, tid).note is None


def test_fremdes_journal_ist_nicht_erreichbar(client):
    fremd = zweiter_nutzer(client)
    konto = fremd["account_id"]
    assert client.get(f"/api/journal/2026-03-02?account_id={konto}").status_code == 404
    assert client.put(
        f"/api/journal/2026-03-02?account_id={konto}", json={"body": "fremd"}
    ).status_code == 404


def test_import_in_fremdes_konto_wird_abgewiesen(client):
    fremd = zweiter_nutzer(client)
    antwort = client.post(
        "/api/import/csv",
        json={"account_id": fremd["account_id"], "content": "ticket,symbol\n1,EURUSD\n"},
    )
    assert antwort.status_code == 404


def test_fremde_tags_tauchen_nicht_auf(client):
    """`/api/tags` ohne `account_id` gab vorher die Tags aller Nutzer."""
    fremd = zweiter_nutzer(client)
    with client.session_factory() as s:
        marke = db.Tag(user_id=2, label="Fremdsetup", kind=db.TagArt.SETUP)
        s.add(marke)
        s.flush()
        s.add(db.TradeTag(trade_id=fremd["trade_id"], tag_id=marke.id))
        s.commit()

    assert "Fremdsetup" not in [t["label"] for t in client.get("/api/tags").json()]


def test_fremde_playbooks_tauchen_nicht_auf(client):
    zweiter_nutzer(client)
    with client.session_factory() as s:
        s.add(db.Playbook(user_id=2, name="Fremdes Buch"))
        s.commit()

    assert "Fremdes Buch" not in [
        b["name"] for b in client.get("/api/playbooks").json()
    ]


def test_nutzer_ohne_konto_bekommt_nichts_statt_alles(client):
    """Die Kante, an der eine leere Liste zur fehlenden Bedingung wird.

    Wer keine Konten hat, darf keine Trades sehen. Ein `IN ()` mit leerer
    Liste, das versehentlich weggelassen wird, liefert dagegen *alles*.
    """
    with client.session_factory() as s:
        s.add(
            db.User(id=3, email="leer@example.invalid", password_hash=hashe_passwort(PASSWORT))
        )
        s.commit()

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "leer@example.invalid", "password": PASSWORT},
    )

    assert client.get("/api/accounts").json() == []
    assert client.get("/api/trades").json()["trades"] == []
    assert client.get("/api/symbols").json() == []
    assert client.get("/api/reports/weekday").json()["total_trades"] == 0


# ---------------------------------------------------------------------------
# Sitzungsübersicht
# ---------------------------------------------------------------------------

def test_sitzungen_auflisten_und_beenden(client):
    """Ein verlorenes iPad muss sich abmelden lassen."""
    sitzungen = client.get("/api/auth/sessions").json()
    assert len(sitzungen) == 1

    assert client.delete(f"/api/auth/sessions/{sitzungen[0]['id']}").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_fremde_sitzung_kann_nicht_beendet_werden(client):
    zweiter_nutzer(client)
    with client.session_factory() as s:
        s.add(
            db.Sitzung(
                id=999,
                user_id=2,
                token_hash="a" * 64,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        s.commit()

    assert client.delete("/api/auth/sessions/999").status_code == 404

    with client.session_factory() as s:
        assert s.get(db.Sitzung, 999) is not None, "fremde Sitzung wurde beendet"

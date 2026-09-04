"""Tests für die schreibenden Endpunkte.

Hier wird die App vom Betrachter zum Journal, und hier kann man zum
ersten Mal etwas kaputt machen, das nicht aus den Deals nachwächst. Was
der Nutzer selbst geschrieben hat, gibt es genau einmal.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
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
def client(tmp_path, monkeypatch):
    """Eine eigene Datenbank je Test, dazu die App darauf.

    Die App liest ihre Datenbank-URL beim Import aus der Umgebung, also
    muss die vor dem Import stehen -- und das Modul darf nicht aus einem
    früheren Test übrigbleiben.
    """
    import importlib
    import sys

    url = f"sqlite:///{tmp_path/'test.db'}"
    monkeypatch.setenv("TRADEDIARY_DB", url)
    sys.modules.pop("tradediary.api.main", None)
    main = importlib.import_module("tradediary.api.main")

    engine = engine_bauen(url)
    schema_anlegen(engine)
    Session_ = session_factory(engine)
    with Session_() as s:
        s.add(db.User(id=1, email="test@example.invalid", password_hash="x"))
        s.add(db.Account(id=1, user_id=1, label="Testkonto"))
        s.commit()
        deals_speichern(
            s,
            1,
            [
                open_long(1, 100, "1.00", "1.08000", 0),
                close_long(2, 100, "1.00", "1.08300", 30, profit=300),
                open_short(3, 200, "1.00", "1.26000", 60),
                close_short(4, 200, "1.00", "1.25800", 90, profit=200),
            ],
        )
        trades_neu_berechnen(s, 1)

    with TestClient(main.app) as c:
        c.session_factory = Session_  # type: ignore[attr-defined]
        yield c

    sys.modules.pop("tradediary.api.main", None)


def _erste_id(client) -> int:
    return client.get("/api/trades").json()["trades"][0]["id"]


# ---------------------------------------------------------------------------
# Notiz
# ---------------------------------------------------------------------------

def test_notiz_schreiben_und_lesen(client):
    tid = _erste_id(client)
    antwort = client.patch(f"/api/trades/{tid}", json={"note": "Zu früh raus."})
    assert antwort.status_code == 200
    assert antwort.json()["note"] == "Zu früh raus."
    assert client.get(f"/api/trades/{tid}").json()["note"] == "Zu früh raus."


def test_leere_notiz_wird_zu_null(client):
    """Leer heißt "keine Notiz", nicht "eine leere Notiz".

    Sonst gäbe es zwei Zustände, die für den Nutzer derselbe sind -- und
    die Oberfläche müsste beide behandeln.
    """
    tid = _erste_id(client)
    client.patch(f"/api/trades/{tid}", json={"note": "etwas"})
    antwort = client.patch(f"/api/trades/{tid}", json={"note": "   "})
    assert antwort.json()["note"] is None


def test_patch_laesst_weggelassene_felder_in_ruhe(client):
    """Der Kern der PATCH-Regel.

    Die Oberfläche speichert Notiz und Playbook getrennt. Setzte ein
    fehlendes Feld auf `null`, löschte jedes Notiz-Speichern still die
    Playbook-Zuordnung.
    """
    tid = _erste_id(client)

    with client.session_factory() as s:  # type: ignore[attr-defined]
        buch = db.Playbook(user_id=1, name="London Breakout")
        s.add(buch)
        s.commit()
        buch_id = buch.id

    client.patch(f"/api/trades/{tid}", json={"playbook_id": buch_id})
    antwort = client.patch(f"/api/trades/{tid}", json={"note": "Nur die Notiz."})

    daten = antwort.json()
    assert daten["note"] == "Nur die Notiz."
    with client.session_factory() as s:  # type: ignore[attr-defined]
        assert s.get(db.Trade, tid).playbook_id == buch_id


def test_ausdrueckliches_null_loescht(client):
    tid = _erste_id(client)
    client.patch(f"/api/trades/{tid}", json={"note": "etwas"})
    assert client.patch(f"/api/trades/{tid}", json={"note": None}).json()["note"] is None


def test_notiz_an_unbekanntem_trade(client):
    assert client.patch("/api/trades/9999", json={"note": "x"}).status_code == 404


def test_zu_lange_notiz_wird_abgelehnt(client):
    tid = _erste_id(client)
    antwort = client.patch(f"/api/trades/{tid}", json={"note": "x" * 20_001})
    assert antwort.status_code == 400


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def test_tags_setzen(client):
    tid = _erste_id(client)
    antwort = client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "Breakout", "kind": "setup"},
                       {"label": "zu früh raus", "kind": "fehler"}]},
    )
    assert antwort.status_code == 200
    marken = {(t["label"], t["kind"]) for t in antwort.json()["tags"]}
    assert marken == {("Breakout", "setup"), ("zu früh raus", "fehler")}


def test_tags_setzen_ist_wiederholbar(client):
    """Zweimal dieselbe Liste ergibt zweimal dasselbe.

    Deshalb PUT mit der vollständigen Liste statt getrenntem Hinzufügen
    und Entfernen: Bei dem hinge das Ergebnis an der Reihenfolge der
    Aufrufe, und ein doppelt abgeschickter Klick legte einen Tag zweimal an.
    """
    tid = _erste_id(client)
    rumpf = {"tags": [{"label": "Breakout", "kind": "setup"}]}
    erste = client.put(f"/api/trades/{tid}/tags", json=rumpf).json()
    zweite = client.put(f"/api/trades/{tid}/tags", json=rumpf).json()
    assert erste["tags"] == zweite["tags"]
    assert len(zweite["tags"]) == 1


def test_bekannter_tag_wird_wiederverwendet(client):
    """Dasselbe Setup an zwei Trades ist eine Marke, nicht zwei.

    Sonst stünde "Breakout" zweimal im Report, mit je der Hälfte der
    Trades -- und beide Zeilen wären für sich plausibel.
    """
    ids = [t["id"] for t in client.get("/api/trades").json()["trades"][:2]]
    for tid in ids:
        client.put(
            f"/api/trades/{tid}/tags",
            json={"tags": [{"label": "Breakout", "kind": "setup"}]},
        )

    with client.session_factory() as s:  # type: ignore[attr-defined]
        marken = s.scalars(select(db.Tag).where(db.Tag.label == "Breakout")).all()
    assert len(marken) == 1

    alle = client.get("/api/tags").json()
    breakout = [t for t in alle if t["label"] == "Breakout"]
    assert len(breakout) == 1
    assert breakout[0]["count"] == 2


def test_ungenutzte_tags_stehen_nicht_in_den_vorschlaegen(client):
    """Die Liste ist zum Wiederverwenden da.

    An einer Bezeichnung mit null Trades gibt es nichts wiederzuverwenden.
    Bliebe sie stehen, sammelte sich dort jeder Tippfehler, den man je
    vergeben und wieder entfernt hat.
    """
    tid = _erste_id(client)
    client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "Vertipper", "kind": "setup"}]},
    )
    assert "Vertipper" in [t["label"] for t in client.get("/api/tags").json()]

    client.put(f"/api/trades/{tid}/tags", json={"tags": []})

    assert "Vertipper" not in [t["label"] for t in client.get("/api/tags").json()]
    # Gelöscht ist sie aber nicht -- nur nicht mehr vorgeschlagen.
    mit = client.get("/api/tags?ungenutzte=true").json()
    assert "Vertipper" in [t["label"] for t in mit]


def test_erneutes_tippen_findet_die_alte_marke_wieder(client):
    """Kein Datenverlust durch das Ausblenden.

    Wer dieselbe Bezeichnung noch einmal vergibt, bekommt dieselbe Marke
    -- und nicht eine zweite mit derselben Aufschrift.
    """
    tid = _erste_id(client)
    rumpf = {"tags": [{"label": "Breakout", "kind": "setup"}]}
    client.put(f"/api/trades/{tid}/tags", json=rumpf)
    erste = client.get(f"/api/trades/{tid}").json()["tags"][0]["id"]

    client.put(f"/api/trades/{tid}/tags", json={"tags": []})
    client.put(f"/api/trades/{tid}/tags", json=rumpf)

    assert client.get(f"/api/trades/{tid}").json()["tags"][0]["id"] == erste


def test_tags_entfernen_mit_leerer_liste(client):
    tid = _erste_id(client)
    client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "Breakout", "kind": "setup"}]},
    )
    antwort = client.put(f"/api/trades/{tid}/tags", json={"tags": []})
    assert antwort.json()["tags"] == []


def test_doppelte_in_der_eingabe_fallen_zusammen(client):
    tid = _erste_id(client)
    antwort = client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "Breakout", "kind": "setup"},
                       {"label": " Breakout ", "kind": "setup"}]},
    )
    assert len(antwort.json()["tags"]) == 1


def test_gleiche_bezeichnung_verschiedene_art_bleiben_getrennt(client):
    """"Rache-Trade" als Fehler ist nicht dasselbe wie als Emotion."""
    tid = _erste_id(client)
    antwort = client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "Rache-Trade", "kind": "fehler"},
                       {"label": "Rache-Trade", "kind": "emotion"}]},
    )
    assert len(antwort.json()["tags"]) == 2


def test_unbekannte_tag_art_wird_abgelehnt(client):
    tid = _erste_id(client)
    antwort = client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "x", "kind": "quatsch"}]},
    )
    assert antwort.status_code == 400
    assert "quatsch" in antwort.json()["detail"]


def test_leere_bezeichnung_wird_uebergangen(client):
    tid = _erste_id(client)
    antwort = client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "  ", "kind": "setup"},
                       {"label": "Pullback", "kind": "setup"}]},
    )
    assert [t["label"] for t in antwort.json()["tags"]] == ["Pullback"]


def test_tags_ueberleben_einen_neuaufbau(client):
    """Die Probe aufs Ganze -- über die HTTP-Schnittstelle.

    Genau hier lag der Fehler: Der Neuaufbau löschte die Trades per
    Bulk-DELETE, und die Tag-Verknüpfungen blieben auf gelöschten IDs
    zurück.
    """
    tid = _erste_id(client)
    client.put(
        f"/api/trades/{tid}/tags",
        json={"tags": [{"label": "Breakout", "kind": "setup"}]},
    )
    vorher = client.get(f"/api/trades/{tid}").json()

    with client.session_factory() as s:  # type: ignore[attr-defined]
        trades_neu_berechnen(s, 1)

    danach = [
        t for t in client.get("/api/trades").json()["trades"]
        if t["position_id"] == vorher["position_id"]
    ]
    assert len(danach) == 1
    assert [t["label"] for t in danach[0]["tags"]] == ["Breakout"]


# ---------------------------------------------------------------------------
# Auswertung nach Tags
# ---------------------------------------------------------------------------

def test_report_nach_setup(client):
    """Wofür man überhaupt taggt: Welches Setup verdient Geld?"""
    ids = [t["id"] for t in client.get("/api/trades").json()["trades"]]
    client.put(
        f"/api/trades/{ids[0]}/tags",
        json={"tags": [{"label": "Breakout", "kind": "setup"}]},
    )

    bericht = client.get("/api/reports/setup?min_sample=1").json()
    gruppen = {g["key"]: g["trades"] for g in bericht["groups"]}
    assert gruppen["Breakout"] == 1
    assert bericht["overlapping"] is True


def test_ungetaggte_trades_bekommen_eine_eigene_gruppe(client):
    """Sie wegzulassen wäre die stillste Art, sich selbst zu belügen.

    Der Report sähe aus wie eine Aussage über alle Trades, beschriebe
    aber nur die schon eingeordneten -- und "Breakout verdient Geld"
    stimmte dann vielleicht nur, weil die schlechten nie getaggt wurden.
    """
    ids = [t["id"] for t in client.get("/api/trades").json()["trades"]]
    client.put(
        f"/api/trades/{ids[0]}/tags",
        json={"tags": [{"label": "Breakout", "kind": "setup"}]},
    )

    bericht = client.get("/api/reports/setup?min_sample=1").json()
    gruppen = {g["key"]: g["trades"] for g in bericht["groups"]}
    assert "ohne Setup" in gruppen
    assert gruppen["ohne Setup"] == bericht["total_trades"] - 1


def test_mehrere_tags_zaehlen_in_mehreren_gruppen(client):
    """Und die Antwort sagt das ausdrücklich.

    Ohne `overlapping` addierte ein Leser die Gruppen und käme auf mehr
    Trades, als es gibt.
    """
    ids = [t["id"] for t in client.get("/api/trades").json()["trades"]]
    client.put(
        f"/api/trades/{ids[0]}/tags",
        json={"tags": [{"label": "Breakout", "kind": "setup"},
                       {"label": "zu früh raus", "kind": "fehler"}]},
    )

    bericht = client.get("/api/reports/tag?min_sample=1").json()
    summe = sum(g["trades"] for g in bericht["groups"])
    assert bericht["overlapping"] is True
    assert summe > bericht["total_trades"]


def test_einwertige_rubriken_ueberlappen_nicht(client):
    """Bei Wochentag & Co. bleibt die Gruppierung eine Aufteilung."""
    bericht = client.get("/api/reports/weekday?min_sample=1").json()
    assert bericht["overlapping"] is False
    summe = sum(g["trades"] for g in bericht["groups"])
    assert summe == bericht["total_trades"]


def test_unbekannte_rubrik_nennt_die_verfuegbaren(client):
    antwort = client.get("/api/reports/quatsch")
    assert antwort.status_code == 400
    detail = antwort.json()["detail"]
    assert "setup" in detail and "weekday" in detail


# ---------------------------------------------------------------------------
# Tagesjournal
# ---------------------------------------------------------------------------

def test_journal_fehlender_eintrag_ist_leer_kein_fehler(client):
    """Die meisten Tage haben keinen Eintrag. Das ist kein Fehlerfall."""
    antwort = client.get("/api/journal/2026-03-02?account_id=1")
    assert antwort.status_code == 200
    assert antwort.json() == {
        "date": "2026-03-02", "body": "", "mood": None, "updated_at": None
    }


def test_journal_schreiben_und_lesen(client):
    antwort = client.put(
        "/api/journal/2026-03-02?account_id=1",
        json={"body": "Ruhiger Tag, Plan eingehalten.", "mood": 4},
    )
    assert antwort.status_code == 200
    gelesen = client.get("/api/journal/2026-03-02?account_id=1").json()
    assert gelesen["body"] == "Ruhiger Tag, Plan eingehalten."
    assert gelesen["mood"] == 4
    assert gelesen["updated_at"] is not None


def test_journal_zweites_schreiben_ueberschreibt(client):
    """Ein Tag hat einen Eintrag, nicht viele."""
    client.put("/api/journal/2026-03-02?account_id=1", json={"body": "erst"})
    client.put("/api/journal/2026-03-02?account_id=1", json={"body": "dann"})

    with client.session_factory() as s:  # type: ignore[attr-defined]
        eintraege = s.scalars(select(db.JournalEntry)).all()
    assert len(eintraege) == 1
    assert eintraege[0].body == "dann"


def test_journal_unlesbares_datum(client):
    assert client.get("/api/journal/gestern?account_id=1").status_code == 400
    assert client.put(
        "/api/journal/gestern?account_id=1", json={"body": "x"}
    ).status_code == 400


def test_journal_stimmung_ausserhalb_der_skala(client):
    for wert in (0, 6, -1):
        antwort = client.put(
            "/api/journal/2026-03-02?account_id=1", json={"body": "x", "mood": wert}
        )
        assert antwort.status_code == 400, wert


def test_journal_unbekanntes_konto(client):
    antwort = client.put("/api/journal/2026-03-02?account_id=99", json={"body": "x"})
    assert antwort.status_code == 404


# ---------------------------------------------------------------------------
# Playbook
# ---------------------------------------------------------------------------

def test_playbook_zuordnen(client):
    tid = _erste_id(client)
    with client.session_factory() as s:  # type: ignore[attr-defined]
        buch = db.Playbook(user_id=1, name="London Breakout")
        s.add(buch)
        s.commit()
        buch_id = buch.id

    antwort = client.patch(f"/api/trades/{tid}", json={"playbook_id": buch_id})
    assert antwort.status_code == 200

    buecher = client.get("/api/playbooks?account_id=1").json()
    assert [b["name"] for b in buecher] == ["London Breakout"]


def test_unbekanntes_playbook_wird_abgelehnt(client):
    tid = _erste_id(client)
    assert client.patch(
        f"/api/trades/{tid}", json={"playbook_id": 999}
    ).status_code == 404


def test_fremdes_playbook_wird_abgelehnt(client):
    """Ein Playbook eines anderen Nutzers gehört nicht an diesen Trade."""
    tid = _erste_id(client)
    with client.session_factory() as s:  # type: ignore[attr-defined]
        s.add(db.User(id=2, email="fremd@example.invalid", password_hash="x"))
        s.commit()
        fremd = db.Playbook(user_id=2, name="Fremdes Buch")
        s.add(fremd)
        s.commit()
        fremd_id = fremd.id

    assert client.patch(
        f"/api/trades/{tid}", json={"playbook_id": fremd_id}
    ).status_code == 403


# ---------------------------------------------------------------------------
# Was nicht schreibbar sein darf
# ---------------------------------------------------------------------------

def test_gerechnete_groessen_sind_nicht_schreibbar(client):
    """Ein Ergebnis kommt aus den Deals, nicht aus einem PATCH.

    Ließe man es zu, wäre die Änderung beim nächsten Abgleich lautlos
    wieder weg -- und bis dahin stünde in der Auswertung eine Zahl, die
    zu keinem Deal gehört. Pydantic verwirft unbekannte Felder still;
    geprüft wird deshalb, dass der Wert sich nicht bewegt hat.
    """
    tid = _erste_id(client)
    vorher = client.get(f"/api/trades/{tid}").json()

    client.patch(
        f"/api/trades/{tid}",
        json={"net_pnl": 999999, "r_multiple": 42, "symbol": "GEFAELSCHT"},
    )

    danach = client.get(f"/api/trades/{tid}").json()
    assert danach["net_pnl"] == vorher["net_pnl"]
    assert danach["r_multiple"] == vorher["r_multiple"]
    assert danach["symbol"] == vorher["symbol"]

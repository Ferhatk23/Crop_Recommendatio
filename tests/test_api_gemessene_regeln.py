"""Tests für Regeln, die gemessen statt abgehakt werden.

Der Sinn der Sache ist die Vorfahrt: Wo eine Angabe im Deal steht, muss
sie das Gedächtnis schlagen. Wer sein Journal abends führt, erinnert sich
an den Einstieg anders, wenn er das Ergebnis schon kennt -- und eine
Disziplin-Quote aus lauter selbstgesetzten Häkchen misst am Ende, wie
nachsichtig jemand mit sich ist.

Zwei Dinge müssen deshalb halten, und beide sind hier festgeschrieben:

1. Die gemessene Antwort überschreibt ein Häkchen an derselben Regel --
   auch ein älteres, das noch aus der Zeit vor der Prüfung stammt.
2. Was sich nicht messen lässt, bleibt **offen** und wird nie zu
   „gebrochen". Ein Befund aus Unwissen wäre schlimmer als keiner.
"""

from __future__ import annotations

import pytest
from decimal import Decimal

from tradediary.db import models as db
from tradediary.db.repository import deals_speichern, trades_neu_berechnen

from .conftest import close_long, open_long
from .test_api_schreiben import PASSWORT, client, roh_client  # noqa: F401


def anlegen(client, regeln) -> dict:
    antwort = client.post(
        "/api/playbooks", json={"name": "Gemessen", "rules": regeln}
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def zuordnen(client, trade_id: int, buch: dict) -> dict:
    return client.patch(
        f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]}
    ).json()


def trades(client) -> list[dict]:
    return sorted(
        client.get("/api/trades?limit=500").json()["trades"],
        key=lambda t: t["position_id"],
    )


def antworten(daten: dict) -> dict[int, dict]:
    return {a["rule_id"]: a for a in daten["rule_checks"]}


@pytest.fixture()
def mit_stop(client):
    """Ein Trade mit gesetztem Stop und einer ohne -- der Grundfall."""
    with client.session_factory() as s:  # type: ignore[attr-defined]
        deals_speichern(
            s,
            1,
            [
                open_long(
                    30, 700, "1.00", "1.10000", 400, stop_loss=Decimal("1.09000")
                ),
                close_long(31, 700, "1.00", "1.10400", 430, profit=400),
            ],
        )
        trades_neu_berechnen(s, 1)
    return trades(client)


# ---------------------------------------------------------------------------
# Die Prüfung antwortet von selbst
# ---------------------------------------------------------------------------

def test_eine_gemessene_regel_braucht_kein_haekchen(client, mit_stop):
    buch = anlegen(client, [{"text": "Stop gesetzt", "auto_check": "stop_gesetzt"}])
    regel = buch["rules"][0]["id"]

    # Der Trade mit Stop ist der zuletzt eingespielte (position 700).
    mit = [t for t in mit_stop if t["initial_sl"] is not None][0]
    daten = zuordnen(client, mit["id"], buch)

    assert antworten(daten)[regel] == {
        "rule_id": regel,
        "checked": True,
        "source": "gemessen",
    }


def test_ohne_stop_ist_die_regel_gebrochen(client, mit_stop):
    buch = anlegen(client, [{"text": "Stop gesetzt", "auto_check": "stop_gesetzt"}])
    regel = buch["rules"][0]["id"]

    ohne = [t for t in mit_stop if t["initial_sl"] is None][0]
    daten = zuordnen(client, ohne["id"], buch)
    assert antworten(daten)[regel]["checked"] is False


def test_eine_gemessene_regel_ist_immer_abhakbar(client):
    """Sonst fiele sie aus der Regeltreue -- gerade die verlässlichste."""
    buch = anlegen(
        client,
        [{"text": "Stop gesetzt", "auto_check": "stop_gesetzt", "checkable": False}],
    )
    assert buch["rules"][0]["checkable"] is True


# ---------------------------------------------------------------------------
# Gemessenes schlägt Erinnertes
# ---------------------------------------------------------------------------

def test_ein_haekchen_an_einer_gemessenen_regel_wird_abgelehnt(client, mit_stop):
    """Ein Klick, der nichts ändert, ist schlimmer als ein fehlender.

    Der Nutzer sähe ihn verpuffen und verstünde nicht warum.
    """
    buch = anlegen(client, [{"text": "Stop gesetzt", "auto_check": "stop_gesetzt"}])
    ohne = [t for t in mit_stop if t["initial_sl"] is None][0]
    zuordnen(client, ohne["id"], buch)

    antwort = client.put(
        f"/api/trades/{ohne['id']}/regeln",
        json=[{"rule_id": buch["rules"][0]["id"], "checked": True}],
    )
    assert antwort.status_code == 400
    assert "gemessen" in antwort.json()["detail"]


def test_ein_altes_haekchen_verliert_gegen_die_messung(client, mit_stop):
    """Der eigentliche Zweck der ganzen Übung.

    Erst wird von Hand abgehakt, dann bekommt die Regel eine Prüfung. Das
    alte Häkchen sagt „eingehalten", die Deals sagen etwas anderes -- und
    die Deals gewinnen. Bliebe das Häkchen stehen, hätte man sich die
    Prüfung sparen können.
    """
    buch = anlegen(client, [{"text": "Stop gesetzt"}])
    regel = buch["rules"][0]
    ohne = [t for t in mit_stop if t["initial_sl"] is None][0]
    zuordnen(client, ohne["id"], buch)

    gesetzt = client.put(
        f"/api/trades/{ohne['id']}/regeln",
        json=[{"rule_id": regel["id"], "checked": True}],
    ).json()
    assert antworten(gesetzt)[regel["id"]] == {
        "rule_id": regel["id"],
        "checked": True,
        "source": "selbst",
    }

    # Jetzt hängt eine Prüfung an derselben Regel.
    client.put(
        f"/api/playbooks/{buch['id']}/regeln",
        json=[{**regel, "auto_check": "stop_gesetzt"}],
    )

    daten = client.get(f"/api/trades/{ohne['id']}").json()
    assert antworten(daten)[regel["id"]] == {
        "rule_id": regel["id"],
        "checked": False,
        "source": "gemessen",
    }


def test_das_haekchen_ist_nicht_geloescht_sondern_ueberstimmt(client, mit_stop):
    """Nimmt man die Prüfung wieder weg, steht die alte Antwort wieder da.

    Ein Rückbau darf nicht als Datenverlust enden -- man probiert eine
    Prüfung aus und will sie folgenlos wieder loswerden können.
    """
    buch = anlegen(client, [{"text": "Stop gesetzt"}])
    regel = buch["rules"][0]
    ohne = [t for t in mit_stop if t["initial_sl"] is None][0]
    zuordnen(client, ohne["id"], buch)
    client.put(
        f"/api/trades/{ohne['id']}/regeln",
        json=[{"rule_id": regel["id"], "checked": True}],
    )

    client.put(
        f"/api/playbooks/{buch['id']}/regeln",
        json=[{**regel, "auto_check": "stop_gesetzt"}],
    )
    client.put(f"/api/playbooks/{buch['id']}/regeln", json=[{**regel, "auto_check": None}])

    daten = client.get(f"/api/trades/{ohne['id']}").json()
    assert antworten(daten)[regel["id"]]["source"] == "selbst"
    assert antworten(daten)[regel["id"]]["checked"] is True


# ---------------------------------------------------------------------------
# Was sich nicht messen lässt, bleibt offen
# ---------------------------------------------------------------------------

def test_ohne_bezugsgroesse_bleibt_die_regel_offen(client, mit_stop):
    """Das Testkonto hat kein Startkapital -- also kein Prozentbezug.

    Die Regel darf dann nicht als gebrochen erscheinen. Genau hier wäre
    ein `False` am gefährlichsten: Es sähe aus wie ein Befund über den
    Händler und wäre eine Aussage über eine leere Spalte.
    """
    with client.session_factory() as s:  # type: ignore[attr-defined]
        konto = s.get(db.Account, 1)
        assert not konto.starting_balance

    buch = anlegen(
        client,
        [{"text": "Höchstens 1 %", "auto_check": "risiko_hoechstens", "auto_param": "1"}],
    )
    mit = [t for t in mit_stop if t["initial_sl"] is not None][0]
    daten = zuordnen(client, mit["id"], buch)
    assert daten["rule_checks"] == []


def test_mit_startkapital_wird_dieselbe_regel_beantwortet(client, mit_stop):
    """Die Gegenprobe: Es lag am fehlenden Bezug, nicht an der Regel."""
    with client.session_factory() as s:  # type: ignore[attr-defined]
        s.get(db.Account, 1).starting_balance = 100000
        s.commit()

    buch = anlegen(
        client,
        [{"text": "Höchstens 1 %", "auto_check": "risiko_hoechstens", "auto_param": "1"}],
    )
    mit = [t for t in mit_stop if t["initial_sl"] is not None][0]
    daten = zuordnen(client, mit["id"], buch)
    assert antworten(daten)[buch["rules"][0]["id"]]["source"] == "gemessen"


# ---------------------------------------------------------------------------
# Eingabefehler
# ---------------------------------------------------------------------------

def test_eine_unbekannte_pruefung_wird_abgelehnt(client):
    antwort = client.post(
        "/api/playbooks",
        json={"name": "X", "rules": [{"text": "Y", "auto_check": "hellsehen"}]},
    )
    assert antwort.status_code == 400
    assert "stop_gesetzt" in antwort.json()["detail"]


def test_eine_zahlenregel_ohne_zahl_wird_abgelehnt(client):
    """Sonst bliebe sie bei jedem Trade offen -- und das sähe aus wie ein
    Fehler in den Daten statt in der Eingabe."""
    antwort = client.post(
        "/api/playbooks",
        json={
            "name": "X",
            "rules": [{"text": "Risiko", "auto_check": "risiko_hoechstens"}],
        },
    )
    assert antwort.status_code == 400
    detail = antwort.json()["detail"]
    assert "Zahl" in detail and "%" in detail


def test_die_pruefungen_stehen_als_liste_bereit(client):
    """Die Oberfläche baut daraus ihre Auswahlliste."""
    daten = client.get("/api/pruefungen").json()
    keys = {p["key"] for p in daten}
    assert "stop_gesetzt" in keys and "risiko_hoechstens" in keys
    for p in daten:
        assert p["beschreibung"]
        if p["einheit"]:
            assert p["beispiel"]


def test_die_pruefungen_brauchen_eine_anmeldung(roh_client):
    assert roh_client.get("/api/pruefungen").status_code == 401


# ---------------------------------------------------------------------------
# In der Auswertung
# ---------------------------------------------------------------------------

def test_die_regeltreue_zaehlt_gemessene_mit(client, mit_stop):
    buch = anlegen(client, [{"text": "Stop gesetzt", "auto_check": "stop_gesetzt"}])
    for t in trades(client):
        zuordnen(client, t["id"], buch)

    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    gruppen = {g["key"]: g for g in daten["groups"]}
    # Kein einziges Häkchen gesetzt -- und trotzdem ist alles beantwortet.
    assert daten["unanswered"] == 0
    assert gruppen["eingehalten"]["trades"] + gruppen["gebrochen"]["trades"] > 0
    assert daten["measured_rules"] == 1


def test_selbstberichtet_faellt_weg_wenn_alles_gemessen_wird(client, mit_stop):
    """Der Hinweis „selbstberichtet" ist eine Einschränkung.

    Sie stehenzulassen, wenn sie nicht mehr gilt, wäre genauso unehrlich
    wie sie wegzulassen, wenn sie gilt.
    """
    buch = anlegen(client, [{"text": "Stop gesetzt", "auto_check": "stop_gesetzt"}])
    zuordnen(client, trades(client)[0]["id"], buch)
    assert client.get("/api/reports/regeltreue?account_id=1").json()["self_reported"] is False


def test_eine_einzige_handregel_macht_es_wieder_selbstberichtet(client, mit_stop):
    buch = anlegen(
        client,
        [
            {"text": "Stop gesetzt", "auto_check": "stop_gesetzt"},
            {"text": "Ruhig geblieben", "checkable": True},
        ],
    )
    zuordnen(client, trades(client)[0]["id"], buch)
    assert client.get("/api/reports/regeltreue?account_id=1").json()["self_reported"] is True


def test_die_liste_und_das_detail_antworten_gleich(client, mit_stop):
    """Zwei Wege zu derselben Frage dürfen nicht auseinanderlaufen.

    Die Liste bündelt den Kontext für alle Zeilen, das Detail holt ihn für
    eine -- ein Unterschied dort wäre für niemanden erklärbar.
    """
    buch = anlegen(
        client,
        [
            {"text": "Stop gesetzt", "auto_check": "stop_gesetzt"},
            {
                "text": "Höchstens 2 Stunden",
                "auto_check": "haltedauer_hoechstens",
                "auto_param": "120",
            },
        ],
    )
    for t in trades(client):
        zuordnen(client, t["id"], buch)

    aus_liste = {t["id"]: t["rule_checks"] for t in trades(client)}
    for trade_id, checks in aus_liste.items():
        einzeln = client.get(f"/api/trades/{trade_id}").json()["rule_checks"]
        assert einzeln == checks, trade_id


def test_gemessene_regeln_kosten_keine_abfrage_je_zeile(client, mit_stop):
    """Die Prüfung darf nicht teurer sein als das, was sie beantwortet."""
    from sqlalchemy import event

    buch = anlegen(
        client,
        [
            {"text": "Stop gesetzt", "auto_check": "stop_gesetzt"},
            {"text": "Nicht nachgekauft", "auto_check": "nur_ein_einstieg"},
        ],
    )
    for t in trades(client):
        zuordnen(client, t["id"], buch)

    stand = {"n": 0}
    engine = client.main.engine  # type: ignore[attr-defined]
    zaehlen = lambda *a, **k: stand.__setitem__("n", stand["n"] + 1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", zaehlen)
    try:
        client.get("/api/trades?limit=500")
    finally:
        event.remove(engine, "before_cursor_execute", zaehlen)
    assert stand["n"] < 20, stand["n"]

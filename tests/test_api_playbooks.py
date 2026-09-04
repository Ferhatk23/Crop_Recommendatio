"""Tests für Playbooks und die Regel-Antworten je Trade.

Ein Playbook ist die schriftliche Fassung dessen, was man zu handeln
behauptet. Es lohnt nur, wenn man hinterher je Trade beantworten kann, ob
man sich daran gehalten hat -- und wenn diese Antworten nicht beiläufig
verschwinden.

Genau darauf liegt der Schwerpunkt hier. Drei Dinge könnten still
schiefgehen und wären hinterher nicht mehr zu bemerken:

1. Eine Regel-Antwort überlebt den nächsten Neuaufbau der Trades nicht.
   Dieselbe Falle hat schon einmal einen Tag an den falschen Trade
   gehängt.
2. Eine gestrichene Regel nimmt beim Speichern die Antworten von Dutzenden
   Trades mit.
3. Die Regeltreue rechnet unbeantwortete Trades als "gebrochen" und
   bestraft damit den, der noch nicht dazugekommen ist.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tradediary.db import models as db
from tradediary.db.repository import deals_speichern, trades_neu_berechnen

from .conftest import close_long, open_long
from .test_api_schreiben import PASSWORT, client, roh_client  # noqa: F401


BUCH = {
    "name": "London Breakout",
    "description": "Ausbruch aus der Asien-Range, erste Stunde London.",
    "rules": [
        {"group": "Vorbereitung", "text": "Range markiert", "checkable": True},
        {"group": "Einstieg", "text": "Stop hinter der Range", "checkable": True},
        {"group": "Haltung", "text": "Nicht in die Nachricht traden", "checkable": False},
    ],
}


def anlegen(client, **abweichung) -> dict:
    antwort = client.post("/api/playbooks", json={**BUCH, **abweichung})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def erster_trade(client) -> int:
    return client.get("/api/trades").json()["trades"][0]["id"]


# ---------------------------------------------------------------------------
# Anlegen und ändern
# ---------------------------------------------------------------------------

def test_playbook_anlegen(client):
    daten = anlegen(client)
    assert daten["name"] == "London Breakout"
    assert [r["text"] for r in daten["rules"]] == [
        "Range markiert",
        "Stop hinter der Range",
        "Nicht in die Nachricht traden",
    ]
    assert daten["trade_count"] == 0


def test_die_reihenfolge_der_eingabe_bleibt(client):
    """Sie ist die Reihenfolge auf dem Bildschirm -- und die des Ablaufs.

    Ein Playbook wird von oben nach unten abgearbeitet; eine alphabetisch
    sortierte Liste wäre eine andere Anweisung.
    """
    daten = anlegen(
        client,
        rules=[{"text": t, "checkable": True} for t in ("Zuletzt", "Mittig", "Anfang")],
    )
    assert [r["text"] for r in daten["rules"]] == ["Zuletzt", "Mittig", "Anfang"]


def test_ohne_anmeldung_kein_playbook(roh_client):
    assert roh_client.post("/api/playbooks", json=BUCH).status_code == 401
    assert roh_client.get("/api/playbooks").status_code == 401


def test_name_ist_pflicht(client):
    for leer in ("", "   "):
        assert client.post("/api/playbooks", json={**BUCH, "name": leer}).status_code == 400


def test_eine_regel_ohne_text_wird_abgelehnt(client):
    antwort = client.post(
        "/api/playbooks", json={**BUCH, "rules": [{"text": "  ", "checkable": True}]}
    )
    assert antwort.status_code == 400


def test_umbenennen_laesst_die_regeln_stehen(client):
    buch = anlegen(client)
    geaendert = client.patch(
        f"/api/playbooks/{buch['id']}", json={"name": "London Breakout v2"}
    ).json()
    assert geaendert["name"] == "London Breakout v2"
    assert len(geaendert["rules"]) == 3


def test_patch_fasst_nur_an_was_dasteht(client):
    buch = anlegen(client)
    geaendert = client.patch(f"/api/playbooks/{buch['id']}", json={"name": "Anders"}).json()
    assert geaendert["description"] == BUCH["description"]


def test_fremdes_playbook_ist_nicht_zu_sehen(client):
    """404, nicht 403: Ein 403 verriete, dass die ID existiert."""
    buch = anlegen(client)
    with client.session_factory() as s:  # type: ignore[attr-defined]
        s.get(db.Playbook, buch["id"]).user_id = 99
        s.commit()

    assert client.get("/api/playbooks").json() == []
    assert client.patch(f"/api/playbooks/{buch['id']}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/playbooks/{buch['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Die Regelliste -- der Teil, an dem Antworten hängen
# ---------------------------------------------------------------------------

def test_eine_geaenderte_regel_behaelt_ihre_id(client):
    """Der wichtigste Test dieser Datei.

    Würde die Liste bei jedem Speichern gelöscht und neu geschrieben,
    verlöre jede Regel bei jeder Tippfehlerkorrektur ihre ID -- und mit
    ihr sämtliche Antworten, die je an ihr hingen. Der Verlust fiele
    nirgends auf: Die Oberfläche zeigte danach einfach leere Kästchen.
    """
    buch = anlegen(client)
    erste = buch["rules"][0]

    neu = client.put(
        f"/api/playbooks/{buch['id']}/regeln",
        json=[
            {**{k: r[k] for k in ("id", "group", "text", "checkable")}}
            if r["id"] != erste["id"]
            else {**erste, "text": "Asien-Range markiert"}
            for r in buch["rules"]
        ],
    )
    assert neu.status_code == 200, neu.text
    geaendert = neu.json()["rules"][0]
    assert geaendert["id"] == erste["id"]
    assert geaendert["text"] == "Asien-Range markiert"


def test_eine_regel_ohne_id_wird_neu_angelegt(client):
    buch = anlegen(client)
    liste = [
        {k: r[k] for k in ("id", "group", "text", "checkable")} for r in buch["rules"]
    ]
    liste.append({"group": "Einstieg", "text": "Rücklauf abgewartet", "checkable": True})

    daten = client.put(f"/api/playbooks/{buch['id']}/regeln", json=liste).json()
    assert len(daten["rules"]) == 4
    assert daten["rules"][-1]["text"] == "Rücklauf abgewartet"
    assert daten["rules"][-1]["id"] not in {r["id"] for r in buch["rules"]}


def test_eine_fehlende_regel_wird_gestrichen(client):
    buch = anlegen(client)
    liste = [
        {k: r[k] for k in ("id", "group", "text", "checkable")}
        for r in buch["rules"][:1]
    ]
    daten = client.put(f"/api/playbooks/{buch['id']}/regeln", json=liste).json()
    assert [r["text"] for r in daten["rules"]] == ["Range markiert"]


def test_eine_fremde_regel_id_wird_abgelehnt(client):
    """Sonst liesse sich eine fremde Regel unter das eigene Playbook hängen."""
    buch = anlegen(client)
    zweites = anlegen(client, name="Zweites")
    antwort = client.put(
        f"/api/playbooks/{buch['id']}/regeln",
        json=[{"id": zweites["rules"][0]["id"], "text": "geklaut", "checkable": True}],
    )
    assert antwort.status_code == 404


# ---------------------------------------------------------------------------
# Antworten je Trade
# ---------------------------------------------------------------------------

def test_regeln_beantworten(client):
    buch = anlegen(client)
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})

    antwort = client.put(
        f"/api/trades/{trade_id}/regeln",
        json=[
            {"rule_id": buch["rules"][0]["id"], "checked": True},
            {"rule_id": buch["rules"][1]["id"], "checked": False},
        ],
    )
    assert antwort.status_code == 200, antwort.text
    checks = {c["rule_id"]: c["checked"] for c in antwort.json()["rule_checks"]}
    assert checks == {buch["rules"][0]["id"]: True, buch["rules"][1]["id"]: False}


def test_die_zuordnung_kommt_beim_trade_zurueck(client):
    """Sie war schon immer setzbar, kam aber nie mit -- die Oberfläche
    konnte ein Playbook auswählen und danach nicht mehr sagen, welches."""
    buch = anlegen(client)
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})
    assert client.get(f"/api/trades/{trade_id}").json()["playbook_id"] == buch["id"]


def test_zweimal_dasselbe_geschickt_ergibt_dasselbe(client):
    buch = anlegen(client)
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})
    liste = [{"rule_id": buch["rules"][0]["id"], "checked": True}]

    erste = client.put(f"/api/trades/{trade_id}/regeln", json=liste).json()
    zweite = client.put(f"/api/trades/{trade_id}/regeln", json=liste).json()
    assert erste["rule_checks"] == zweite["rule_checks"]


def test_was_fehlt_gilt_als_unbeantwortet(client):
    """Nicht als "nicht eingehalten" -- daran hängt die ganze Kennzahl."""
    buch = anlegen(client)
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})
    client.put(
        f"/api/trades/{trade_id}/regeln",
        json=[{"rule_id": r["id"], "checked": True} for r in buch["rules"][:2]],
    )

    daten = client.put(
        f"/api/trades/{trade_id}/regeln",
        json=[{"rule_id": buch["rules"][0]["id"], "checked": True}],
    ).json()
    assert len(daten["rule_checks"]) == 1


def test_ohne_playbook_keine_antworten(client):
    trade_id = erster_trade(client)
    antwort = client.put(
        f"/api/trades/{trade_id}/regeln", json=[{"rule_id": 1, "checked": True}]
    )
    assert antwort.status_code == 400


def test_eine_leere_liste_ohne_playbook_ist_kein_fehler(client):
    """Die Oberfläche darf beim Abwählen aufräumen, ohne 400 zu bekommen."""
    trade_id = erster_trade(client)
    assert client.put(f"/api/trades/{trade_id}/regeln", json=[]).status_code == 200


def test_eine_regel_aus_einem_anderen_playbook_wird_abgelehnt(client):
    """Sonst stünde am Trade eine Antwort auf eine nie gestellte Frage."""
    buch = anlegen(client)
    fremdes = anlegen(client, name="Ganz anderes")
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})

    antwort = client.put(
        f"/api/trades/{trade_id}/regeln",
        json=[{"rule_id": fremdes["rules"][0]["id"], "checked": True}],
    )
    assert antwort.status_code == 400


def test_nach_dem_wechsel_zaehlen_die_alten_antworten_nicht_mehr(client):
    """Aber sie sind auch nicht weg -- zurückgewechselt sind sie wieder da.

    Ein Playbook-Wechsel ist meistens eine Korrektur, kein Neuanfang.
    Löschte er die Antworten, wäre ein Fehlgriff in der Auswahlliste
    unumkehrbar.
    """
    buch = anlegen(client)
    anderes = anlegen(client, name="Anderes")
    trade_id = erster_trade(client)

    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})
    client.put(
        f"/api/trades/{trade_id}/regeln",
        json=[{"rule_id": buch["rules"][0]["id"], "checked": True}],
    )

    gewechselt = client.patch(
        f"/api/trades/{trade_id}", json={"playbook_id": anderes["id"]}
    ).json()
    assert gewechselt["rule_checks"] == []

    zurueck = client.patch(
        f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]}
    ).json()
    assert len(zurueck["rule_checks"]) == 1


# ---------------------------------------------------------------------------
# Nichts geht beiläufig verloren
# ---------------------------------------------------------------------------

def test_eine_regel_mit_antworten_verschwindet_nicht_still(client):
    buch = anlegen(client)
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})
    client.put(
        f"/api/trades/{trade_id}/regeln",
        json=[{"rule_id": buch["rules"][0]["id"], "checked": True}],
    )

    antwort = client.put(f"/api/playbooks/{buch['id']}/regeln", json=[])
    assert antwort.status_code == 409
    assert "1 Antworten" in antwort.json()["detail"]
    # Und wirklich nichts angefasst.
    assert len(client.get(f"/api/playbooks").json()[0]["rules"]) == 3


def test_mit_ausdruecklicher_zustimmung_geht_es_doch(client):
    buch = anlegen(client)
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})
    client.put(
        f"/api/trades/{trade_id}/regeln",
        json=[{"rule_id": buch["rules"][0]["id"], "checked": True}],
    )

    antwort = client.put(
        f"/api/playbooks/{buch['id']}/regeln?antworten_verwerfen=true", json=[]
    )
    assert antwort.status_code == 200
    assert antwort.json()["rules"] == []
    assert client.get(f"/api/trades/{trade_id}").json()["rule_checks"] == []


def test_eine_regel_ohne_antworten_darf_einfach_weg(client):
    """Sonst wäre schon das Streichen eines Tippfehlers eine Bestätigung wert."""
    buch = anlegen(client)
    liste = [
        {k: r[k] for k in ("id", "group", "text", "checkable")}
        for r in buch["rules"][:2]
    ]
    assert client.put(f"/api/playbooks/{buch['id']}/regeln", json=liste).status_code == 200


def test_ein_playbook_mit_trades_wird_nicht_geloescht(client):
    buch = anlegen(client)
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})

    antwort = client.delete(f"/api/playbooks/{buch['id']}")
    assert antwort.status_code == 409
    assert "1 Trades" in antwort.json()["detail"]


def test_ein_ungenutztes_playbook_laesst_sich_loeschen(client):
    buch = anlegen(client)
    assert client.delete(f"/api/playbooks/{buch['id']}").status_code == 200
    assert client.get("/api/playbooks").json() == []


def test_beim_loeschen_bleiben_keine_regeln_zurueck(client):
    buch = anlegen(client)
    client.delete(f"/api/playbooks/{buch['id']}")
    with client.session_factory() as s:  # type: ignore[attr-defined]
        assert s.scalars(select(db.PlaybookRule)).all() == []


def test_antworten_ueberleben_den_neuaufbau(client):
    """Dieselbe Falle wie bei den Tags, und sie hat dort schon zugeschlagen.

    Ein Bulk-DELETE übergeht die ORM-Kaskade, und SQLite vergibt nach
    einem vollständigen Löschen wieder ab 1. Ohne ausdrückliches
    Mitführen zeigte ein Häkchen nach dem nächsten Nachimport auf einen
    fremden Trade -- die stillste Art, die eigene Statistik zu
    verfälschen.
    """
    buch = anlegen(client)
    trade_id = erster_trade(client)
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})
    client.put(
        f"/api/trades/{trade_id}/regeln",
        json=[
            {"rule_id": buch["rules"][0]["id"], "checked": True},
            {"rule_id": buch["rules"][1]["id"], "checked": False},
        ],
    )
    position = client.get(f"/api/trades/{trade_id}").json()["position_id"]

    # Ältere Historie kommt nach -- der Klassiker, bei dem die IDs sich
    # verschieben.
    with client.session_factory() as s:  # type: ignore[attr-defined]
        deals_speichern(
            s,
            1,
            [
                open_long(90, 50, "1.00", "1.07000", -600),
                close_long(91, 50, "1.00", "1.07200", -570, profit=200),
            ],
        )
        trades_neu_berechnen(s, 1)

    neu = next(
        t
        for t in client.get("/api/trades").json()["trades"]
        if t["position_id"] == position
    )
    assert neu["playbook_id"] == buch["id"]
    checks = {c["rule_id"]: c["checked"] for c in neu["rule_checks"]}
    assert checks == {buch["rules"][0]["id"]: True, buch["rules"][1]["id"]: False}

    # Und der neu dazugekommene Trade hat *keine* geerbt.
    andere = [
        t
        for t in client.get("/api/trades").json()["trades"]
        if t["position_id"] != position
    ]
    assert all(t["rule_checks"] == [] for t in andere)


# ---------------------------------------------------------------------------
# Regeltreue
# ---------------------------------------------------------------------------

@pytest.fixture()
def regeltreue_daten(client):
    """Vier Trades: zwei sauber, einer gebrochen, einer unbeantwortet."""
    buch = anlegen(
        client,
        rules=[
            {"group": "A", "text": "Range markiert", "checkable": True},
            {"group": "A", "text": "Stop gesetzt", "checkable": True},
            {"group": "B", "text": "Ruhig geblieben", "checkable": False},
        ],
    )
    with client.session_factory() as s:  # type: ignore[attr-defined]
        deals_speichern(
            s,
            1,
            [
                open_long(20, 300, "1.00", "1.10000", 200),
                close_long(21, 300, "1.00", "1.10500", 230, profit=500),
                open_long(22, 400, "1.00", "1.11000", 300),
                close_long(23, 400, "1.00", "1.10000", 330, profit=-900),
            ],
        )
        trades_neu_berechnen(s, 1)

    trades = client.get("/api/trades").json()["trades"]
    ids = [t["id"] for t in sorted(trades, key=lambda t: t["position_id"])]
    r0, r1 = buch["rules"][0]["id"], buch["rules"][1]["id"]

    for trade_id in ids:
        client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})

    # Zwei vollständig sauber, einer mit einem Bruch, der vierte bleibt offen.
    for trade_id in ids[:2]:
        client.put(
            f"/api/trades/{trade_id}/regeln",
            json=[{"rule_id": r0, "checked": True}, {"rule_id": r1, "checked": True}],
        )
    client.put(
        f"/api/trades/{ids[2]}/regeln",
        json=[{"rule_id": r0, "checked": True}, {"rule_id": r1, "checked": False}],
    )
    return {"buch": buch, "ids": ids, "r0": r0, "r1": r1}


def test_regeltreue_teilt_in_eingehalten_und_gebrochen(client, regeltreue_daten):
    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    gruppen = {g["key"]: g for g in daten["groups"]}
    assert gruppen["eingehalten"]["trades"] == 2
    assert gruppen["gebrochen"]["trades"] == 1


def test_unbeantwortete_trades_stehen_getrennt(client, regeltreue_daten):
    """Sie dürfen nicht als "gebrochen" zählen.

    Sonst bestrafte die Kennzahl den, der noch nicht dazugekommen ist --
    und die Regeltreue eines frisch eingelaufenen Trades stünde bei 0 %.
    """
    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    assert daten["unanswered"] == 1
    assert sum(g["trades"] for g in daten["groups"]) == 3
    assert daten["total_trades"] == 4


def test_ein_bestaetigter_bruch_bleibt_ein_bruch(client, regeltreue_daten):
    """Auch wenn der Rest der Liste offen ist.

    Das ist die Gegenprobe zur Vollständigkeitsregel: Unvollständig
    beantwortet heisst offen -- ausser es steht schon ein Nein da.
    """
    ids, r1 = regeltreue_daten["ids"], regeltreue_daten["r1"]
    client.put(f"/api/trades/{ids[3]}/regeln", json=[{"rule_id": r1, "checked": False}])

    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    gruppen = {g["key"]: g for g in daten["groups"]}
    assert gruppen["gebrochen"]["trades"] == 2
    assert daten["unanswered"] == 0


def test_halb_abgehakt_zaehlt_nicht_als_sauber(client, regeltreue_daten):
    """Sonst misst die Quote Fleiss beim Abhaken statt Disziplin."""
    ids, r0 = regeltreue_daten["ids"], regeltreue_daten["r0"]
    client.put(f"/api/trades/{ids[3]}/regeln", json=[{"rule_id": r0, "checked": True}])

    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    gruppen = {g["key"]: g for g in daten["groups"]}
    assert gruppen["eingehalten"]["trades"] == 2
    assert daten["unanswered"] == 1


def test_je_regel_steht_die_quote_da(client, regeltreue_daten):
    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    regeln = {r["rule_id"]: r for r in daten["rules"]}

    assert regeln[regeltreue_daten["r0"]]["answered"] == 3
    assert regeln[regeltreue_daten["r0"]]["rate"] == 1.0
    assert regeln[regeltreue_daten["r1"]]["broken"] == 1
    assert regeln[regeltreue_daten["r1"]]["rate"] == pytest.approx(2 / 3)


def test_ohne_antwort_gibt_es_keine_quote(client):
    """`None`, nicht 0 -- null hiesse "nie eingehalten"."""
    anlegen(client)
    trade_id = erster_trade(client)
    buch = client.get("/api/playbooks").json()[0]
    client.patch(f"/api/trades/{trade_id}", json={"playbook_id": buch["id"]})

    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    assert all(r["rate"] is None for r in daten["rules"])


def test_nicht_abhakbare_regeln_stehen_nicht_in_der_quote(client, regeltreue_daten):
    """Ein Merksatz ist keine Frage, die sich mit ja oder nein beantworten lässt."""
    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    texte = {r["text"] for r in daten["rules"]}
    assert "Ruhig geblieben" not in texte
    assert texte == {"Range markiert", "Stop gesetzt"}


def test_die_antwort_sagt_dass_sie_selbstberichtet_ist(client, regeltreue_daten):
    """Die Zahl misst, was der Händler über sich notiert hat. Nicht mehr."""
    daten = client.get("/api/reports/regeltreue?account_id=1").json()
    assert daten["self_reported"] is True


def test_regeltreue_ist_keine_unbekannte_dimension(client):
    """Der Platzhalter `/api/reports/{dimension}` darf sie nicht schlucken."""
    assert client.get("/api/reports/regeltreue?account_id=1").status_code == 200


def test_regeltreue_sieht_nur_eigene_konten(client):
    """Ohne Anmeldung gar nichts, mit fremdem Konto nichts Fremdes."""
    from .test_api_schreiben import zweiter_nutzer

    zweiter_nutzer(client)
    daten = client.get("/api/reports/regeltreue?account_id=2")
    assert daten.status_code == 404

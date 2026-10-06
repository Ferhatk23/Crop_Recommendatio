"""Tests für den Nachbearbeitungs-Filter der Trade-Liste.

Ein Journal führt man abends, nicht während des Handels. Danach muss man
wiederfinden, was noch aussteht -- sonst scrollt man durch dreihundert
Zeilen und rät. Genau daran stirbt die Gewohnheit: nicht am Aufschreiben,
sondern am Suchen, wo man stehen geblieben ist.

Der Filter darf deshalb in beide Richtungen nicht lügen. Ein Trade, der
fälschlich als erledigt gilt, wird nie wieder angesehen; einer, der
fälschlich offen bleibt, macht die Liste unbrauchbar.
"""

from __future__ import annotations

import pytest

from tradediary.db.repository import deals_speichern, trades_neu_berechnen

from .conftest import close_long, open_long
from .test_api_playbooks import anlegen  # noqa: F401
from .test_api_schreiben import PASSWORT, client, roh_client  # noqa: F401


def ids(client, art: str | None = None) -> set[int]:
    pfad = "/api/trades?limit=500"
    if art:
        pfad += f"&nachbearbeitung={art}"
    return {t["id"] for t in client.get(pfad).json()["trades"]}


@pytest.fixture()
def vier(client):
    """Vier Trades in vier Bearbeitungsständen.

    Der Grundbestand bringt zwei mit; zwei kommen dazu, damit jeder Stand
    genau einmal vorkommt und ein zu weit gefasster Filter auffällt.
    """
    with client.session_factory() as s:  # type: ignore[attr-defined]
        deals_speichern(
            s,
            1,
            [
                open_long(20, 300, "1.00", "1.10000", 200),
                close_long(21, 300, "1.00", "1.10500", 230, profit=500),
                open_long(22, 400, "1.00", "1.11000", 300),
                close_long(23, 400, "1.00", "1.11400", 330, profit=400),
            ],
        )
        trades_neu_berechnen(s, 1)

    buch = anlegen(client)
    alle = sorted(
        client.get("/api/trades?limit=500").json()["trades"],
        key=lambda t: t["position_id"],
    )
    a, b, c, d = (t["id"] for t in alle)

    # a bleibt unberührt.
    # b bekommt nur eine Notiz.
    client.patch(f"/api/trades/{b}", json={"note": "Nur eine Notiz."})
    # c bekommt nur einen Tag.
    client.put(
        f"/api/trades/{c}/tags", json={"tags": [{"label": "Breakout", "kind": "setup"}]}
    )
    # d ist vollständig: Notiz, Tag, Playbook, alle abhakbaren Regeln.
    client.patch(f"/api/trades/{d}", json={"note": "Fertig.", "playbook_id": buch["id"]})
    client.put(
        f"/api/trades/{d}/tags", json={"tags": [{"label": "Pullback", "kind": "setup"}]}
    )
    client.put(
        f"/api/trades/{d}/regeln",
        json=[
            {"rule_id": r["id"], "checked": True}
            for r in buch["rules"]
            if r["checkable"]
        ],
    )
    return {"buch": buch, "a": a, "b": b, "c": c, "d": d}


def test_unberuehrt_findet_nur_den_frisch_eingelaufenen(client, vier):
    """Weder Notiz noch Tag noch Playbook -- nie angesehen."""
    assert ids(client, "unberuehrt") == {vier["a"]}


def test_ohne_notiz_uebersieht_den_getaggten_nicht(client, vier):
    """Ein Tag ist keine Notiz. Wer beides gleichsetzt, verliert Trades."""
    assert ids(client, "ohne_notiz") == {vier["a"], vier["c"]}


def test_ohne_tag_uebersieht_den_notierten_nicht(client, vier):
    assert ids(client, "ohne_tag") == {vier["a"], vier["b"]}


def test_ohne_playbook_findet_die_drei_ohne(client, vier):
    assert ids(client, "ohne_playbook") == {vier["a"], vier["b"], vier["c"]}


def test_regeln_offen_ist_leer_wenn_alles_beantwortet_ist(client, vier):
    """Der einzige Trade mit Playbook ist vollständig durchgegangen."""
    assert ids(client, "regeln_offen") == set()


def test_eine_halb_beantwortete_liste_gilt_als_offen(client, vier):
    """Halb abgehakt ist nicht erledigt -- sonst zählt die Liste zu früh runter."""
    buch = vier["buch"]
    abhakbar = [r for r in buch["rules"] if r["checkable"]]
    client.put(
        f"/api/trades/{vier['d']}/regeln",
        json=[{"rule_id": abhakbar[0]["id"], "checked": True}],
    )
    assert ids(client, "regeln_offen") == {vier["d"]}


def test_ein_playbook_ohne_abhakbare_regeln_bleibt_nicht_ewig_offen(client, vier):
    """Sonst stünde jeder Trade eines reinen Merksatz-Playbooks für immer
    auf der Liste -- und niemand könnte ihn je herunterbekommen."""
    merksaetze = anlegen(
        client,
        name="Nur Merksätze",
        rules=[{"text": "Ruhig bleiben", "checkable": False}],
    )
    client.patch(f"/api/trades/{vier['a']}", json={"playbook_id": merksaetze["id"]})
    assert vier["a"] not in ids(client, "regeln_offen")


def test_ohne_filter_kommen_alle(client, vier):
    assert ids(client) == {vier["a"], vier["b"], vier["c"], vier["d"]}


def test_der_filter_laesst_sich_mit_dem_ausgang_kombinieren(client, vier):
    """Beide Filter gleichzeitig -- sonst muss man sich entscheiden."""
    antwort = client.get("/api/trades?nachbearbeitung=ohne_notiz&outcome=win")
    assert antwort.status_code == 200
    assert {t["id"] for t in antwort.json()["trades"]} == {vier["a"], vier["c"]}


def test_die_gesamtzahl_zaehlt_die_gefilterten(client, vier):
    """`total` ist die Zahl, die als "noch offen" auf dem Schirm steht.

    Zählte sie ungefiltert, stünde dort dauerhaft die Gesamtmenge -- und
    die Anzeige wäre schlimmer als keine.
    """
    daten = client.get("/api/trades?nachbearbeitung=unberuehrt").json()
    assert daten["total"] == 1


def test_die_gesamtzahl_stimmt_auch_ueber_seitengrenzen(client, vier):
    """Der Filter läuft in der Datenbank, nicht auf der geholten Seite.

    Ein Filter, der erst nach dem Blättern greift, zählt falsch und
    liefert auf Seite zwei etwas anderes als auf Seite eins.
    """
    daten = client.get("/api/trades?nachbearbeitung=ohne_playbook&limit=2").json()
    assert daten["total"] == 3
    assert len(daten["trades"]) == 2


def test_eine_unbekannte_art_wird_abgelehnt(client):
    """Ein Tippfehler darf nicht stillschweigend alles zurückgeben.

    Sonst sähe die Liste danach aus wie "nichts mehr zu tun" -- oder wie
    "alles zu tun", je nach Blickwinkel. Beides ist eine Falschaussage.
    """
    antwort = client.get("/api/trades?nachbearbeitung=erledigt")
    assert antwort.status_code == 400
    assert "unberuehrt" in antwort.json()["detail"]


def test_der_filter_sieht_keine_fremden_trades(client, vier):
    """Die Berechtigungsschranke gilt auch hier."""
    from .test_api_schreiben import zweiter_nutzer

    fremd = zweiter_nutzer(client)
    gefunden = ids(client, "unberuehrt")
    assert fremd["trade_id"] not in gefunden

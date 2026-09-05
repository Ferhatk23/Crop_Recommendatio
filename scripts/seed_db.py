"""Legt eine Entwicklungsdatenbank mit Beispieldaten an."""
from __future__ import annotations

import os
import secrets
import sys
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradediary.db import models as m
from tradediary.db.repository import (aufnehmen, engine_bauen, schema_anlegen,
                                      session_factory)
from tradediary.demo.seed import erzeuge_deals
from tradediary.sicherheit import hashe_passwort

URL = os.environ.get("TRADEDIARY_DB", "sqlite:///tradediary.db")
EMAIL = os.environ.get("TRADEDIARY_DEMO_EMAIL", "demo@tradediary.local")


def main() -> None:
    pfad = URL.replace("sqlite:///", "")
    if URL.startswith("sqlite") and os.path.exists(pfad):
        os.remove(pfad)
        print(f"alte Datenbank entfernt: {pfad}")

    engine = engine_bauen(URL)
    schema_anlegen(engine)
    Session = session_factory(engine)

    # Ein zufaelliges Passwort, einmal ausgegeben -- kein festes im Repo.
    #
    # Standardpasswoerter sind der haeufigste Weg, auf dem selbstbetriebene
    # Software uebernommen wird: Sie stehen im oeffentlichen Quelltext,
    # jeder kennt sie, und niemand aendert sie. Wer dieses hier verliert,
    # setzt ein neues: scripts/nutzer.py passwort <email>
    passwort = secrets.token_urlsafe(12)

    with Session() as s:
        user = m.User(email=EMAIL, password_hash=hashe_passwort(passwort))
        s.add(user)
        s.flush()

        # Drei Konten, wie ein Prop-Trader sie über die Zeit ansammelt:
        # eins bestanden, eins verloren, eins aktiv.
        konten = [
            dict(label="Alpha 100k · Funded", phase=m.KontoPhase.FUNDED,
                 status=m.KontoStatus.AKTIV, starting_balance=100_000,
                 daily_loss_limit=5_000, max_loss_limit=10_000,
                 consistency_limit=D("0.4"), profit_target=10_000,
                 tage=45, seed=20260315),
            dict(label="Alpha 50k · Challenge", phase=m.KontoPhase.CHALLENGE,
                 status=m.KontoStatus.BESTANDEN, starting_balance=50_000,
                 daily_loss_limit=2_500, max_loss_limit=5_000,
                 consistency_limit=D("0.4"), profit_target=4_000,
                 tage=22, seed=99),
            dict(label="Alpha 25k · verloren", phase=m.KontoPhase.CHALLENGE,
                 status=m.KontoStatus.VERLOREN, starting_balance=25_000,
                 daily_loss_limit=1_250, max_loss_limit=2_500,
                 consistency_limit=D("0.4"), tage=9, seed=7),
        ]

        for eintrag in konten:
            tage = eintrag.pop("tage")
            seed = eintrag.pop("seed")
            konto = m.Account(user_id=user.id, broker="Alpha Capital",
                              server="AlphaCapital-Live02", currency="EUR",
                              hedging=True, **eintrag)
            s.add(konto)
            s.commit()

            deals = erzeuge_deals(account_id=str(konto.id), handelstage=tage,
                                  seed=seed,
                                  startkapital=D(str(eintrag["starting_balance"])))
            neu, anzahl = aufnehmen(s, konto.id, deals, source="demo")
            print(f"  {konto.label:<26} {neu:>4} Ausfuehrungen -> {anzahl:>3} Trades")

        # Tags und ein Playbook, damit die Oberflaeche etwas zu zeigen hat.
        setups = ["Breakout", "Pullback", "News-Fade"]
        fehler = ["zu frueh raus", "Regel gebrochen", "nachgekauft"]
        emotionen = ["ruhig", "ungeduldig"]

        marken: dict[str, m.Tag] = {}
        for label, art in ([(x, m.TagArt.SETUP) for x in setups]
                           + [(x, m.TagArt.FEHLER) for x in fehler]
                           + [(x, m.TagArt.EMOTION) for x in emotionen]):
            marke = m.Tag(user_id=user.id, label=label, kind=art)
            s.add(marke)
            marken[label] = marke
        s.flush()

        pb = m.Playbook(user_id=user.id, name="London Breakout",
                        description="Ausbruch aus der asiatischen Range.")
        s.add(pb)
        s.flush()
        # Die letzten drei tragen eine Pruefung: Sie werden aus den Deals
        # beantwortet statt abgehakt. Ohne mindestens eine im Seed
        # entwickelt man den gemessenen Fall an einem Bildschirm, auf dem
        # er nie vorkommt.
        regeln = [
            ("Aufbau", "Asiatische Range sauber abgegrenzt", False, None, None),
            ("Aufbau", "Ueber VWAP", True, None, None),
            ("Einstieg", "Ausbruch mit Volumen bestaetigt", False, None, None),
            ("Risiko", "Stop hinter der Range", True, "stop_gesetzt", None),
            ("Risiko", "Hoechstens 1 % Risiko", True, "risiko_hoechstens", "1"),
            ("Verhalten", "Nicht nachgekauft", True, "nur_ein_einstieg", None),
        ]
        for i, (gruppe, text, pruefbar, pruefung, wert) in enumerate(regeln):
            s.add(m.PlaybookRule(playbook_id=pb.id, group_label=gruppe,
                                 text=text, checkable=pruefbar, sort_order=i,
                                 auto_check=pruefung, auto_param=wert))
        s.commit()

        verteile_beschriftungen(s, marken, pb, setups, fehler, emotionen)

        gesamt = s.query(m.Trade).count()
        print(f"\nFertig: {gesamt} Trades in {pfad}")
        print("\n" + "=" * 58)
        print("  Anmeldung -- dieses Passwort steht nirgendwo sonst:")
        print(f"    E-Mail:   {EMAIL}")
        print(f"    Passwort: {passwort}")
        print("=" * 58)
        print("  Neues setzen: python scripts/nutzer.py passwort <email>")


def beantworte_regeln(s, rng, trade, pruefbare, verlust: bool) -> int:
    """Hakt die Regeln eines Trades ab -- oder eben nicht.

    Drei Faelle, und der dritte ist der wichtigste:

    * **Vollstaendig beantwortet, alles gehalten.** Der saubere Trade.
    * **Mindestens eine gebrochen.** Ueberwiegend bei Verlusten -- nicht,
      weil das huebscher aussieht, sondern weil die Auswertung sonst flach
      herauskaeme und man nicht saehe, ob sie etwas misst.
    * **Gar nicht oder halb beantwortet.** Wer sein Journal fuehrt, fuehrt
      es lueckenhaft. Diese Trades muessen in den Beispieldaten vorkommen,
      sonst entwickelt man die Regeltreue an einem Bildschirm, auf dem der
      haeufigste Fall nie auftaucht.
    """
    if not pruefbare or rng.random() < 0.25:
        return 0

    # Bei einem Verlust haeufiger ein Bruch -- und bei Gewinnen kommt er
    # trotzdem vor, sonst waere die Kennzahl bloss ein zweites Vorzeichen.
    bricht = rng.random() < (0.45 if verlust else 0.12)
    gebrochene = {rng.choice(pruefbare).id} if bricht else set()

    # Ein Teil bleibt absichtlich halb ausgefuellt.
    liste = pruefbare if rng.random() > 0.18 else pruefbare[: max(1, len(pruefbare) // 2)]

    gesetzt = 0
    for regel in liste:
        s.add(m.TradeRuleCheck(trade_id=trade.id, rule_id=regel.id,
                               checked=regel.id not in gebrochene))
        gesetzt += 1
    return gesetzt


def verteile_beschriftungen(s, marken, pb, setups, fehler, emotionen) -> None:
    """Haengt Tags, Notizen und Tagesjournale an die erzeugten Trades.

    Ohne das legt der Seed zwar Tags an, vergibt sie aber nie -- und die
    Auswertung nach Setup bleibt leer, obwohl die Oberflaeche dafuer
    gebaut ist. Man entwickelt dann an einem Bildschirm, den es im
    Betrieb nie gibt.

    Zwei Dinge sind hier Absicht:

    * **Nicht jeder Trade bekommt etwas.** Wer sein Journal fuehrt, fuehrt
      es lueckenhaft. Die Oberflaeche muss den Fall "kein Tag" genauso
      aushalten wie den anderen -- und man sieht ihn nur, wenn er in den
      Beispieldaten vorkommt.
    * **Fehler-Tags haengen ueberwiegend an Verlusten.** Nicht, weil das
      huebscher aussieht, sondern weil sonst jede Auswertung nach Fehlern
      flach herauskaeme und man nicht erkennen wuerde, ob sie ueberhaupt
      etwas misst.
    """
    import random
    from datetime import timezone

    rng = random.Random(4711)
    trades = s.query(m.Trade).all()
    verknuepft = 0
    notizen = 0
    haken = 0
    # Von Hand abgehakt wird nur, was keine Pruefung traegt -- die
    # anderen lehnt die API zu Recht ab.
    pruefbare = [r for r in pb.rules if r.checkable and not r.auto_check]

    notiztexte = [
        "Plan war sauber, Ausfuehrung auch. Nichts zu aendern.",
        "Zu frueh raus. Ziel lag 20 Pips weiter, Angst war schneller.",
        "Setup war da, aber die Groesse war zu hoch fuer den Abstand.",
        "Nachgekauft, obwohl die Regel es verbietet. Ist diesmal gutgegangen.",
        "Kein klares Signal -- eigentlich haette ich nicht handeln duerfen.",
        "Stop sass richtig, der Markt hat ihn nur gestreift.",
    ]

    for t in trades:
        verlust = float(t.net_pnl or 0) < 0

        if rng.random() < 0.72:
            s.add(m.TradeTag(trade_id=t.id,
                             tag_id=marken[rng.choice(setups)].id))
            verknuepft += 1

        # Fehler ueberwiegend bei Verlusten -- sonst misst die Auswertung
        # nach Fehlern nichts.
        if rng.random() < (0.42 if verlust else 0.08):
            s.add(m.TradeTag(trade_id=t.id,
                             tag_id=marken[rng.choice(fehler)].id))
            verknuepft += 1

        if rng.random() < 0.3:
            s.add(m.TradeTag(trade_id=t.id,
                             tag_id=marken[rng.choice(emotionen)].id))
            verknuepft += 1

        if rng.random() < 0.22:
            t.note = rng.choice(notiztexte)
            notizen += 1

        if rng.random() < 0.35:
            t.playbook_id = pb.id
            haken += beantworte_regeln(s, rng, t, pruefbare, verlust)

    # Tagesjournale fuer einen Teil der Handelstage.
    tagebuch = 0
    tagestexte = [
        "Ruhiger Tag. Zwei Setups gesehen, eins genommen, das war richtig.",
        "Zu viel gehandelt. Nach dem zweiten Verlust haette ich aufhoeren muessen.",
        "Guter Rhythmus. Keine Regel gebrochen, Groesse konstant gehalten.",
        "Schwacher Start, dann gefangen. Das Ergebnis taeuscht ueber den Verlauf.",
        "Muede angefangen. Merke: an solchen Tagen kleiner anfangen.",
    ]
    for konto_id in {t.account_id for t in trades}:
        tage = sorted({
            (t.closed_at or t.opened_at).date()
            for t in trades if t.account_id == konto_id
        })
        for tag in tage:
            if rng.random() < 0.4:
                s.add(m.JournalEntry(
                    account_id=konto_id,
                    entry_date=tag,
                    body=rng.choice(tagestexte),
                    mood=rng.choice([2, 3, 3, 4, 4, 5]),
                ))
                tagebuch += 1

    s.commit()
    print(f"  {verknuepft} Tag-Zuordnungen, {notizen} Notizen, "
          f"{tagebuch} Tagesjournale, {haken} Regel-Antworten")


if __name__ == "__main__":
    main()

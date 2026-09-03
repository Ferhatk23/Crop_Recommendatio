"""Legt eine Entwicklungsdatenbank mit Beispieldaten an."""
from __future__ import annotations

import os
import sys
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradediary.db import models as m
from tradediary.db.repository import (aufnehmen, engine_bauen, schema_anlegen,
                                      session_factory)
from tradediary.demo.seed import erzeuge_deals

URL = os.environ.get("TRADEDIARY_DB", "sqlite:///tradediary.db")


def main() -> None:
    pfad = URL.replace("sqlite:///", "")
    if URL.startswith("sqlite") and os.path.exists(pfad):
        os.remove(pfad)
        print(f"alte Datenbank entfernt: {pfad}")

    engine = engine_bauen(URL)
    schema_anlegen(engine)
    Session = session_factory(engine)

    with Session() as s:
        user = m.User(email="ferhat@example.com", password_hash="!dev")
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
        for label, art in [("Breakout", m.TagArt.SETUP),
                           ("Pullback", m.TagArt.SETUP),
                           ("News-Fade", m.TagArt.SETUP),
                           ("zu frueh raus", m.TagArt.FEHLER),
                           ("Regel gebrochen", m.TagArt.FEHLER),
                           ("nachgekauft", m.TagArt.FEHLER),
                           ("ruhig", m.TagArt.EMOTION),
                           ("ungeduldig", m.TagArt.EMOTION)]:
            s.add(m.Tag(user_id=user.id, label=label, kind=art))

        pb = m.Playbook(user_id=user.id, name="London Breakout",
                        description="Ausbruch aus der asiatischen Range.")
        s.add(pb)
        s.flush()
        regeln = [
            ("Aufbau", "Asiatische Range sauber abgegrenzt", False),
            ("Aufbau", "Ueber VWAP", True),
            ("Einstieg", "Ausbruch mit Volumen bestaetigt", False),
            ("Risiko", "Stop hinter der Range", True),
            ("Risiko", "Hoechstens 1 % Risiko", True),
            ("Verhalten", "Nicht nachgekauft", True),
        ]
        for i, (gruppe, text, pruefbar) in enumerate(regeln):
            s.add(m.PlaybookRule(playbook_id=pb.id, group_label=gruppe,
                                 text=text, checkable=pruefbar, sort_order=i))
        s.commit()

        gesamt = s.query(m.Trade).count()
        print(f"\nFertig: {gesamt} Trades in {pfad}")


if __name__ == "__main__":
    main()

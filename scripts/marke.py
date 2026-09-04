"""Zugangsmarken für den Sammler anlegen und zurückziehen.

Der Sammler läuft ohne Browser und braucht deshalb einen eigenen Zugang.
Diese Marke darf **nur einliefern**, nicht lesen -- sie steht dauerhaft in
einer Datei auf dem Dauerrechner, und wer diese Datei findet, soll damit
weder Notizen lesen noch Kontostände sehen können.

    python scripts/marke.py anlegen 1 --label "Ubuntu-Sammler"
    python scripts/marke.py liste
    python scripts/marke.py zurueckziehen 3

Die Marke wird **einmal** ausgegeben. Danach steht in der Datenbank nur
noch ihr Hash -- wie bei einem Passwort. Verloren heißt: neue anlegen und
die alte zurückziehen.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from tradediary.db import models as m
from tradediary.db.repository import engine_bauen, schema_anlegen, session_factory
from tradediary.sicherheit import neue_marke

URL = os.environ.get("TRADEDIARY_DB", "sqlite:///tradediary.db")


def _sitzung():
    engine = engine_bauen(URL)
    schema_anlegen(engine)
    return session_factory(engine)()


def anlegen(account_id: int, label: str = "Sammler") -> None:
    with _sitzung() as s:
        konto = s.get(m.Account, account_id)
        if konto is None:
            print(f"Kein Konto mit der Nummer {account_id}.")
            print("Vorhandene Konten:")
            for k in s.scalars(select(m.Account).order_by(m.Account.id)).all():
                print(f"  {k.id:>3}  {k.label}")
            raise SystemExit(1)

        marke = neue_marke()
        s.add(
            m.Zugangsmarke(
                user_id=konto.user_id,
                account_id=konto.id,
                token_hash=marke.hash,
                label=label,
            )
        )
        s.commit()

    print(f"Marke für Konto {account_id} ({konto.label}) angelegt.\n")
    print("=" * 66)
    print("  Diese Zeile wird genau einmal angezeigt:\n")
    print(f"    TRADEDIARY_TOKEN={marke.klartext}")
    print("=" * 66)
    print("\n  Gehört in die .env des Sammlers -- nicht ins Repository.")
    print("  Verloren? Neue anlegen, alte zurueckziehen.")


def liste() -> None:
    with _sitzung() as s:
        marken = s.scalars(
            select(m.Zugangsmarke).order_by(m.Zugangsmarke.id)
        ).all()
        if not marken:
            print("Keine Marken. Anlegen mit:")
            print("  python scripts/marke.py anlegen <konto-nummer>")
            return
        print(f"  {'ID':>3}  {'Konto':>5}  {'Bezeichnung':<24} zuletzt benutzt")
        for marke in marken:
            benutzt = (
                marke.last_used.strftime("%d.%m.%Y %H:%M")
                if marke.last_used
                else "nie"
            )
            print(
                f"  {marke.id:>3}  {marke.account_id:>5}  "
                f"{marke.label:<24} {benutzt}"
            )


def zurueckziehen(marke_id: int) -> None:
    with _sitzung() as s:
        marke = s.get(m.Zugangsmarke, marke_id)
        if marke is None:
            print(f"Keine Marke mit der Nummer {marke_id}.")
            raise SystemExit(1)
        s.delete(marke)
        s.commit()
    print(f"Marke {marke_id} zurückgezogen. Der Sammler kann nicht mehr einliefern.")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)

    befehl = sys.argv[1]

    if befehl == "liste":
        liste()
    elif befehl == "anlegen":
        if len(sys.argv) < 3:
            print("Konto-Nummer fehlt: python scripts/marke.py anlegen <nummer>")
            raise SystemExit(2)
        label = "Sammler"
        if "--label" in sys.argv:
            label = sys.argv[sys.argv.index("--label") + 1]
        anlegen(int(sys.argv[2]), label)
    elif befehl == "zurueckziehen":
        if len(sys.argv) < 3:
            print("Marken-Nummer fehlt.")
            raise SystemExit(2)
        zurueckziehen(int(sys.argv[2]))
    else:
        print(__doc__)
        raise SystemExit(2)


if __name__ == "__main__":
    main()

"""Nutzer anlegen und Passwörter setzen.

Es gibt bewusst keine Registrierung in der App. Ein selbstbetriebenes
Journal für eine Person braucht keine, und ein offenes Anmeldeformular
im Netz ist eine Einladung.

    python scripts/nutzer.py anlegen ferhat@example.com
    python scripts/nutzer.py passwort ferhat@example.com
    python scripts/nutzer.py liste
    python scripts/nutzer.py abmelden ferhat@example.com

Das Passwort wird abgefragt, nicht als Argument übergeben: Argumente
stehen in der Shell-Historie und in der Prozessliste, wo jeder andere
Nutzer desselben Rechners sie lesen kann.
"""

from __future__ import annotations

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from tradediary.db import models as m
from tradediary.db.repository import session_factory
from tradediary.sicherheit import MINDESTLAENGE, PasswortZuKurz, hashe_passwort

from datenbank import datenbank_url, sitzung  # noqa: E402

URL = datenbank_url()


def _sitzung():
    """Siehe `scripts/datenbank.py` -- bricht ab statt eine leere
    Datenbank am falschen Ort anzulegen."""
    return sitzung(anlegen_erlaubt="--neu" in sys.argv)


def _passwort_abfragen() -> str:
    """Zweimal eingeben lassen. Ein Tippfehler sperrt sonst dauerhaft aus."""
    while True:
        erste = getpass.getpass("Passwort: ")
        if len(erste) < MINDESTLAENGE:
            print(
                f"  Mindestens {MINDESTLAENGE} Zeichen. Ein langer Satz ist "
                "besser als ein kurzes Sonderzeichen-Rätsel.\n"
            )
            continue
        if erste != getpass.getpass("Noch einmal: "):
            print("  Stimmt nicht überein.\n")
            continue
        return erste


def anlegen(email: str) -> None:
    with _sitzung() as s:
        if s.scalars(
            select(m.User).where(func.lower(m.User.email) == email.lower())
        ).first():
            print(f"Gibt es schon: {email}")
            print("Zum Ändern des Passworts: scripts/nutzer.py passwort <email>")
            raise SystemExit(1)

        passwort = _passwort_abfragen()
        s.add(m.User(email=email.strip().lower(), password_hash=hashe_passwort(passwort)))
        s.commit()
    print(f"Angelegt: {email}")


def passwort(email: str) -> None:
    with _sitzung() as s:
        nutzer = s.scalars(
            select(m.User).where(func.lower(m.User.email) == email.lower())
        ).first()
        if nutzer is None:
            print(f"Kein Nutzer: {email}")
            raise SystemExit(1)

        neu = _passwort_abfragen()
        nutzer.password_hash = hashe_passwort(neu)

        # Alle Sitzungen beenden. Wer sein Passwort ändert, tut das oft,
        # weil er vermutet, dass jemand anderes es kennt -- dann muessen
        # auch dessen offene Sitzungen weg.
        offen = s.scalars(
            select(m.Sitzung).where(m.Sitzung.user_id == nutzer.id)
        ).all()
        for sitzung in offen:
            s.delete(sitzung)
        s.commit()

    print(f"Passwort geändert: {email}")
    print(f"{len(offen)} offene Sitzung(en) beendet -- bitte neu anmelden.")


def abmelden(email: str) -> None:
    """Beendet alle Sitzungen eines Nutzers, ohne das Passwort zu ändern."""
    with _sitzung() as s:
        nutzer = s.scalars(
            select(m.User).where(func.lower(m.User.email) == email.lower())
        ).first()
        if nutzer is None:
            print(f"Kein Nutzer: {email}")
            raise SystemExit(1)
        offen = s.scalars(
            select(m.Sitzung).where(m.Sitzung.user_id == nutzer.id)
        ).all()
        for sitzung in offen:
            s.delete(sitzung)
        s.commit()
    print(f"{len(offen)} Sitzung(en) beendet.")


def liste() -> None:
    with _sitzung() as s:
        nutzer = s.scalars(select(m.User).order_by(m.User.id)).all()
        if not nutzer:
            print("Noch kein Nutzer. Anlegen mit:")
            print("  python scripts/nutzer.py anlegen <email>")
            return
        for n in nutzer:
            konten = s.scalars(
                select(func.count()).select_from(m.Account).where(
                    m.Account.user_id == n.id
                )
            ).one()
            sitzungen = s.scalars(
                select(func.count()).select_from(m.Sitzung).where(
                    m.Sitzung.user_id == n.id
                )
            ).one()
            print(f"  {n.id:>3}  {n.email:<36} {konten} Konten, {sitzungen} Sitzungen")


BEFEHLE = {"anlegen": anlegen, "passwort": passwort, "abmelden": abmelden}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {*BEFEHLE, "liste"}:
        print(__doc__)
        raise SystemExit(2)

    befehl = sys.argv[1]
    if befehl == "liste":
        liste()
        return

    if len(sys.argv) < 3:
        print(f"E-Mail fehlt: python scripts/nutzer.py {befehl} <email>")
        raise SystemExit(2)

    try:
        BEFEHLE[befehl](sys.argv[2])
    except PasswortZuKurz as fehler:
        print(fehler)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

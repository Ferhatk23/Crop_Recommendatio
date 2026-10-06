"""Passwörter und Sitzungsmarken.

Weder Handelslogik noch Schnittstelle -- deshalb eine eigene Datei. Was
hier steht, ist reine Rechnerei über Bytes und lässt sich ohne Datenbank
und ohne HTTP prüfen. Genau das ist der Punkt: Sicherheitscode, den man
nur im Zusammenspiel testen kann, testet am Ende niemand.

**Ohne zusätzliche Abhängigkeit.** `hashlib.scrypt` steht in der
Standardbibliothek und ist ein speicherhartes Verfahren -- also genau
das, was man für Passwörter will. bcrypt oder argon2 wären ebenso
richtig, kosteten aber eine Abhängigkeit mit C-Erweiterung, die bei
jedem Aufsetzen kompiliert sein will.

Was hier *nicht* passiert, ist genauso wichtig:

* **Kein Klartext-Passwort verlässt diese Datei.** Es wird
  entgegengenommen, verrechnet und fällt aus dem Gültigkeitsbereich.
* **Kein Vergleich mit `==`.** Ein normaler Vergleich bricht beim ersten
  abweichenden Byte ab; wie lange er dauert, verrät, wie weit man
  gekommen ist. `hmac.compare_digest` braucht immer gleich lang.
* **Die Sitzungsmarke steht nicht in der Datenbank**, nur ihr Hash. Wer
  die Datenbank in die Hände bekommt, hat damit noch keine gültige
  Sitzung -- so wie er mit den Passwort-Hashes noch kein Passwort hat.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

#: scrypt-Parameter. `n` ist die Kostenschraube: 2^15 braucht rund 32 MB
#: und knapp 100 ms je Prüfung. Das ist für eine Anmeldung nicht spürbar
#: und macht das Durchprobieren von Passwortlisten teuer.
#:
#: Die Werte stehen im Hash mit drin. Wer sie später erhöht, kann alte
#: Hashes weiter prüfen -- sie tragen ihre eigenen Parameter.
N = 2**15
R = 8
P = 1
DKLEN = 32
SALZ_LAENGE = 16

#: Obergrenze für den Speicher, den eine einzelne Berechnung nehmen darf.
#:
#: Muss ausdrücklich gesetzt werden: OpenSSL erlaubt von sich aus 32 MB,
#: und `N = 2**15` braucht ``128 * n * r`` = 33,5 MB -- knapp darüber.
#: Ohne diesen Wert scheitert schon das Setzen des ersten Passworts mit
#: "memory limit exceeded".
#:
#: Sie ist zugleich eine Schranke in die andere Richtung. Beim Prüfen
#: kommen `n`, `r` und `p` aus dem gespeicherten Hash. Stünde dort ein
#: unsinnig großes `n` -- durch einen Fehler oder durch einen manipulierten
#: Datensatz --, versuchte der Rechner, Gigabytes zu belegen. Mit der
#: Grenze bricht die Berechnung stattdessen ab, und die Prüfung gibt
#: schlicht `False` zurück.
MAXMEM = 96 * 1024 * 1024

#: Mindestlänge. Bewusst niedrig und dafür ohne Zeichenklassen-Regeln:
#: Die erzwingen "Passwort1!" statt eines langen Satzes und machen ein
#: Passwort damit eher schlechter.
#:
#: Die Regel ist ein grobes Werkzeug, und sie ist nicht gerecht: Sie zählt
#: Zeichen, nicht Aussagekraft. "日本語のパスワード" hat neun Zeichen und
#: fällt durch, "aaaaaaaaaa" hat zehn und kommt durch -- obwohl das erste
#: ungleich schwerer zu erraten ist. Wer ein Wörterbuch anwirft, sieht den
#: Unterschied sofort, die Längenregel nie.
#:
#: Trotzdem bleibt sie: Der einzige ehrliche Ersatz wäre eine echte
#: Schätzung der Erratbarkeit (zxcvbn und Ähnliches), und die kostet eine
#: Abhängigkeit mit Wörterbüchern in mehreren Sprachen. Für ein
#: selbstbetriebenes Journal mit einem Nutzer ist das die falsche Rechnung.
#: Sie hier zu notieren ist ehrlicher, als so zu tun, als wäre die Zahl
#: ein Sicherheitsmaß.
MINDESTLAENGE = 10


class PasswortZuKurz(ValueError):
    """Wird beim Setzen geworfen, nie beim Prüfen."""


def hashe_passwort(passwort: str, *, pruefe_laenge: bool = True) -> str:
    """Verrechnet ein Passwort zu einem selbstbeschreibenden Hash.

    Format: ``scrypt$n$r$p$salz$hash`` -- alles hexadezimal. Die
    Parameter stehen mit drin, damit sie sich später erhöhen lassen,
    ohne alle Hashes ungültig zu machen.
    """
    if pruefe_laenge and len(passwort) < MINDESTLAENGE:
        raise PasswortZuKurz(
            f"Passwort braucht mindestens {MINDESTLAENGE} Zeichen. "
            "Ein langer Satz ist besser als ein kurzes Sonderzeichen-Rätsel."
        )

    salz = secrets.token_bytes(SALZ_LAENGE)
    roh = hashlib.scrypt(
        passwort.encode("utf-8"),
        salt=salz,
        n=N,
        r=R,
        p=P,
        dklen=DKLEN,
        maxmem=MAXMEM,
    )
    return f"scrypt${N}${R}${P}${salz.hex()}${roh.hex()}"


def pruefe_passwort(passwort: str, gespeichert: str) -> bool:
    """Prüft ein Passwort gegen einen gespeicherten Hash.

    Gibt bei jedem Fehler `False` zurück, nie eine Ausnahme: Ein
    beschädigter Hash in der Datenbank darf die Anmeldung ablehnen, aber
    keine Fehlermeldung erzeugen, aus der sich etwas ablesen ließe.
    """
    try:
        art, n, r, p, salz_hex, hash_hex = gespeichert.split("$")
        if art != "scrypt":
            return False
        roh = hashlib.scrypt(
            passwort.encode("utf-8"),
            salt=bytes.fromhex(salz_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(hash_hex) // 2,
            maxmem=MAXMEM,
        )
    except (ValueError, TypeError, MemoryError):
        return False

    return hmac.compare_digest(roh.hex(), hash_hex)


#: Ein Hash, gegen den geprüft wird, wenn es die E-Mail gar nicht gibt.
#:
#: Ohne ihn wäre die Anmeldung für unbekannte Adressen messbar schneller
#: als für bekannte -- und damit ließe sich herausfinden, welche Adressen
#: es gibt, ohne ein einziges Passwort zu erraten. Der Wert wird beim
#: ersten Zugriff erzeugt, damit der Import nicht 100 ms kostet.
_BLIND: str | None = None


def blindprüfung(passwort: str) -> bool:
    """Verbrennt dieselbe Rechenzeit wie eine echte Prüfung. Immer `False`."""
    global _BLIND
    if _BLIND is None:
        _BLIND = hashe_passwort(secrets.token_urlsafe(32), pruefe_laenge=False)
    pruefe_passwort(passwort, _BLIND)
    return False


# ---------------------------------------------------------------------------
# Sitzungen
# ---------------------------------------------------------------------------

#: Länge der Sitzungsmarke in Bytes vor der Base64-Kodierung.
MARKEN_BYTES = 32


@dataclass(frozen=True)
class Marke:
    """Eine frische Sitzungsmarke.

    `klartext` geht einmal an den Browser und wird nie gespeichert.
    `hash` geht in die Datenbank und nie an den Browser.
    """

    klartext: str
    hash: str


def neue_marke() -> Marke:
    klartext = secrets.token_urlsafe(MARKEN_BYTES)
    return Marke(klartext=klartext, hash=marken_hash(klartext))


def marken_hash(klartext: str) -> str:
    """Der Datenbank-Wert zu einer Marke.

    Hier reicht ein einfacher SHA-256 ohne Salz und ohne Kostenschraube --
    anders als bei Passwörtern. Eine Marke sind 32 zufällige Bytes; die
    kann man nicht erraten und nicht in einer Liste nachschlagen. Die
    teure Rechnerei bei Passwörtern schützt gegen genau das, und beides
    zu verwechseln kostet bei jeder einzelnen Anfrage 100 ms.
    """
    return hashlib.sha256(klartext.encode("utf-8")).hexdigest()

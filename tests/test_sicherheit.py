"""Tests für Passwörter und Sitzungsmarken.

Sicherheitscode hat eine unangenehme Eigenschaft: Er sieht auch dann
richtig aus, wenn er falsch ist. Ein Passwortvergleich mit `==` besteht
jeden funktionalen Test -- und verrät trotzdem über die Laufzeit, wie
viele Zeichen schon stimmen.
"""

from __future__ import annotations

import pytest

from tradediary import sicherheit


# ---------------------------------------------------------------------------
# Passwörter
# ---------------------------------------------------------------------------

def test_richtiges_passwort_wird_erkannt():
    h = sicherheit.hashe_passwort("ein langer satz als passwort")
    assert sicherheit.pruefe_passwort("ein langer satz als passwort", h)


def test_falsches_passwort_wird_abgelehnt():
    h = sicherheit.hashe_passwort("ein langer satz als passwort")
    assert not sicherheit.pruefe_passwort("ein langer satz als passwor", h)
    assert not sicherheit.pruefe_passwort("", h)
    assert not sicherheit.pruefe_passwort("völlig anderes passwort", h)


def test_das_passwort_steht_nicht_im_hash():
    """Klingt selbstverständlich, ist aber die eine Sache, die zählt."""
    passwort = "Butterbrot-Fahrrad-Dienstag"
    h = sicherheit.hashe_passwort(passwort)
    assert passwort not in h
    assert passwort.lower() not in h.lower()


def test_gleiches_passwort_ergibt_verschiedene_hashes():
    """Jeder Hash bekommt sein eigenes Salz.

    Ohne das hätten zwei Nutzer mit demselben Passwort denselben Hash --
    und eine vorberechnete Tabelle knackte beide auf einmal.
    """
    a = sicherheit.hashe_passwort("ein langer satz als passwort")
    b = sicherheit.hashe_passwort("ein langer satz als passwort")
    assert a != b
    assert sicherheit.pruefe_passwort("ein langer satz als passwort", a)
    assert sicherheit.pruefe_passwort("ein langer satz als passwort", b)


def test_hash_traegt_seine_parameter():
    """Damit sich die Kostenschraube später erhöhen lässt."""
    h = sicherheit.hashe_passwort("ein langer satz als passwort")
    teile = h.split("$")
    assert teile[0] == "scrypt"
    assert int(teile[1]) == sicherheit.N
    assert int(teile[2]) == sicherheit.R
    assert int(teile[3]) == sicherheit.P


def test_alter_hash_mit_schwaecheren_parametern_bleibt_pruefbar():
    """Der Sinn der mitgeführten Parameter.

    Wer `N` erhöht, darf niemanden aussperren, der sich seit der
    Änderung nicht angemeldet hat.
    """
    import hashlib

    salz = b"0123456789abcdef"
    roh = hashlib.scrypt(b"altes passwort", salt=salz, n=2**12, r=8, p=1, dklen=32)
    alt = f"scrypt$4096$8$1${salz.hex()}${roh.hex()}"
    assert sicherheit.pruefe_passwort("altes passwort", alt)
    assert not sicherheit.pruefe_passwort("anderes passwort", alt)


def test_zu_kurzes_passwort_wird_beim_setzen_abgelehnt():
    with pytest.raises(sicherheit.PasswortZuKurz):
        sicherheit.hashe_passwort("kurz")


def test_laengenpruefung_gilt_nur_beim_setzen():
    """Beim Prüfen darf die Länge keine Rolle spielen.

    Sonst führte eine spätere Erhöhung der Mindestlänge dazu, dass sich
    Bestandsnutzer nicht mehr anmelden können.
    """
    h = sicherheit.hashe_passwort("kurz", pruefe_laenge=False)
    assert sicherheit.pruefe_passwort("kurz", h)


@pytest.mark.parametrize(
    "kaputt",
    [
        "",
        "nur-text",
        "scrypt$16384$8$1$nichthex$auchnichthex",
        "bcrypt$16384$8$1$aabb$ccdd",
        "scrypt$viel$zu$wenig",
        "scrypt$0$8$1$aabb$ccdd",  # n=0 ist ungültig
        "scrypt$16384$8$1$aabb",
    ],
)
def test_beschaedigter_hash_lehnt_ab_statt_zu_werfen(kaputt):
    """Eine Ausnahme wäre eine Auskunft.

    Wer aus der Fehlermeldung ablesen kann, dass ein Datensatz beschädigt
    ist, weiß mehr als er soll -- und ein Fehler 500 beim Anmelden sieht
    aus wie ein Angriffspunkt.
    """
    assert sicherheit.pruefe_passwort("egal", kaputt) is False


def test_umlaute_und_emoji_im_passwort():
    """UTF-8 sauber durchgereicht -- sonst scheitert die Anmeldung später.

    Ein Passwort wird auf einem Mac gesetzt und auf einem iPhone
    eingegeben. Geht dabei die Kodierung verloren, merkt man es erst,
    wenn man sich nicht mehr anmelden kann.
    """
    for passwort in [
        "Müßiggang-Öl-Straße",
        "passwort mit 🔒 drin",
        "日本語のパスワードです",
    ]:
        h = sicherheit.hashe_passwort(passwort)
        assert sicherheit.pruefe_passwort(passwort, h)
        # Ein Byte anders, und es passt nicht mehr.
        assert not sicherheit.pruefe_passwort(passwort + " ", h)


def test_die_laengenregel_zaehlt_zeichen_keine_aussagekraft():
    """Festgehalten, weil es eine echte Schwäche ist und keine Absicht.

    Neun japanische Zeichen sind ungleich schwerer zu erraten als zehn
    gleiche Buchstaben -- die Regel sieht nur die Länge. Wer sie später
    durch eine echte Schätzung ersetzt, soll hier lesen können, was sie
    nie geleistet hat.
    """
    with pytest.raises(sicherheit.PasswortZuKurz):
        sicherheit.hashe_passwort("日本語のパスワード")  # 9 Zeichen
    sicherheit.hashe_passwort("aaaaaaaaaa")  # 10 Zeichen, geht durch


def test_blindpruefung_ist_immer_falsch():
    """Sie verbrennt nur Zeit -- damit unbekannte E-Mails nicht schneller
    abgelehnt werden als bekannte."""
    assert sicherheit.blindprüfung("irgendwas") is False
    assert sicherheit.blindprüfung("") is False


# ---------------------------------------------------------------------------
# Sitzungsmarken
# ---------------------------------------------------------------------------

def test_marken_sind_verschieden():
    marken = {sicherheit.neue_marke().klartext for _ in range(200)}
    assert len(marken) == 200


def test_marke_ist_lang_genug():
    """32 Bytes Zufall. Kürzer wäre erratbar, und eine Marke ist ein
    vollwertiger Ersatz für das Passwort."""
    marke = sicherheit.neue_marke()
    assert len(marke.klartext) >= 40  # 32 Bytes base64url


def test_die_marke_steht_nicht_in_ihrem_hash():
    """Der Datenbankwert darf die Marke nicht hergeben.

    Sonst wäre ein Blick in die Datenbank gleichbedeutend mit dem Besitz
    jeder gerade offenen Sitzung.
    """
    marke = sicherheit.neue_marke()
    assert marke.klartext not in marke.hash
    assert marke.hash != marke.klartext


def test_marken_hash_ist_wiederholbar():
    """Sonst fände man die Sitzung beim nächsten Aufruf nicht wieder."""
    marke = sicherheit.neue_marke()
    assert sicherheit.marken_hash(marke.klartext) == marke.hash

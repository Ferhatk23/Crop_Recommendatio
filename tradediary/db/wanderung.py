"""Schema-Wanderungen: neue Spalten in bestehenden Tabellen.

`create_all` legt **fehlende Tabellen** an und fasst vorhandene nicht an.
Für neue Tabellen reicht das -- nachgemessen an einer Datenbank ohne
`trade_rule_checks`: nach dem nächsten Start war sie da. Für eine neue
**Spalte** reicht es nicht, und das Scheitern sieht harmlos aus: Die App
startet, meldet nichts, und erst der erste Aufruf, der die Spalte
anfasst, wirft `no such column`.

Genau das ist beim Commit „Regeln messen statt fragen" passiert.
`playbook_rules` bekam `auto_check` und `auto_param`; eine bestehende
Datenbank behielt die alte Tabelle, und `/api/playbooks` starb. Hier
nachgestellt und gemessen, nicht vermutet.

Warum kein Alembic
------------------
Alembics Wert liegt in Autogenerate, Downgrades und Verzweigungen. Für
ein Journal mit einem Nutzer ist davon nichts nötig: Es gibt keine
parallelen Entwicklungszweige und keinen Grund, ein Schema
zurückzurollen -- dafür liegt die tägliche Sicherung bereit. Autogenerate
wäre an SQLite ohnehin heikel, weil SQLite kaum etwas ändern kann ausser
Spalten anzuhängen.

Warum selbsterkennend statt durchnummeriert
-------------------------------------------
Eine bestehende Datenbank ist älter als jede Versionstabelle. Ihr eine
Nummer zuzuweisen hiesse zu raten, welchen Stand sie hat -- und ein
falsches Stempeln überspringt stillschweigend eine nötige Wanderung.
Jeder Schritt hier prüft deshalb selbst, ob er gebraucht wird. Das macht
ihn zugleich wiederholbar: Zweimal gestartet passiert einmal etwas.

Warum nur Spalten anhängen
--------------------------
Ein Schritt besteht aus Tabelle, Spalte und Typ -- kein beliebiges SQL.
Damit *kann* hier nichts Zerstörerisches stehen, nicht einmal
versehentlich, und die Datei ist auf einen Blick prüfbar. Alles
Schwierigere -- eine Spalte umbenennen, einen Typ ändern, Daten umbauen
-- gehört von Hand gemacht, mit einer Sicherung davor, und nicht still
beim Hochfahren.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import inspect, text


@dataclass(frozen=True)
class Spaltenschritt:
    """Eine Spalte, die einer bestehenden Tabelle fehlen kann.

    `typ` ist absichtlich SQL-Text und nicht der SQLAlchemy-Typ: Was hier
    steht, geht wortwörtlich in ein `ALTER TABLE`. Eine Spalte ohne
    `NOT NULL` und ohne Vorgabewert lässt sich auf beiden Datenbanken
    anhängen, ohne die vorhandenen Zeilen anzufassen.
    """

    tabelle: str
    spalte: str
    typ: str
    grund: str

    @property
    def name(self) -> str:
        return f"{self.tabelle}.{self.spalte}"


#: In der Reihenfolge, in der sie entstanden sind. Neue kommen unten dazu;
#: eine einmal ausgelieferte Zeile wird nicht mehr geändert.
SCHRITTE: tuple[Spaltenschritt, ...] = (
    Spaltenschritt(
        tabelle="playbook_rules",
        spalte="auto_check",
        typ="VARCHAR(40)",
        grund="Regeln, die aus den Deals beantwortet werden",
    ),
    Spaltenschritt(
        tabelle="playbook_rules",
        spalte="auto_param",
        typ="VARCHAR(40)",
        grund="die Zahl zur Prüfung, etwa 1 für ein Prozent",
    ),
)


def _protokoll_anlegen(verbindung) -> None:
    """Die Tabelle, in der steht, was gelaufen ist.

    Sie ist für den Menschen da, nicht für die Logik: Ob ein Schritt nötig
    ist, entscheidet immer die Prüfung am Schema selbst. Wer nach einem
    missglückten Hochfahren wissen will, was die App angefasst hat, findet
    es hier -- und zwar auch dann, wenn die Protokollzeilen fehlen, weil
    die Tabelle neu ist.
    """
    verbindung.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_wanderungen ("
            " name VARCHAR(120) PRIMARY KEY,"
            " gelaufen_am VARCHAR(40) NOT NULL)"
        )
    )


def offene_schritte(engine) -> list[Spaltenschritt]:
    """Was dieser Datenbank fehlt. Fragt das Schema, nicht das Protokoll."""
    pruefer = inspect(engine)
    tabellen = set(pruefer.get_table_names())

    offen = []
    for schritt in SCHRITTE:
        # Fehlt die Tabelle ganz, ist nichts zu wandern: `create_all` legt
        # sie gleich vollständig an.
        if schritt.tabelle not in tabellen:
            continue
        vorhanden = {s["name"] for s in pruefer.get_columns(schritt.tabelle)}
        if schritt.spalte not in vorhanden:
            offen.append(schritt)
    return offen


def wandern(engine) -> list[str]:
    """Hängt die fehlenden Spalten an. Gibt zurück, was getan wurde.

    Wiederholbar: Ein zweiter Lauf findet nichts mehr und tut nichts.
    """
    offen = offene_schritte(engine)
    if not offen:
        return []

    getan = []
    with engine.begin() as verbindung:
        _protokoll_anlegen(verbindung)
        for schritt in offen:
            verbindung.execute(
                text(
                    f"ALTER TABLE {schritt.tabelle}"
                    f" ADD COLUMN {schritt.spalte} {schritt.typ}"
                )
            )
            # Erst löschen, dann schreiben: `INSERT OR REPLACE` kennt nur
            # SQLite, und das Schema soll auch auf Postgres laufen. Der
            # Fall tritt nur auf, wenn jemand eine Spalte von Hand wieder
            # entfernt hat -- dann ist der alte Protokolleintrag falsch.
            verbindung.execute(
                text("DELETE FROM schema_wanderungen WHERE name = :n"),
                {"n": schritt.name},
            )
            verbindung.execute(
                text(
                    "INSERT INTO schema_wanderungen (name, gelaufen_am)"
                    " VALUES (:n, :z)"
                ),
                {"n": schritt.name, "z": datetime.now(timezone.utc).isoformat()},
            )
            getan.append(schritt.name)
    return getan

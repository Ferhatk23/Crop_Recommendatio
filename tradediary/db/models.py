"""Datenbankschema.

Zwei Ebenen, wie im Kern: ``deals`` ist die Wahrheit und wird nie verändert,
``trades`` ist daraus abgeleitet und jederzeit neu berechenbar. Wer die
Zuordnungslogik später korrigiert, lässt einfach neu durchlaufen -- es gehen
keine Daten verloren.

Das Schema ist auf Postgres ausgelegt, läuft in der Entwicklung aber auch
auf SQLite. Deshalb `Numeric` statt `Money` und keine Postgres-eigenen Typen.

Prop-Besonderheit: Konten sterben. Challenge bestanden, Funded, Regel
gerissen, neues Konto -- über die Zeit sammeln sich mehrere an. Sie bleiben
alle erhalten, tragen ihre Phase und ihren Status, und lassen sich einzeln
wie gemeinsam auswerten.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

#: Geldbeträge. 4 Nachkommastellen, weil Swap und Kommission bei kleinen
#: Volumina unter einem Cent liegen können und sich sonst wegrunden.
GELD = Numeric(18, 4)
#: Preise. Forex braucht 5 Stellen, Krypto mehr.
PREIS = Numeric(18, 8)
#: Volumen in Lot.
LOT = Numeric(12, 4)


class Base(DeclarativeBase):
    pass


def jetzt() -> datetime:
    return datetime.now(timezone.utc)


class KontoPhase(str, enum.Enum):
    """Wo im Prop-Prozess ein Konto steht."""

    CHALLENGE = "challenge"
    VERIFICATION = "verification"
    FUNDED = "funded"
    DEMO = "demo"
    LIVE = "live"


class KontoStatus(str, enum.Enum):
    AKTIV = "aktiv"
    BESTANDEN = "bestanden"
    VERLOREN = "verloren"
    ARCHIVIERT = "archiviert"


class TagArt(str, enum.Enum):
    SETUP = "setup"
    FEHLER = "fehler"
    EMOTION = "emotion"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")


class Sitzung(Base):
    """Eine offene Anmeldung.

    Serverseitig statt als selbsttragendes Token (JWT), und das ist eine
    bewusste Wahl: Eine Sitzung, die in der Datenbank steht, lässt sich
    beenden. Ein JWT gilt bis zum Ablauf, egal was dazwischen passiert --
    wer sein iPad verliert, kann es nicht zurückrufen.

    Die Marke selbst steht hier nicht, nur ihr Hash. Wer die Datenbank
    liest, hat damit keine gültige Sitzung in der Hand.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: SHA-256 der Marke. Eindeutig, damit zwei Sitzungen nicht kollidieren.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=jetzt
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    #: Zuletzt benutzt -- damit man in den Einstellungen sieht, welche
    #: Geräte noch angemeldet sind, und alte gezielt beenden kann.
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=jetzt
    )
    #: Grob, wofür es reicht: "Safari auf dem iPhone". Gekürzt, weil ein
    #: vollständiger User-Agent nichts hinzufügt, was man lesen will.
    device: Mapped[str | None] = mapped_column(String(120), default=None)

    user: Mapped["User"] = relationship()


class Account(Base):
    """Ein Handelskonto. Ein Prop-Trader hat über die Zeit mehrere."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    label: Mapped[str] = mapped_column(String(120))
    login: Mapped[str | None] = mapped_column(String(64), default=None)
    broker: Mapped[str | None] = mapped_column(String(120), default=None)
    server: Mapped[str | None] = mapped_column(String(120), default=None)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")

    phase: Mapped[KontoPhase] = mapped_column(
        Enum(KontoPhase, native_enum=False), default=KontoPhase.CHALLENGE
    )
    status: Mapped[KontoStatus] = mapped_column(
        Enum(KontoStatus, native_enum=False), default=KontoStatus.AKTIV
    )
    hedging: Mapped[bool] = mapped_column(Boolean, default=True)

    starting_balance: Mapped[float] = mapped_column(GELD, default=0)
    #: Versatz der Broker-Serverzeit gegenüber UTC in Sekunden. Wird bei
    #: jedem Abgleich neu mitgeliefert, damit Sommerzeitwechsel des Brokers
    #: sich von allein erledigen statt fest verdrahtet zu sein.
    server_utc_offset: Mapped[int] = mapped_column(Integer, default=0)

    # --- Prop-Regeln. Ohne sie kann das Dashboard keinen Puffer zeigen. ---
    #: Maximaler Tagesverlust als positive Zahl.
    daily_loss_limit: Mapped[float | None] = mapped_column(GELD, default=None)
    #: Maximaler Gesamtverlust als positive Zahl.
    max_loss_limit: Mapped[float | None] = mapped_column(GELD, default=None)
    #: Ab welchem Anteil des Limits gewarnt wird (0.8 = 80 %).
    warn_threshold: Mapped[float] = mapped_column(Numeric(4, 3), default=0.8)
    #: Konsistenzregel: höchster erlaubter Anteil eines einzelnen Tages am
    #: Gesamtgewinn. Alpha Capital fährt hier 40 %.
    consistency_limit: Mapped[float | None] = mapped_column(
        Numeric(4, 3), default=None
    )
    profit_target: Mapped[float | None] = mapped_column(GELD, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    user: Mapped["User"] = relationship(back_populates="accounts")
    deals: Mapped[list["Deal"]] = relationship(back_populates="account")
    trades: Mapped[list["Trade"]] = relationship(back_populates="account")


class Deal(Base):
    """Eine einzelne Ausführung, roh vom Broker. Wird nie verändert."""

    __tablename__ = "deals"
    __table_args__ = (
        UniqueConstraint("account_id", "ticket", name="uq_deal_konto_ticket"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Die Nummer, die MT5 vergibt. Zusammen mit dem Konto der fachliche
    #: Schlüssel -- deshalb darf derselbe Zeitraum beliebig oft abgefragt
    #: werden, ohne dass Dubletten entstehen.
    ticket: Mapped[int] = mapped_column(Integer, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    position_id: Mapped[int] = mapped_column(Integer, index=True)

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(16))
    entry: Mapped[str] = mapped_column(String(16))
    volume: Mapped[float] = mapped_column(LOT)
    price: Mapped[float] = mapped_column(PREIS)

    time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    #: Broker-Serverzeit, nur zur Anzeige. Gerechnet wird auf UTC -- beides
    #: speichern, damit die Umrechnung nachvollziehbar bleibt.
    time_broker: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), default=None
    )

    profit: Mapped[float] = mapped_column(GELD, default=0)
    commission: Mapped[float] = mapped_column(GELD, default=0)
    swap: Mapped[float] = mapped_column(GELD, default=0)
    fee: Mapped[float] = mapped_column(GELD, default=0)
    stop_loss: Mapped[float | None] = mapped_column(PREIS, default=None)

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=jetzt
    )

    account: Mapped["Account"] = relationship(back_populates="deals")


class Trade(Base):
    """Ein vollständiger Round-Trip. Aus Deals abgeleitet, neu berechenbar."""

    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("account_id", "position_id", name="uq_trade_konto_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    position_id: Mapped[int] = mapped_column(Integer, index=True)

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )

    volume: Mapped[float] = mapped_column(LOT)
    exit_volume: Mapped[float] = mapped_column(LOT, default=0)
    avg_entry: Mapped[float | None] = mapped_column(PREIS, default=None)
    avg_exit: Mapped[float | None] = mapped_column(PREIS, default=None)

    gross_pnl: Mapped[float] = mapped_column(GELD, default=0)
    costs: Mapped[float] = mapped_column(GELD, default=0)
    net_pnl: Mapped[float] = mapped_column(GELD, default=0, index=True)

    initial_sl: Mapped[float | None] = mapped_column(PREIS, default=None)
    risk_amount: Mapped[float | None] = mapped_column(GELD, default=None)
    r_multiple: Mapped[float | None] = mapped_column(Numeric(12, 4), default=None)

    #: Bruchstück: Ergebnis stimmt, Einstieg unbekannt, weil die Eröffnung
    #: vor dem abgefragten Zeitraum lag. Am Rand jedes Fensters unvermeidlich.
    partial: Mapped[bool] = mapped_column(Boolean, default=False)
    playbook_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbooks.id"), default=None
    )
    note: Mapped[str | None] = mapped_column(Text, default=None)

    account: Mapped["Account"] = relationship(back_populates="trades")
    tags: Mapped[list["TradeTag"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan"
    )


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "label", "kind", name="uq_tag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    kind: Mapped[TagArt] = mapped_column(Enum(TagArt, native_enum=False))

    trades: Mapped[list["TradeTag"]] = relationship(back_populates="tag")


class TradeTag(Base):
    __tablename__ = "trade_tags"

    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)

    trade: Mapped["Trade"] = relationship(back_populates="tags")
    tag: Mapped["Tag"] = relationship(back_populates="trades")


class Playbook(Base):
    __tablename__ = "playbooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    rules: Mapped[list["PlaybookRule"]] = relationship(
        back_populates="playbook", cascade="all, delete-orphan"
    )


class PlaybookRule(Base):
    """Eine Regel im Playbook.

    Der Unterschied zwischen prüfbar und selbstberichtet ist strukturell,
    nicht kosmetisch: Nur prüfbare Regeln lassen sich aus MT5-Daten
    ableiten und zählen in die Regeltreue. Selbstberichtete werden angezeigt,
    aber aus der Statistik herausgehalten -- sonst misst man Ehrlichkeit
    und nennt es Disziplin.
    """

    __tablename__ = "playbook_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    playbook_id: Mapped[int] = mapped_column(ForeignKey("playbooks.id"), index=True)
    group_label: Mapped[str] = mapped_column(String(120), default="Allgemein")
    text: Mapped[str] = mapped_column(Text)
    checkable: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    playbook: Mapped["Playbook"] = relationship(back_populates="rules")


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("account_id", "entry_date", name="uq_journal_konto_tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    mood: Mapped[int | None] = mapped_column(Integer, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=jetzt, onupdate=jetzt
    )


class SyncState(Base):
    """Herzschlag der Übernahme.

    Kein Detail, sondern die Statuszeile des ganzen Produkts: Ein stiller
    Ausfall der MT5-Anbindung darf niemals genauso aussehen wie "heute
    keine Trades".
    """

    __tablename__ = "sync_state"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(40), default="csv")
    last_deal_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    deals_imported: Mapped[int] = mapped_column(Integer, default=0)

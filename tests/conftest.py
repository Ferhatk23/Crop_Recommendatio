"""Bausteine für die Tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradediary.core.models import Deal, DealEntry, DealType

BASE = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


def D(value) -> Decimal:
    return Decimal(str(value))


def deal(
    ticket: int,
    position_id: int,
    type_: DealType,
    entry: DealEntry,
    volume,
    price,
    minute: int,
    *,
    profit=0,
    commission=0,
    swap=0,
    fee=0,
    symbol: str = "EURUSD",
    account_id: str = "A1",
    stop_loss=None,
) -> Deal:
    """Baut einen Deal mit wenig Zeremonie."""
    return Deal(
        ticket=ticket,
        account_id=account_id,
        position_id=position_id,
        symbol=symbol,
        type=type_,
        entry=entry,
        volume=D(volume),
        price=D(price),
        time_utc=BASE + timedelta(minutes=minute),
        profit=D(profit),
        commission=D(commission),
        swap=D(swap),
        fee=D(fee),
        stop_loss=D(stop_loss) if stop_loss is not None else None,
    )


def buy(ticket, position_id, volume, price, minute, **kw) -> Deal:
    entry = kw.pop("entry", DealEntry.IN)
    return deal(ticket, position_id, DealType.BUY, entry, volume, price, minute, **kw)


def sell(ticket, position_id, volume, price, minute, **kw) -> Deal:
    entry = kw.pop("entry", DealEntry.OUT)
    return deal(ticket, position_id, DealType.SELL, entry, volume, price, minute, **kw)

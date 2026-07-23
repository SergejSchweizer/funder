"""Flatex trade-preparation exports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import floor
from pathlib import Path
from typing import Any

from camovar.table_io import JsonRow, write_csv


def prepare_flatex_orders(
    targets: Sequence[Mapping[str, Any]], *, portfolio_value: float, cash_buffer: float = 0.0
) -> list[JsonRow]:
    if portfolio_value <= 0:
        raise ValueError("portfolio_value must be positive")
    if cash_buffer < 0 or cash_buffer >= 1:
        raise ValueError("cash_buffer must be in [0, 1)")
    investable_value = portfolio_value * (1 - cash_buffer)
    orders: list[JsonRow] = []
    for target in targets:
        weight = float(target["weight"])
        price = float(target["price"])
        if price <= 0:
            raise ValueError(f"price must be positive for {target['isin']}")
        quantity = floor((investable_value * weight) / price)
        orders.append(
            {
                "broker": "Flatex",
                "side": "BUY" if quantity > 0 else "SKIP",
                "isin": str(target["isin"]),
                "code": str(target["code"]),
                "exchange": str(target["exchange"]),
                "currency": str(target["currency"]),
                "target_weight": weight,
                "limit_price": price,
                "quantity": quantity,
                "estimated_value": quantity * price,
            }
        )
    return orders


def write_flatex_orders(path: Path, orders: Sequence[Mapping[str, Any]]) -> None:
    write_csv(
        path,
        orders,
        (
            "broker",
            "side",
            "isin",
            "code",
            "exchange",
            "currency",
            "target_weight",
            "limit_price",
            "quantity",
            "estimated_value",
        ),
    )

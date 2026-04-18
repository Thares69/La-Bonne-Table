"""Preparation du contexte IA a partir des KPI et recommandations existants.

Fonction pure : lit la base SQLite via les KPI deja calcules, agrege dans une
structure serialisable JSON. Aucune donnee brute (tickets individuels, lignes
de stock) n'est exposee — uniquement des agregats.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Any

from la_bonne_table import kpi, rules
from la_bonne_table.db import get_metadata


def _safe_top(conn: sqlite3.Connection, start: str, end: str, n: int = 5) -> list[dict]:
    df = kpi.top_items_by_revenue(conn, n=n, start=start, end=end)
    return [
        {
            "name": str(r["name"]),
            "category": str(r["category"]),
            "revenue": round(float(r["revenue"]), 2),
        }
        for _, r in df.iterrows()
    ]


def _safe_flop(conn: sqlite3.Connection, start: str, end: str, n: int = 5) -> list[dict]:
    df = kpi.flop_items_by_revenue(conn, n=n, start=start, end=end)
    return [
        {
            "name": str(r["name"]),
            "category": str(r["category"]),
            "revenue": round(float(r["revenue"]), 2),
        }
        for _, r in df.iterrows()
    ]


def build_context(
    conn: sqlite3.Connection, start: str, end: str,
) -> dict[str, Any]:
    """Construit le contexte structure passe au copilote IA.

    Toutes les valeurs sont des types natifs serialisables (pas de DataFrame).
    """
    rev = kpi.revenue_total(conn, start, end)
    n_tickets = kpi.ticket_count(conn, start, end)
    avg = kpi.average_ticket(conn, start, end)
    gm = kpi.global_gross_margin(conn, start, end)
    waste = kpi.waste_rate_global(conn, start, end)
    days = kpi.open_closed_days(conn, start, end)

    pc = kpi.period_comparison(conn, end=end, window_days=30)
    comparison: dict[str, Any] | None = None
    if pc is not None:
        comparison = {
            "window_days": 30,
            "current_revenue": round(float(pc.current_revenue), 2),
            "previous_revenue": round(float(pc.previous_revenue), 2),
            "delta_pct": (
                round(float(pc.delta_pct), 4) if pc.previous_revenue > 0 else None
            ),
        }

    recos = rules.run_all_rules(conn, end=end)
    recos_serialized = [
        {
            **asdict(r),
            "priority_label": rules.PRIORITY_LABELS.get(r.priority, str(r.priority)),
        }
        for r in recos
    ]

    return {
        "period": {
            "start": start,
            "end": end,
            "days_open": int(days["open"]),
            "days_closed": int(days["closed"]),
            "days_total": int(days["total"]),
        },
        "revenue": {
            "total": round(float(rev), 2),
            "tickets": int(n_tickets),
            "average_ticket": round(float(avg), 2),
            "comparison_30d": comparison,
        },
        "health": {
            "gross_margin_rate": round(float(gm["margin_rate"]), 4),
            "waste_rate": round(float(waste["waste_rate"]), 4),
            "waste_units": int(waste["waste"]),
            "available_units": int(waste["available"]),
        },
        "top_items": _safe_top(conn, start, end),
        "flop_items": _safe_flop(conn, start, end),
        "recommendations": recos_serialized,
        "dataset_type": get_metadata(conn, "dataset_type") or "unknown",
    }

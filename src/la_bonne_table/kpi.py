"""KPI calculations — pure read functions over SQLite.

Toutes les fonctions acceptent une connexion `sqlite3.Connection` et des bornes
optionnelles `start` / `end` au format ISO ``YYYY-MM-DD`` (inclusives).

Retours : scalaires natifs (float, int, dict) pour les KPI simples,
pandas DataFrame pour les KPI tabulaires.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


def _where_date(
    start: str | None, end: str | None, col: str = "date"
) -> tuple[str, list[str]]:
    """Construit la clause WHERE paramétrée pour filtrer sur une colonne date."""
    conds: list[str] = []
    params: list[str] = []
    if start:
        conds.append(f"{col} >= ?")
        params.append(start)
    if end:
        conds.append(f"{col} <= ?")
        params.append(end)
    clause = (" WHERE " + " AND ".join(conds)) if conds else ""
    return clause, params


# ---------------------------------------------------------------------------
# KPI scalaires
# ---------------------------------------------------------------------------


def revenue_total(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> float:
    where, params = _where_date(start, end)
    row = conn.execute(
        f"SELECT COALESCE(SUM(total), 0.0) AS r FROM sales{where}", params
    ).fetchone()
    return float(row["r"])


def ticket_count(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> int:
    where, params = _where_date(start, end)
    row = conn.execute(
        f"SELECT COUNT(DISTINCT ticket_id) AS n FROM sales{where}", params
    ).fetchone()
    return int(row["n"])


def average_ticket(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> float:
    rev = revenue_total(conn, start, end)
    n = ticket_count(conn, start, end)
    return rev / n if n else 0.0


def open_closed_days(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> dict[str, int]:
    where, params = _where_date(start, end)
    row = conn.execute(
        f"""SELECT
               COALESCE(SUM(CASE WHEN is_open = 1 THEN 1 ELSE 0 END), 0) AS open_days,
               COALESCE(SUM(CASE WHEN is_open = 0 THEN 1 ELSE 0 END), 0) AS closed_days,
               COUNT(*) AS total_days
            FROM calendar{where}""",
        params,
    ).fetchone()
    return {
        "open": int(row["open_days"]),
        "closed": int(row["closed_days"]),
        "total": int(row["total_days"]),
    }


# ---------------------------------------------------------------------------
# KPI tabulaires
# ---------------------------------------------------------------------------


def revenue_by_day(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    where, params = _where_date(start, end)
    return pd.read_sql(
        f"""SELECT date, SUM(total) AS revenue, COUNT(DISTINCT ticket_id) AS tickets
            FROM sales{where}
            GROUP BY date
            ORDER BY date""",
        conn,
        params=params,
    )


def _items_aggregate(
    conn: sqlite3.Connection,
    order_by: str,
    ascending: bool,
    n: int,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    where, params = _where_date(start, end, "s.date")
    direction = "ASC" if ascending else "DESC"
    return pd.read_sql(
        f"""SELECT s.item_id, i.name, i.category,
                   SUM(s.quantity) AS qty,
                   SUM(s.total)    AS revenue
            FROM sales s
            JOIN items i ON i.item_id = s.item_id
            {where}
            GROUP BY s.item_id, i.name, i.category
            ORDER BY {order_by} {direction}
            LIMIT ?""",
        conn,
        params=[*params, n],
    )


def top_items_by_revenue(
    conn: sqlite3.Connection,
    n: int = 5,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    return _items_aggregate(conn, "revenue", ascending=False, n=n, start=start, end=end)


def flop_items_by_revenue(
    conn: sqlite3.Connection,
    n: int = 5,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    return _items_aggregate(conn, "revenue", ascending=True, n=n, start=start, end=end)


def top_items_by_volume(
    conn: sqlite3.Connection,
    n: int = 5,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    return _items_aggregate(conn, "qty", ascending=False, n=n, start=start, end=end)


def gross_margin_by_item(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    where, params = _where_date(start, end, "s.date")
    df = pd.read_sql(
        f"""SELECT s.item_id, i.name, i.category, i.unit_cost, i.sell_price,
                   SUM(s.quantity)               AS qty,
                   SUM(s.total)                  AS revenue,
                   SUM(s.quantity * i.unit_cost) AS total_cost
            FROM sales s
            JOIN items i ON i.item_id = s.item_id
            {where}
            GROUP BY s.item_id, i.name, i.category, i.unit_cost, i.sell_price
            ORDER BY i.category, s.item_id""",
        conn,
        params=params,
    )
    df["gross_margin"] = df["revenue"] - df["total_cost"]
    df["margin_rate"] = (df["gross_margin"] / df["revenue"]).where(df["revenue"] > 0, 0.0)
    return df


def global_gross_margin(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> dict[str, float]:
    df = gross_margin_by_item(conn, start, end)
    revenue = float(df["revenue"].sum())
    cost = float(df["total_cost"].sum())
    margin = revenue - cost
    rate = margin / revenue if revenue > 0 else 0.0
    return {
        "revenue": revenue,
        "cost": cost,
        "gross_margin": margin,
        "margin_rate": rate,
    }


def waste_rate_by_item(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    where, params = _where_date(start, end, "st.date")
    df = pd.read_sql(
        f"""SELECT st.item_id, i.name, i.category,
                   SUM(st.waste)                      AS waste,
                   SUM(st.qty_open + st.qty_received) AS available
            FROM stock st
            JOIN items i ON i.item_id = st.item_id
            {where}
            GROUP BY st.item_id, i.name, i.category
            ORDER BY i.category, st.item_id""",
        conn,
        params=params,
    )
    df["waste_rate"] = (df["waste"] / df["available"]).where(df["available"] > 0, 0.0)
    return df


def waste_rate_global(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> dict[str, float]:
    where, params = _where_date(start, end)
    row = conn.execute(
        f"""SELECT COALESCE(SUM(waste), 0)                     AS waste,
                   COALESCE(SUM(qty_open + qty_received), 0)   AS available
            FROM stock{where}""",
        params,
    ).fetchone()
    waste, avail = int(row["waste"]), int(row["available"])
    return {
        "waste": waste,
        "available": avail,
        "waste_rate": (waste / avail) if avail > 0 else 0.0,
    }


def stockout_days_by_item(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    """Nombre de jours avec ``qty_close = 0`` par item sur la période."""
    where, params = _where_date(start, end, "st.date")
    return pd.read_sql(
        f"""SELECT st.item_id, i.name, i.category,
                   SUM(CASE WHEN st.qty_close = 0 THEN 1 ELSE 0 END) AS zero_days,
                   COUNT(*) AS total_days
            FROM stock st
            JOIN items i ON i.item_id = st.item_id
            {where}
            GROUP BY st.item_id, i.name, i.category
            ORDER BY zero_days DESC, i.name""",
        conn,
        params=params,
    )


def stock_rotation(
    conn: sqlite3.Connection, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    """Rotation simple : quantité vendue / stock moyen de clôture sur la période."""
    w_sales, p_sales = _where_date(start, end, "s.date")
    w_stock, p_stock = _where_date(start, end, "st.date")
    df = pd.read_sql(
        f"""WITH sold AS (
                SELECT s.item_id, SUM(s.quantity) AS qty_sold
                FROM sales s{w_sales}
                GROUP BY s.item_id
            ),
            avg_stk AS (
                SELECT st.item_id, AVG(st.qty_close) AS avg_close
                FROM stock st{w_stock}
                GROUP BY st.item_id
            )
            SELECT i.item_id, i.name, i.category,
                   COALESCE(sold.qty_sold, 0)      AS qty_sold,
                   COALESCE(avg_stk.avg_close, 0)  AS avg_close
            FROM items i
            LEFT JOIN sold    ON sold.item_id    = i.item_id
            LEFT JOIN avg_stk ON avg_stk.item_id = i.item_id
            ORDER BY i.category, i.item_id""",
        conn,
        params=[*p_sales, *p_stock],
    )
    df["rotation"] = (df["qty_sold"] / df["avg_close"]).where(df["avg_close"] > 0, 0.0)
    return df


# ---------------------------------------------------------------------------
# Comparaison période
# ---------------------------------------------------------------------------


@dataclass
class PeriodComparison:
    current_start: str
    current_end: str
    current_revenue: float
    previous_start: str
    previous_end: str
    previous_revenue: float
    delta_pct: float  # 0.0 si la période précédente a un CA nul


def period_comparison(
    conn: sqlite3.Connection, end: str | None = None, window_days: int = 30
) -> PeriodComparison | None:
    """CA sur les `window_days` derniers jours vs la période précédente de même taille.

    Si `end` est omis, on prend la date max présente dans `sales`.
    Retourne None s'il n'y a aucune donnée.
    """
    if end is None:
        row = conn.execute("SELECT MAX(date) AS d FROM sales").fetchone()
        if row["d"] is None:
            return None
        end = row["d"]

    end_d = date.fromisoformat(end)
    current_start = (end_d - timedelta(days=window_days - 1)).isoformat()
    previous_end = (end_d - timedelta(days=window_days)).isoformat()
    previous_start = (end_d - timedelta(days=2 * window_days - 1)).isoformat()

    curr = revenue_total(conn, current_start, end)
    prev = revenue_total(conn, previous_start, previous_end)
    delta = (curr - prev) / prev if prev > 0 else 0.0

    return PeriodComparison(
        current_start=current_start,
        current_end=end,
        current_revenue=curr,
        previous_start=previous_start,
        previous_end=previous_end,
        previous_revenue=prev,
        delta_pct=delta,
    )

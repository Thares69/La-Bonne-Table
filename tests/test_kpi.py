"""Tests KPI sur un dataset minimal aux valeurs connues.

Dataset :
    items  : A (cost=4, price=10, marge=60%), B (cost=7, price=10, marge=30%)
    calendar : 2026-01-01 ouvert, 2026-01-02 fermé, 2026-01-03 ouvert
    sales  :
        T1 (2026-01-01) : A x2 (20€) + B x1 (10€)  = 30 €
        T2 (2026-01-01) : A x1 (10€)                = 10 €
        T3 (2026-01-03) : B x3 (30€)                = 30 €
    stock  :
        2026-01-01 A : open=10, recv=5, close=11, waste=1
        2026-01-01 B : open=8,  recv=0, close=7,  waste=0
        2026-01-03 A : open=11, recv=0, close=11, waste=0
        2026-01-03 B : open=7,  recv=5, close=9,  waste=0

Attendus :
    revenue_total       = 70
    tickets             = 3
    average_ticket      = 70/3
    revenue_by_day      = [(01, 40), (03, 30)]
    top by revenue      = [B (40), A (30)]
    top by volume       = A qty=3 ... wait B=4. [B, A]
    margin A : rev=30, cost=4*3=12, margin=18, rate=60%
    margin B : rev=40, cost=7*4=28, margin=12, rate=30%
    global margin rate  = 30 / 70 ≈ 42.857%
    waste A : 1 / (10+5+11+0) = 1/26
    waste B : 0
    rotation A : qty=3, avg_close=(11+11)/2=11 -> 3/11
    rotation B : qty=4, avg_close=(7+9)/2=8   -> 4/8 = 0.5
    open/closed : 2 / 1
"""
from __future__ import annotations

import sqlite3

import pytest

from la_bonne_table import kpi


@pytest.fixture
def populated_db(tmp_db: sqlite3.Connection) -> sqlite3.Connection:
    tmp_db.executemany(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) VALUES (?,?,?,?,?)",
        [
            ("A", "Item A", "plat", 4.0, 10.0),
            ("B", "Item B", "plat", 7.0, 10.0),
        ],
    )
    tmp_db.executemany(
        "INSERT INTO calendar (date, is_open, notes) VALUES (?,?,?)",
        [
            ("2026-01-01", 1, ""),
            ("2026-01-02", 0, "fermé"),
            ("2026-01-03", 1, ""),
        ],
    )
    tmp_db.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("2026-01-01", "T1", "A", 2, 10.0, 20.0),
            ("2026-01-01", "T1", "B", 1, 10.0, 10.0),
            ("2026-01-01", "T2", "A", 1, 10.0, 10.0),
            ("2026-01-03", "T3", "B", 3, 10.0, 30.0),
        ],
    )
    tmp_db.executemany(
        "INSERT INTO stock (date, item_id, qty_open, qty_received, qty_close, waste) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("2026-01-01", "A", 10, 5, 11, 1),
            ("2026-01-01", "B", 8, 0, 7, 0),
            ("2026-01-03", "A", 11, 0, 11, 0),
            ("2026-01-03", "B", 7, 5, 9, 0),
        ],
    )
    tmp_db.commit()
    return tmp_db


def test_revenue_total(populated_db):
    assert kpi.revenue_total(populated_db) == 70.0


def test_revenue_total_with_range(populated_db):
    assert kpi.revenue_total(populated_db, "2026-01-01", "2026-01-01") == 40.0
    assert kpi.revenue_total(populated_db, "2026-01-02", "2026-01-03") == 30.0


def test_ticket_count(populated_db):
    assert kpi.ticket_count(populated_db) == 3


def test_average_ticket(populated_db):
    assert kpi.average_ticket(populated_db) == pytest.approx(70.0 / 3)


def test_average_ticket_empty():
    import sqlite3 as sq

    from la_bonne_table.db import init_schema

    conn = sq.connect(":memory:")
    conn.row_factory = sq.Row
    init_schema(conn)
    assert kpi.average_ticket(conn) == 0.0


def test_revenue_by_day(populated_db):
    df = kpi.revenue_by_day(populated_db)
    assert list(df["date"]) == ["2026-01-01", "2026-01-03"]
    assert list(df["revenue"]) == [40.0, 30.0]
    assert list(df["tickets"]) == [2, 1]


def test_top_items_by_revenue(populated_db):
    df = kpi.top_items_by_revenue(populated_db, n=5)
    assert list(df["item_id"]) == ["B", "A"]
    assert list(df["revenue"]) == [40.0, 30.0]


def test_flop_items_by_revenue(populated_db):
    df = kpi.flop_items_by_revenue(populated_db, n=5)
    assert list(df["item_id"]) == ["A", "B"]


def test_top_items_by_volume(populated_db):
    df = kpi.top_items_by_volume(populated_db, n=5)
    assert list(df["item_id"]) == ["B", "A"]
    assert list(df["qty"]) == [4, 3]


def test_gross_margin_by_item(populated_db):
    df = kpi.gross_margin_by_item(populated_db).set_index("item_id")
    assert df.loc["A", "gross_margin"] == pytest.approx(18.0)
    assert df.loc["A", "margin_rate"] == pytest.approx(0.60)
    assert df.loc["B", "gross_margin"] == pytest.approx(12.0)
    assert df.loc["B", "margin_rate"] == pytest.approx(0.30)


def test_global_gross_margin(populated_db):
    g = kpi.global_gross_margin(populated_db)
    assert g["revenue"] == 70.0
    assert g["cost"] == pytest.approx(40.0)  # 12 + 28
    assert g["gross_margin"] == pytest.approx(30.0)
    assert g["margin_rate"] == pytest.approx(30.0 / 70.0)


def test_waste_rate_by_item(populated_db):
    df = kpi.waste_rate_by_item(populated_db).set_index("item_id")
    assert df.loc["A", "waste"] == 1
    assert df.loc["A", "available"] == 26  # (10+5)+(11+0)
    assert df.loc["A", "waste_rate"] == pytest.approx(1 / 26)
    assert df.loc["B", "waste_rate"] == 0.0


def test_waste_rate_global(populated_db):
    g = kpi.waste_rate_global(populated_db)
    assert g["waste"] == 1
    assert g["available"] == 46  # 26 (A) + 20 (B)
    assert g["waste_rate"] == pytest.approx(1 / 46)


def test_stockout_days_by_item(populated_db):
    # dataset : aucun qty_close = 0 -> zero_days partout = 0
    df = kpi.stockout_days_by_item(populated_db).set_index("item_id")
    assert df.loc["A", "zero_days"] == 0
    assert df.loc["A", "total_days"] == 2


def test_stockout_days_by_item_counts_zeros(tmp_db):
    tmp_db.execute(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES ('X', 'X', 'plat', 1.0, 5.0)"
    )
    rows = [
        ("2026-01-01", "X", 5, 0, 0, 0),
        ("2026-01-02", "X", 5, 5, 5, 0),
        ("2026-01-03", "X", 5, 0, 0, 0),
    ]
    tmp_db.executemany(
        "INSERT INTO stock (date, item_id, qty_open, qty_received, qty_close, waste) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    tmp_db.commit()
    df = kpi.stockout_days_by_item(tmp_db).set_index("item_id")
    assert df.loc["X", "zero_days"] == 2
    assert df.loc["X", "total_days"] == 3


def test_stock_rotation(populated_db):
    df = kpi.stock_rotation(populated_db).set_index("item_id")
    assert df.loc["A", "qty_sold"] == 3
    assert df.loc["A", "avg_close"] == pytest.approx(11.0)
    assert df.loc["A", "rotation"] == pytest.approx(3 / 11)
    assert df.loc["B", "rotation"] == pytest.approx(4 / 8)


def test_open_closed_days(populated_db):
    d = kpi.open_closed_days(populated_db)
    assert d == {"open": 2, "closed": 1, "total": 3}


def test_period_comparison_simple(populated_db):
    # window_days=1, end=2026-01-03 -> current=[03,03]=30, previous=[02,02]=0
    p = kpi.period_comparison(populated_db, end="2026-01-03", window_days=1)
    assert p is not None
    assert p.current_revenue == 30.0
    assert p.previous_revenue == 0.0
    assert p.delta_pct == 0.0  # fallback lorsque previous = 0


def test_period_comparison_with_delta(populated_db):
    # window_days=1, end=2026-01-01 -> current=[01,01]=40, previous=[12-31]=0
    # Use window 2 : current=[02,03]=30, previous=[12-31,01-01]=40
    p = kpi.period_comparison(populated_db, end="2026-01-03", window_days=2)
    assert p.current_revenue == 30.0
    assert p.previous_revenue == 40.0
    assert p.delta_pct == pytest.approx((30.0 - 40.0) / 40.0)

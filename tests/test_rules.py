"""Tests du moteur de règles.

Chaque règle est testée avec une fixture minimale qui plante explicitement
un signal (ou son absence) et vérifie le message, la priorité, la métrique.
"""
from __future__ import annotations

import sqlite3

import pytest

from la_bonne_table import rules

# ---------------------------------------------------------------------------
# rule_excessive_waste
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_high_waste(tmp_db: sqlite3.Connection) -> sqlite3.Connection:
    tmp_db.executemany(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) VALUES (?,?,?,?,?)",
        [
            ("A", "Item A", "plat", 5.0, 15.0),
            ("B", "Item B", "plat", 5.0, 15.0),
        ],
    )
    tmp_db.executemany(
        "INSERT INTO stock (date, item_id, qty_open, qty_received, qty_close, waste) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("2026-01-01", "A", 10, 10, 2, 8),  # waste 40%
            ("2026-01-01", "B", 10, 10, 18, 2),  # waste 10%
        ],
    )
    tmp_db.commit()
    return tmp_db


def test_excessive_waste_triggers(db_with_high_waste):
    recos = rules.rule_excessive_waste(db_with_high_waste)
    assert len(recos) == 1
    r = recos[0]
    assert r.type == "excessive_waste"
    assert r.priority == 1
    assert r.item_id == "A"
    assert r.metric_value == pytest.approx(8 / 20)
    assert "Item A" in r.message


def test_excessive_waste_respects_threshold(db_with_high_waste):
    assert rules.rule_excessive_waste(db_with_high_waste, threshold=0.50) == []


# ---------------------------------------------------------------------------
# rule_frequent_stockout
# ---------------------------------------------------------------------------


def test_frequent_stockout(tmp_db):
    tmp_db.execute(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES ('X', 'Plat X', 'plat', 4.0, 12.0)"
    )
    # 7 jours avec qty_close=0 -> déclenche (seuil par défaut = 5)
    rows = []
    for i in range(7):
        d = f"2026-01-{i + 1:02d}"
        rows.append((d, "X", 5, 0, 0, 0))
    # 3 jours normaux
    for i in range(7, 10):
        d = f"2026-01-{i + 1:02d}"
        rows.append((d, "X", 5, 5, 5, 0))
    tmp_db.executemany(
        "INSERT INTO stock (date, item_id, qty_open, qty_received, qty_close, waste) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    tmp_db.commit()

    recos = rules.rule_frequent_stockout(tmp_db)
    assert len(recos) == 1
    assert recos[0].priority == 1
    assert recos[0].metric_value == 7
    assert recos[0].item_id == "X"


def test_frequent_stockout_below_threshold(tmp_db):
    tmp_db.execute(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES ('X', 'Plat X', 'plat', 4.0, 12.0)"
    )
    rows = [(f"2026-01-0{i + 1}", "X", 5, 0, 0, 0) for i in range(3)]
    tmp_db.executemany(
        "INSERT INTO stock (date, item_id, qty_open, qty_received, qty_close, waste) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    tmp_db.commit()
    assert rules.rule_frequent_stockout(tmp_db) == []


# ---------------------------------------------------------------------------
# rule_low_margin
# ---------------------------------------------------------------------------


def test_low_margin(tmp_db):
    tmp_db.executemany(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) VALUES (?,?,?,?,?)",
        [
            ("LM", "Pizza", "plat", 9.5, 13.0),   # marge 27%
            ("OK", "Burger", "plat", 3.0, 12.0),  # marge 75%
        ],
    )
    # 60 ventes chacun
    rows_lm = [
        ("2026-01-01", f"T{i}", "LM", 1, 13.0, 13.0) for i in range(60)
    ]
    rows_ok = [
        ("2026-01-01", f"U{i}", "OK", 1, 12.0, 12.0) for i in range(60)
    ]
    tmp_db.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?,?,?,?,?,?)",
        rows_lm + rows_ok,
    )
    tmp_db.commit()

    recos = rules.rule_low_margin(tmp_db)
    assert len(recos) == 1
    assert recos[0].item_id == "LM"
    assert recos[0].priority == 2
    assert recos[0].metric_value == pytest.approx((13 - 9.5) / 13)


def test_low_margin_ignores_low_volume(tmp_db):
    tmp_db.execute(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES ('LM', 'Pizza', 'plat', 9.5, 13.0)"
    )
    # Seulement 10 ventes -> sous le seuil de 50
    tmp_db.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?,?,?,?,?,?)",
        [("2026-01-01", f"T{i}", "LM", 1, 13.0, 13.0) for i in range(10)],
    )
    tmp_db.commit()
    assert rules.rule_low_margin(tmp_db) == []


# ---------------------------------------------------------------------------
# rule_declining_item
# ---------------------------------------------------------------------------


def test_declining_item(tmp_db):
    tmp_db.execute(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES ('D', 'Tajine', 'plat', 5.0, 18.0)"
    )
    tmp_db.execute(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES ('S', 'Salade', 'entree', 2.0, 9.0)"
    )

    # Période précédente (2026-01-01 -> 2026-01-07) : 10 ventes de D par jour
    prev = []
    for d in range(1, 8):
        date_s = f"2026-01-{d:02d}"
        for t in range(10):
            prev.append((date_s, f"P{d}-{t}", "D", 1, 18.0, 18.0))

    # Période courante (2026-01-08 -> 2026-01-14) : 2 ventes/jour -> baisse ~80%
    curr = []
    for d in range(8, 15):
        date_s = f"2026-01-{d:02d}"
        for t in range(2):
            curr.append((date_s, f"C{d}-{t}", "D", 1, 18.0, 18.0))

    # Salade constante (sert à ancrer le top 10)
    salad = []
    for d in range(1, 15):
        date_s = f"2026-01-{d:02d}"
        salad.append((date_s, f"S{d}", "S", 1, 9.0, 9.0))

    tmp_db.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?,?,?,?,?,?)",
        prev + curr + salad,
    )
    tmp_db.commit()

    recos = rules.rule_declining_item(tmp_db, end="2026-01-14")
    assert any(r.item_id == "D" for r in recos)
    d_reco = next(r for r in recos if r.item_id == "D")
    assert d_reco.priority == 2
    assert d_reco.metric_value == pytest.approx((14 - 70) / 70)


def test_declining_item_skips_when_no_baseline(tmp_db):
    tmp_db.execute(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES ('N', 'Nouveau', 'plat', 5.0, 18.0)"
    )
    # Ventes uniquement sur la période courante
    rows = [
        (f"2026-01-{d:02d}", f"T{d}", "N", 1, 18.0, 18.0)
        for d in range(8, 15)
    ]
    tmp_db.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    tmp_db.commit()
    assert rules.rule_declining_item(tmp_db, end="2026-01-14") == []


# ---------------------------------------------------------------------------
# rule_slow_weekday
# ---------------------------------------------------------------------------


def test_slow_weekday(tmp_db):
    tmp_db.execute(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES ('X', 'X', 'plat', 2.0, 10.0)"
    )
    # 2 semaines : mardi (weekday=1) très bas, autres normaux.
    # 2026-01-05 = lundi (weekday 0), donc mardi = 06 et 13.
    rows = []
    for ticket, d in enumerate(range(5, 19), start=1):
        date_s = f"2026-01-{d:02d}"
        weekday = (d - 5) % 7
        ticket_revenue = 20.0 if weekday == 1 else 100.0
        rows.append((date_s, f"T{ticket}", "X", 1, ticket_revenue, ticket_revenue))
    tmp_db.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    tmp_db.commit()

    recos = rules.rule_slow_weekday(tmp_db)
    assert len(recos) == 1
    r = recos[0]
    assert r.type == "slow_weekday"
    assert r.priority == 4
    assert "Mardi" in r.message


# ---------------------------------------------------------------------------
# Orchestration + persistance
# ---------------------------------------------------------------------------


def test_run_all_rules_sorts_by_priority(db_with_high_waste):
    # Ajoute un signal jour creux pour avoir 2 règles différentes
    db_with_high_waste.execute(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES ('2026-01-06', 'T1', 'A', 1, 100.0, 100.0)"
    )
    db_with_high_waste.execute(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES ('2026-01-07', 'T2', 'A', 1, 20.0, 20.0)"
    )
    db_with_high_waste.commit()
    recos = rules.run_all_rules(db_with_high_waste)
    priorities = [r.priority for r in recos]
    assert priorities == sorted(priorities)


def test_save_recommendations(tmp_db):
    recos = [
        rules.Recommendation("waste", 1, "msg1", 0.20, "A"),
        rules.Recommendation("low_margin", 2, "msg2", 0.25, "B"),
    ]
    n = rules.save_recommendations(tmp_db, recos)
    assert n == 2
    rows = tmp_db.execute(
        "SELECT type, priority, message FROM recommendations ORDER BY priority"
    ).fetchall()
    assert rows[0]["type"] == "waste"
    assert rows[1]["type"] == "low_margin"


def test_save_recommendations_is_idempotent(tmp_db):
    r = rules.Recommendation("waste", 1, "msg", 0.5, "A")
    rules.save_recommendations(tmp_db, [r])
    rules.save_recommendations(tmp_db, [r])
    count = tmp_db.execute("SELECT COUNT(*) AS c FROM recommendations").fetchone()["c"]
    assert count == 1


def test_recommendation_dataclass():
    r = rules.Recommendation("waste", 1, "test", 0.18, "A")
    assert r.item_id == "A"
    assert rules.PRIORITY_LABELS[r.priority] == "critique"

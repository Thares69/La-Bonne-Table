"""Tests for HTML report generation."""
from __future__ import annotations

import sqlite3

import pytest

from la_bonne_table import kpi
from la_bonne_table.report import generate_html_report


@pytest.fixture
def report_db(tmp_db: sqlite3.Connection) -> sqlite3.Connection:
    """Minimal dataset sufficient for report generation."""
    tmp_db.executemany(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES (?,?,?,?,?)",
        [
            ("A", "Item A", "plat", 4.0, 10.0),
            ("B", "Item B", "dessert", 7.0, 10.0),
        ],
    )
    tmp_db.executemany(
        "INSERT INTO calendar (date, is_open, notes) VALUES (?,?,?)",
        [("2026-01-01", 1, ""), ("2026-01-02", 0, ""), ("2026-01-03", 1, "")],
    )
    tmp_db.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("2026-01-01", "T1", "A", 2, 10.0, 20.0),
            ("2026-01-01", "T1", "B", 1, 10.0, 10.0),
            ("2026-01-03", "T2", "B", 3, 10.0, 30.0),
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


def test_report_returns_valid_html(report_db):
    html = generate_html_report(report_db, "2026-01-01", "2026-01-03")
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_report_contains_period(report_db):
    html = generate_html_report(report_db, "2026-01-01", "2026-01-03")
    assert "2026-01-01" in html
    assert "2026-01-03" in html


def test_report_contains_kpi_values(report_db):
    html = generate_html_report(report_db, "2026-01-01", "2026-01-03")
    rev = kpi.revenue_total(report_db, "2026-01-01", "2026-01-03")
    # Revenue should appear formatted in the report
    assert f"{rev:,.0f}" in html


def test_report_contains_product_names(report_db):
    html = generate_html_report(report_db, "2026-01-01", "2026-01-03")
    assert "Item A" in html
    assert "Item B" in html


def test_report_contains_recommendations_section(report_db):
    html = generate_html_report(report_db, "2026-01-01", "2026-01-03")
    assert "Recommandations" in html


def test_report_empty_db(tmp_db):
    """Report on empty DB should not crash."""
    html = generate_html_report(tmp_db, "2026-01-01", "2026-01-03")
    assert "<!DOCTYPE html>" in html
    assert "Aucune alerte" in html

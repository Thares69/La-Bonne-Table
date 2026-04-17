from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from la_bonne_table import ingest

ITEMS_CSV = """item_id,name,category,unit_cost,sell_price
P001,Burger,plat,3.0,12.0
P002,Salade,entree,2.0,8.0
D001,Tarte,dessert,1.5,6.5
"""

CALENDAR_CSV = """date,is_open,notes
2026-03-01,1,
2026-03-02,0,fermé
2026-03-03,1,
"""

SALES_CSV = """date,ticket_id,item_id,quantity,unit_price,total
2026-03-01,T001,P001,1,12.0,12.0
2026-03-01,T001,P002,1,8.0,8.0
2026-03-01,T002,P001,2,12.0,24.0
2026-03-03,T003,D001,1,6.5,6.5
"""

STOCK_CSV = """date,item_id,qty_open,qty_received,qty_close,waste
2026-03-01,P001,10,5,8,1
2026-03-01,P002,8,4,6,0
2026-03-01,D001,6,2,4,0
2026-03-03,P001,8,5,7,0
"""


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    d = tmp_path / "raw"
    d.mkdir()
    (d / "items.csv").write_text(ITEMS_CSV)
    (d / "calendar.csv").write_text(CALENDAR_CSV)
    (d / "sales.csv").write_text(SALES_CSV)
    (d / "stock.csv").write_text(STOCK_CSV)
    return d


def test_ingest_all_happy_path(raw_dir, tmp_path):
    db = tmp_path / "test.db"
    counts = ingest.ingest_all(raw_dir, db)
    assert counts == {"items": 3, "calendar": 3, "sales": 4, "stock": 4}


def test_ingest_all_is_idempotent(raw_dir, tmp_path):
    db = tmp_path / "test.db"
    c1 = ingest.ingest_all(raw_dir, db)
    c2 = ingest.ingest_all(raw_dir, db)
    assert c1 == c2


def test_sales_unknown_item_raises(raw_dir, tmp_path):
    (raw_dir / "sales.csv").write_text(
        "date,ticket_id,item_id,quantity,unit_price,total\n"
        "2026-03-01,T001,XXX,1,10.0,10.0\n"
    )
    with pytest.raises(ValueError, match="item_id inconnus"):
        ingest.ingest_all(raw_dir, tmp_path / "test.db")


def test_sales_filters_non_positive_quantity(raw_dir, tmp_path):
    (raw_dir / "sales.csv").write_text(
        "date,ticket_id,item_id,quantity,unit_price,total\n"
        "2026-03-01,T001,P001,1,12.0,12.0\n"
        "2026-03-01,T001,P001,0,12.0,0.0\n"
        "2026-03-01,T001,P001,-1,12.0,-12.0\n"
    )
    counts = ingest.ingest_all(raw_dir, tmp_path / "test.db")
    assert counts["sales"] == 1


def test_sales_deduplicates_same_ticket_same_item(raw_dir, tmp_path):
    (raw_dir / "sales.csv").write_text(
        "date,ticket_id,item_id,quantity,unit_price,total\n"
        "2026-03-01,T001,P001,1,12.0,12.0\n"
        "2026-03-01,T001,P001,2,12.0,24.0\n"
    )
    from la_bonne_table.db import connect, init_schema

    counts = ingest.ingest_all(raw_dir, tmp_path / "test.db")
    assert counts["sales"] == 1

    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    row = conn.execute(
        "SELECT quantity, total FROM sales WHERE ticket_id='T001'"
    ).fetchone()
    assert row["quantity"] == 3
    assert row["total"] == 36.0
    conn.close()


def test_stock_deduplicates_date_item(raw_dir, tmp_path):
    (raw_dir / "stock.csv").write_text(
        "date,item_id,qty_open,qty_received,qty_close,waste\n"
        "2026-03-01,P001,10,5,8,1\n"
        "2026-03-01,P001,10,5,7,2\n"  # doublon -> keep last
    )
    counts = ingest.ingest_all(raw_dir, tmp_path / "test.db")
    assert counts["stock"] == 1


def test_stock_negative_raises(raw_dir, tmp_path):
    (raw_dir / "stock.csv").write_text(
        "date,item_id,qty_open,qty_received,qty_close,waste\n"
        "2026-03-01,P001,10,-5,8,1\n"
    )
    with pytest.raises(ValueError, match="qty_received négatif"):
        ingest.ingest_all(raw_dir, tmp_path / "test.db")


def test_invalid_date_raises(raw_dir, tmp_path):
    (raw_dir / "calendar.csv").write_text(
        "date,is_open,notes\n"
        "2026-03-01,1,\n"
        "not-a-date,1,\n"
    )
    with pytest.raises(ValueError, match="date\\(s\\) invalide"):
        ingest.ingest_all(raw_dir, tmp_path / "test.db")


def test_missing_column_raises(raw_dir, tmp_path):
    (raw_dir / "items.csv").write_text(
        "item_id,name,category,unit_cost\n"
        "P001,Burger,plat,3.0\n"
    )
    with pytest.raises(ValueError, match="colonnes manquantes"):
        ingest.ingest_all(raw_dir, tmp_path / "test.db")


def test_missing_file_raises(raw_dir, tmp_path):
    (raw_dir / "sales.csv").unlink()
    with pytest.raises(FileNotFoundError):
        ingest.ingest_all(raw_dir, tmp_path / "test.db")


# ---------------------------------------------------------------------------
# ingest_uploaded (file-like objects)
# ---------------------------------------------------------------------------

ITEMS_BIN = (
    b"item_id,name,category,unit_cost,sell_price\n"
    b"A,Item A,plat,4.0,10.0\n"
    b"B,Item B,boisson,2.0,6.0\n"
)
CALENDAR_BIN = b"date,is_open,notes\n2026-01-01,1,\n2026-01-02,0,ferme\n"
SALES_BIN = (
    b"date,ticket_id,item_id,quantity,unit_price,total\n"
    b"2026-01-01,T1,A,2,10.0,20.0\n"
    b"2026-01-01,T1,B,1,6.0,6.0\n"
)
STOCK_BIN = (
    b"date,item_id,qty_open,qty_received,qty_close,waste\n"
    b"2026-01-01,A,10,5,11,1\n"
    b"2026-01-01,B,8,0,7,0\n"
)


def test_ingest_uploaded_without_calendar(tmp_db):
    files = {
        "items": BytesIO(ITEMS_BIN),
        "sales": BytesIO(SALES_BIN),
        "stock": BytesIO(STOCK_BIN),
    }
    counts = ingest.ingest_uploaded(tmp_db, files)
    assert counts["items"] == 2
    assert counts["sales"] == 2
    assert counts["stock"] == 2
    assert "calendar" not in counts


def test_ingest_uploaded_with_calendar(tmp_db):
    files = {
        "items": BytesIO(ITEMS_BIN),
        "sales": BytesIO(SALES_BIN),
        "stock": BytesIO(STOCK_BIN),
        "calendar": BytesIO(CALENDAR_BIN),
    }
    counts = ingest.ingest_uploaded(tmp_db, files)
    assert counts["calendar"] == 2
    row = tmp_db.execute("SELECT COUNT(*) AS c FROM calendar").fetchone()
    assert row["c"] == 2


def test_ingest_uploaded_replaces_data(tmp_db):
    files = {
        "items": BytesIO(ITEMS_BIN),
        "sales": BytesIO(SALES_BIN),
        "stock": BytesIO(STOCK_BIN),
    }
    ingest.ingest_uploaded(tmp_db, files)
    # Re-import with same data — counts should be identical (idempotent)
    files2 = {
        "items": BytesIO(ITEMS_BIN),
        "sales": BytesIO(SALES_BIN),
        "stock": BytesIO(STOCK_BIN),
    }
    counts = ingest.ingest_uploaded(tmp_db, files2)
    assert counts["items"] == 2
    row = tmp_db.execute("SELECT COUNT(*) AS c FROM items").fetchone()
    assert row["c"] == 2


def test_ingest_uploaded_unknown_item_raises(tmp_db):
    bad_sales = b"date,ticket_id,item_id,quantity,unit_price,total\n2026-01-01,T1,ZZZ,1,5.0,5.0\n"
    files = {
        "items": BytesIO(ITEMS_BIN),
        "sales": BytesIO(bad_sales),
        "stock": BytesIO(STOCK_BIN),
    }
    with pytest.raises(ValueError, match="item_id inconnus"):
        ingest.ingest_uploaded(tmp_db, files)


def test_ingest_uploaded_missing_column_raises(tmp_db):
    bad_items = b"item_id,name,category\nA,Item A,plat\n"
    files = {
        "items": BytesIO(bad_items),
        "sales": BytesIO(SALES_BIN),
        "stock": BytesIO(STOCK_BIN),
    }
    with pytest.raises(ValueError, match="colonnes manquantes"):
        ingest.ingest_uploaded(tmp_db, files)


def test_ingest_uploaded_sets_metadata_user(tmp_db):
    from la_bonne_table.db import get_metadata

    files = {
        "items": BytesIO(ITEMS_BIN),
        "sales": BytesIO(SALES_BIN),
        "stock": BytesIO(STOCK_BIN),
    }
    ingest.ingest_uploaded(tmp_db, files)
    assert get_metadata(tmp_db, "dataset_type") == "user"


def test_metadata_helpers(tmp_db):
    from la_bonne_table.db import get_metadata, set_metadata

    assert get_metadata(tmp_db, "foo") is None
    set_metadata(tmp_db, "foo", "bar")
    assert get_metadata(tmp_db, "foo") == "bar"
    set_metadata(tmp_db, "foo", "baz")
    assert get_metadata(tmp_db, "foo") == "baz"

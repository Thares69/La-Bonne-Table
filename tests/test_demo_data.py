from __future__ import annotations

from pathlib import Path

from la_bonne_table import demo_data, ingest
from la_bonne_table.demo_data import ITEMS, generate_demo_csvs


def test_generate_demo_csvs_writes_four_files(tmp_path: Path) -> None:
    counts = generate_demo_csvs(tmp_path)

    assert (tmp_path / "items.csv").exists()
    assert (tmp_path / "calendar.csv").exists()
    assert (tmp_path / "sales.csv").exists()
    assert (tmp_path / "stock.csv").exists()

    assert counts["items"] == len(ITEMS)
    assert counts["calendar"] == demo_data.DAYS
    assert counts["sales"] > 0
    assert counts["stock"] > 0


def test_generate_demo_csvs_is_ingestible(tmp_path: Path) -> None:
    """Le dataset produit doit passer la validation d'ingestion sans erreur."""
    raw = tmp_path / "raw"
    raw.mkdir()
    generate_demo_csvs(raw)

    counts = ingest.ingest_all(raw, tmp_path / "demo.db")
    assert counts["items"] == len(ITEMS)
    assert counts["sales"] > 0

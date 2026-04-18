"""CLI wrapper : genere les CSV de demo dans ``data/raw/``.

La logique de generation vit dans ``la_bonne_table.demo_data``.
"""
from __future__ import annotations

from pathlib import Path

from la_bonne_table.demo_data import DAYS, END_DATE, START_DATE, generate_demo_csvs

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


def main() -> None:
    counts = generate_demo_csvs(RAW_DIR)
    open_days = counts["calendar"] - 13  # lundis + feries
    print(f"Periode : {START_DATE} -> {END_DATE} ({DAYS} jours)")
    print(f"Jours ouverts : {open_days} / {DAYS}")
    print(f"Items : {counts['items']}")
    print(f"Lignes de vente : {counts['sales']}")
    print(f"Lignes de stock : {counts['stock']}")
    print(f"CSV ecrits dans : {RAW_DIR}")


if __name__ == "__main__":
    main()

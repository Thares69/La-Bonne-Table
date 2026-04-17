"""CSV -> SQLite ingestion.

Pipeline :
    items.csv -> items
    calendar.csv -> calendar
    sales.csv -> sales   (FK vers items)
    stock.csv -> stock   (FK vers items, unique (date, item_id))

Chaque `load_*` est idempotent : la table est purgée puis repeuplée.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from la_bonne_table.db import DB_PATH, connect, init_schema, set_metadata

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

CsvSource = Path | BinaryIO


def _read_csv(source: CsvSource, required: list[str], name: str = "") -> pd.DataFrame:
    if isinstance(source, Path):
        if not source.exists():
            raise FileNotFoundError(f"CSV manquant : {source}")
        name = name or source.name
    df = pd.read_csv(source)
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(f"{name} : colonnes manquantes {sorted(missing)}")
    if df.empty:
        raise ValueError(f"{name} : fichier vide")
    return df


def _validate_dates(df: pd.DataFrame, col: str, src: str) -> None:
    parsed = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
    bad = df[parsed.isna()]
    if not bad.empty:
        sample = bad[col].iloc[0]
        raise ValueError(f"{src} : {len(bad)} date(s) invalide(s), ex : {sample!r}")


def _known_items(conn: sqlite3.Connection) -> set[str]:
    return {r["item_id"] for r in conn.execute("SELECT item_id FROM items")}


def load_items(
    conn: sqlite3.Connection, source: CsvSource, name: str = "items.csv",
) -> int:
    df = _read_csv(source, ["item_id", "name", "category", "unit_cost", "sell_price"], name)
    if (df["unit_cost"] < 0).any() or (df["sell_price"] < 0).any():
        raise ValueError(f"{name} : unit_cost/sell_price négatif")
    df = df.drop_duplicates(subset=["item_id"], keep="last")

    conn.executemany(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) "
        "VALUES (?, ?, ?, ?, ?)",
        df[["item_id", "name", "category", "unit_cost", "sell_price"]].itertuples(
            index=False, name=None
        ),
    )
    conn.commit()
    return len(df)


def load_calendar(
    conn: sqlite3.Connection, source: CsvSource, name: str = "calendar.csv",
) -> int:
    df = _read_csv(source, ["date", "is_open", "notes"], name)
    _validate_dates(df, "date", name)
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.copy()
    df["notes"] = df["notes"].fillna("")
    df["is_open"] = df["is_open"].astype(int)

    conn.executemany(
        "INSERT INTO calendar (date, is_open, notes) VALUES (?, ?, ?)",
        df[["date", "is_open", "notes"]].itertuples(index=False, name=None),
    )
    conn.commit()
    return len(df)


def load_sales(
    conn: sqlite3.Connection, source: CsvSource, name: str = "sales.csv",
) -> int:
    df = _read_csv(
        source,
        ["date", "ticket_id", "item_id", "quantity", "unit_price", "total"],
        name,
    )
    _validate_dates(df, "date", name)

    # Filtrage des lignes aberrantes
    df = df[(df["quantity"] > 0) & (df["unit_price"] >= 0) & (df["total"] >= 0)]

    # Dédoublonnage : même (ticket, item) -> on somme les quantités et totaux
    df = df.groupby(
        ["date", "ticket_id", "item_id", "unit_price"], as_index=False
    ).agg(quantity=("quantity", "sum"), total=("total", "sum"))

    # Vérif FK
    unknown = set(df["item_id"]) - _known_items(conn)
    if unknown:
        raise ValueError(
            f"{name} : item_id inconnus dans items : {sorted(unknown)[:5]}"
        )

    conn.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        df[["date", "ticket_id", "item_id", "quantity", "unit_price", "total"]].itertuples(
            index=False, name=None
        ),
    )
    conn.commit()
    return len(df)


def load_stock(
    conn: sqlite3.Connection, source: CsvSource, name: str = "stock.csv",
) -> int:
    df = _read_csv(
        source,
        ["date", "item_id", "qty_open", "qty_received", "qty_close", "waste"],
        name,
    )
    _validate_dates(df, "date", name)

    for col in ["qty_open", "qty_received", "qty_close", "waste"]:
        if (df[col] < 0).any():
            raise ValueError(f"{name} : {col} négatif")

    df = df.drop_duplicates(subset=["date", "item_id"], keep="last")

    unknown = set(df["item_id"]) - _known_items(conn)
    if unknown:
        raise ValueError(
            f"{name} : item_id inconnus dans items : {sorted(unknown)[:5]}"
        )

    conn.executemany(
        "INSERT INTO stock (date, item_id, qty_open, qty_received, qty_close, waste) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        df[["date", "item_id", "qty_open", "qty_received", "qty_close", "waste"]].itertuples(
            index=False, name=None
        ),
    )
    conn.commit()
    return len(df)


def _purge_tables(conn: sqlite3.Connection) -> None:
    """Purge toutes les tables dans l'ordre inverse des FK."""
    for table in ("sales", "stock", "calendar", "items"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def ingest_all(
    raw_dir: Path | str = RAW_DIR,
    db_path: Path | str = DB_PATH,
) -> dict[str, int]:
    """Orchestration complète. Ordre respecté pour les FK."""
    raw_dir = Path(raw_dir)
    conn = connect(db_path)
    try:
        init_schema(conn)
        _purge_tables(conn)

        counts = {
            "items": load_items(conn, raw_dir / "items.csv"),
            "calendar": load_calendar(conn, raw_dir / "calendar.csv"),
            "sales": load_sales(conn, raw_dir / "sales.csv"),
            "stock": load_stock(conn, raw_dir / "stock.csv"),
        }
    finally:
        conn.close()
    return counts


def ingest_uploaded(
    conn: sqlite3.Connection, files: dict[str, BinaryIO],
) -> dict[str, int]:
    """Ingest depuis des file-like objects (ex. Streamlit uploads).

    ``files`` doit contenir les clés ``items``, ``sales``, ``stock``.
    La clé ``calendar`` est optionnelle.
    """
    for f in files.values():
        f.seek(0)

    init_schema(conn)
    _purge_tables(conn)

    counts: dict[str, int] = {}
    counts["items"] = load_items(conn, files["items"], "items.csv")
    if "calendar" in files:
        counts["calendar"] = load_calendar(conn, files["calendar"], "calendar.csv")
    counts["sales"] = load_sales(conn, files["sales"], "sales.csv")
    counts["stock"] = load_stock(conn, files["stock"], "stock.csv")
    set_metadata(conn, "dataset_type", "user")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingère les CSV dans SQLite.")
    parser.add_argument("--raw-dir", default=str(RAW_DIR), help="Dossier des CSV")
    parser.add_argument("--db", default=str(DB_PATH), help="Chemin de la base SQLite")
    args = parser.parse_args()

    counts = ingest_all(args.raw_dir, args.db)
    print(f"DB : {args.db}")
    for table, n in counts.items():
        print(f"  {table:10s} {n:>6d} lignes")


if __name__ == "__main__":
    main()

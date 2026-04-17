"""Generate 90 days of simulated data for a fictional restaurant.

Produces 4 CSV files in data/raw/:
  - items.csv      : 25 items (entrées, plats, desserts, boissons)
  - calendar.csv   : 90 days with explicit open/closed flags
  - sales.csv      : multi-item tickets, with ticket_id
  - stock.csv      : one row per (date, item) for open days

Data intentionally contains signals that should trigger V1 rules:
  - P106 : declining trend (triggers rule_declining_item)
  - P107 : waste > 15%       (triggers rule_excessive_waste)
  - P108 : margin < 30%      (triggers rule_low_margin)
  - P109 : frequent stockouts (triggers rule_frequent_stockout)
  - Tuesdays : ~55% of avg daily revenue (triggers rule_slow_weekday)
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SEED = 42
DAYS = 90
END_DATE = date(2026, 4, 14)
START_DATE = END_DATE - timedelta(days=DAYS - 1)

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


@dataclass
class Item:
    item_id: str
    name: str
    category: str
    unit_cost: float
    sell_price: float
    base_demand: float  # expected qty sold per open day


ITEMS: list[Item] = [
    # Entrées (E1xx)
    Item("E101", "Salade César",        "entree",  2.80,  9.50,  8),
    Item("E102", "Soupe du jour",       "entree",  1.60,  7.00,  5),
    Item("E103", "Carpaccio de bœuf",   "entree",  4.20, 12.00,  6),
    Item("E104", "Bruschetta",          "entree",  1.90,  8.00,  7),
    Item("E105", "Tartare de saumon",   "entree",  5.10, 13.50,  4),
    # Plats (P1xx)
    Item("P101", "Burger classique",    "plat",    3.20, 14.50, 18),
    Item("P102", "Entrecôte frites",    "plat",    7.80, 22.00, 10),
    Item("P103", "Magret de canard",    "plat",    6.50, 21.00,  9),
    Item("P104", "Pâtes carbonara",     "plat",    2.40, 13.00, 14),
    Item("P105", "Risotto champignons", "plat",    3.10, 15.00,  8),
    Item("P106", "Tajine agneau",       "plat",    5.80, 18.00, 12),  # déclin
    Item("P107", "Poisson du jour",     "plat",    6.20, 19.00,  9),  # waste élevé
    Item("P108", "Pizza margherita",    "plat",    9.80, 13.00, 14),  # marge faible ~25%
    Item("P109", "Plat végétarien",     "plat",    2.80, 14.00,  6),  # ruptures
    Item("P110", "Côte de porc",        "plat",    4.50, 16.00,  8),
    # Desserts (D1xx)
    Item("D101", "Crème brûlée",        "dessert", 1.20,  7.00,  9),
    Item("D102", "Moelleux chocolat",   "dessert", 1.40,  7.50, 11),
    Item("D103", "Tiramisu",            "dessert", 1.60,  7.50,  8),
    Item("D104", "Fruits frais",        "dessert", 1.80,  6.50,  5),
    Item("D105", "Café gourmand",       "dessert", 1.90,  8.50,  7),
    # Boissons (B1xx)
    Item("B101", "Verre de vin rouge",  "boisson", 1.30,  6.00, 22),
    Item("B102", "Verre de vin blanc",  "boisson", 1.30,  6.00, 14),
    Item("B103", "Bière pression",      "boisson", 0.90,  5.50, 18),
    Item("B104", "Soda",                "boisson", 0.40,  3.50, 16),
    Item("B105", "Eau minérale",        "boisson", 0.25,  3.00, 20),
]


def build_calendar(rng: random.Random) -> list[tuple[date, bool, str]]:
    """Return (date, is_open, notes). Closed Mondays + a few extra closures."""
    extra_closed = {date(2026, 2, 16), date(2026, 3, 30)}  # jours fériés/congés
    cal: list[tuple[date, bool, str]] = []
    for i in range(DAYS):
        d = START_DATE + timedelta(days=i)
        if d.weekday() == 0:  # lundi fermé
            cal.append((d, False, "fermé (lundi)"))
        elif d in extra_closed:
            cal.append((d, False, "fermé (congé)"))
        else:
            cal.append((d, True, ""))
    return cal


def weekday_multiplier(d: date) -> float:
    """Weekend gets +40%, Tuesday is the slow day (~55%)."""
    wd = d.weekday()  # 0=Mon ... 6=Sun
    return {
        1: 0.55,  # mardi = jour creux
        2: 0.95,
        3: 1.00,
        4: 1.20,
        5: 1.40,  # samedi
        6: 1.35,  # dimanche
    }.get(wd, 1.00)


def item_trend(item: Item, day_idx: int) -> float:
    """Multiplier depending on the item's storyline."""
    if item.item_id == "P106":
        # Linéaire : 1.15 -> 0.55 sur 90 jours (-50%+ sur la période)
        return 1.15 - (day_idx / (DAYS - 1)) * 0.60
    return 1.0


def simulate_day_sales(
    d: date, day_idx: int, rng: random.Random, np_rng: np.random.Generator
) -> list[dict]:
    """Generate ticket-level sales for one open day."""
    multiplier = weekday_multiplier(d)
    # Nombre de tickets de la journée : base 35, +/- bruit
    n_tickets = max(5, int(np_rng.normal(loc=35 * multiplier, scale=4)))
    rows: list[dict] = []
    for t in range(n_tickets):
        ticket_id = f"T{d.strftime('%Y%m%d')}-{t + 1:03d}"
        n_items = rng.choices([1, 2, 3, 4, 5], weights=[10, 35, 30, 18, 7])[0]
        # Choix d'items pondéré par base_demand × trend × disponibilité
        weights = []
        for it in ITEMS:
            w = it.base_demand * item_trend(it, day_idx)
            # P109 : ruptures fréquentes -> 40% de chance d'être indisponible
            if it.item_id == "P109" and rng.random() < 0.40:
                w = 0
            weights.append(max(w, 0.01))
        chosen = rng.choices(ITEMS, weights=weights, k=n_items)
        # Dédupe en regroupant les quantités
        counts: dict[str, int] = {}
        for it in chosen:
            counts[it.item_id] = counts.get(it.item_id, 0) + 1
        for item_id, qty in counts.items():
            it = next(x for x in ITEMS if x.item_id == item_id)
            rows.append({
                "date": d.isoformat(),
                "ticket_id": ticket_id,
                "item_id": item_id,
                "quantity": qty,
                "unit_price": round(it.sell_price, 2),
                "total": round(it.sell_price * qty, 2),
            })
    return rows


def simulate_stock(
    open_days: list[date],
    sales_by_day_item: dict[tuple[str, str], int],
    rng: random.Random,
    np_rng: np.random.Generator,
) -> list[dict]:
    """One stock row per (open_day, item)."""
    rows: list[dict] = []
    # État courant du stock par item
    stock_open = {it.item_id: int(it.base_demand * 2) for it in ITEMS}
    for d in open_days:
        for it in ITEMS:
            qty_open = stock_open[it.item_id]
            qty_sold = sales_by_day_item.get((d.isoformat(), it.item_id), 0)
            # Livraison visant à couvrir 1.5 × demande de base
            target = int(it.base_demand * 1.5)
            qty_received = max(0, target - qty_open + qty_sold)
            # Waste : baseline ~3%, élevé pour P107 (~20%)
            if it.item_id == "P107":
                waste_rate = np_rng.uniform(0.15, 0.25)
            else:
                waste_rate = np_rng.uniform(0.00, 0.06)
            available = qty_open + qty_received
            waste = int(round(available * waste_rate))
            qty_close = max(0, available - qty_sold - waste)
            rows.append({
                "date": d.isoformat(),
                "item_id": it.item_id,
                "qty_open": qty_open,
                "qty_received": qty_received,
                "qty_close": qty_close,
                "waste": waste,
            })
            stock_open[it.item_id] = qty_close
    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_demo_csvs(output_dir: Path) -> dict[str, int]:
    """Generate demo CSV files in *output_dir*. Returns row counts per table."""
    rng = random.Random(SEED)
    np_rng = np.random.default_rng(SEED)

    # items.csv
    items_rows = [
        {
            "item_id": it.item_id,
            "name": it.name,
            "category": it.category,
            "unit_cost": it.unit_cost,
            "sell_price": it.sell_price,
        }
        for it in ITEMS
    ]
    write_csv(
        output_dir / "items.csv",
        items_rows,
        ["item_id", "name", "category", "unit_cost", "sell_price"],
    )

    # calendar.csv
    calendar = build_calendar(rng)
    write_csv(
        output_dir / "calendar.csv",
        [{"date": d.isoformat(), "is_open": int(op), "notes": nt} for d, op, nt in calendar],
        ["date", "is_open", "notes"],
    )

    # sales.csv
    sales_rows: list[dict] = []
    for idx, (d, op, _) in enumerate(calendar):
        if not op:
            continue
        sales_rows.extend(simulate_day_sales(d, idx, rng, np_rng))
    write_csv(
        output_dir / "sales.csv",
        sales_rows,
        ["date", "ticket_id", "item_id", "quantity", "unit_price", "total"],
    )

    # stock.csv
    open_days = [d for d, op, _ in calendar if op]
    sales_by_day_item: dict[tuple[str, str], int] = {}
    for r in sales_rows:
        key = (r["date"], r["item_id"])
        sales_by_day_item[key] = sales_by_day_item.get(key, 0) + r["quantity"]
    stock_rows = simulate_stock(open_days, sales_by_day_item, rng, np_rng)
    write_csv(
        output_dir / "stock.csv",
        stock_rows,
        ["date", "item_id", "qty_open", "qty_received", "qty_close", "waste"],
    )

    return {
        "items": len(items_rows),
        "calendar": len(calendar),
        "sales": len(sales_rows),
        "stock": len(stock_rows),
    }


def main() -> None:
    counts = generate_demo_csvs(RAW_DIR)
    open_days = counts["calendar"] - 13  # lundis + fériés
    total_sales = counts["sales"]
    print(f"Période : {START_DATE} -> {END_DATE} ({DAYS} jours)")
    print(f"Jours ouverts : {open_days} / {DAYS}")
    print(f"Items : {counts['items']}")
    print(f"Lignes de vente : {total_sales}")
    print(f"Lignes de stock : {counts['stock']}")
    print(f"CSV écrits dans : {RAW_DIR}")


if __name__ == "__main__":
    main()

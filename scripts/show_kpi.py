"""Imprime tous les KPI V1 sur la base ingérée. Utile pour vérifier visuellement.

Usage : ``uv run python scripts/show_kpi.py``
"""
from __future__ import annotations

import pandas as pd

from la_bonne_table import kpi
from la_bonne_table.db import connect

pd.set_option("display.max_rows", 60)
pd.set_option("display.width", 120)
pd.set_option("display.float_format", lambda v: f"{v:,.2f}")


def _title(txt: str) -> None:
    print(f"\n=== {txt} ===")


def main() -> None:
    conn = connect()

    _title("Vue d'ensemble")
    print(f"CA total          : {kpi.revenue_total(conn):>12,.2f} €")
    print(f"Tickets           : {kpi.ticket_count(conn):>12d}")
    print(f"Panier moyen      : {kpi.average_ticket(conn):>12,.2f} €")
    days = kpi.open_closed_days(conn)
    print(f"Jours ouverts     : {days['open']} / {days['total']}  (fermés : {days['closed']})")

    _title("Marge brute globale")
    g = kpi.global_gross_margin(conn)
    print(f"CA                : {g['revenue']:>12,.2f} €")
    print(f"Coût matière      : {g['cost']:>12,.2f} €")
    print(f"Marge brute       : {g['gross_margin']:>12,.2f} €")
    print(f"Taux de marge     : {g['margin_rate']:>12.1%}")

    _title("Waste global")
    w = kpi.waste_rate_global(conn)
    print(f"Waste             : {w['waste']} / {w['available']} = {w['waste_rate']:.1%}")

    _title("Top 5 par CA")
    print(kpi.top_items_by_revenue(conn, n=5).to_string(index=False))

    _title("Flop 5 par CA")
    print(kpi.flop_items_by_revenue(conn, n=5).to_string(index=False))

    _title("Top 5 par volume")
    print(kpi.top_items_by_volume(conn, n=5).to_string(index=False))

    _title("Marge par item (items avec marge < 30%)")
    m = kpi.gross_margin_by_item(conn)
    low = m[m["margin_rate"] < 0.30].sort_values("margin_rate")
    cols = ["item_id", "name", "qty", "revenue", "gross_margin", "margin_rate"]
    print(low[cols].to_string(index=False))

    _title("Waste par item (> 10%)")
    wdf = kpi.waste_rate_by_item(conn)
    high = wdf[wdf["waste_rate"] > 0.10].sort_values("waste_rate", ascending=False)
    print(high[["item_id", "name", "waste", "available", "waste_rate"]].to_string(index=False))

    _title("Rotation stock (bottom 5)")
    rot = kpi.stock_rotation(conn).sort_values("rotation").head(5)
    print(rot[["item_id", "name", "qty_sold", "avg_close", "rotation"]].to_string(index=False))

    _title("Comparaison 30 derniers jours vs précédents 30 jours")
    pc = kpi.period_comparison(conn, window_days=30)
    if pc is None:
        print("Pas de données.")
    else:
        curr = f"{pc.current_revenue:>10,.2f} €"
        prev = f"{pc.previous_revenue:>10,.2f} €"
        print(f"Courante   [{pc.current_start} → {pc.current_end}] : {curr}")
        print(f"Précédente [{pc.previous_start} → {pc.previous_end}] : {prev}")
        print(f"Delta              : {pc.delta_pct:+.1%}")

    conn.close()


if __name__ == "__main__":
    main()

"""Moteur de règles V1.

5 règles déterministes qui consomment les KPI pour produire des
recommandations priorisées. Pas de ML, pas de LLM — if/else pur.

Priorités :
    1 = critique  (action immédiate)
    2 = élevée    (opportunité business)
    3 = moyenne   (optimisation)
    4 = info      (observation)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from la_bonne_table import kpi

PRIORITY_LABELS: dict[int, str] = {
    1: "critique",
    2: "élevée",
    3: "moyenne",
    4: "info",
}

WEEKDAY_NAMES_FR: list[str] = [
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"
]


@dataclass
class Recommendation:
    type: str
    priority: int
    message: str
    metric_value: float | None = None
    item_id: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_range(
    conn: sqlite3.Connection, end: str | None, days: int
) -> tuple[str, str] | None:
    """Retourne (start, end) pour une fenêtre de `days` jours se terminant à `end`.

    Si `end` est None on prend la date max présente dans `sales`.
    """
    if end is None:
        row = conn.execute("SELECT MAX(date) AS d FROM sales").fetchone()
        if row["d"] is None:
            return None
        end = row["d"]
    end_d = date.fromisoformat(end)
    start = (end_d - timedelta(days=days - 1)).isoformat()
    return start, end


# ---------------------------------------------------------------------------
# Règles
# ---------------------------------------------------------------------------


def rule_excessive_waste(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    threshold: float = 0.15,
) -> list[Recommendation]:
    """Items dont le taux de perte dépasse `threshold` sur la période."""
    df = kpi.waste_rate_by_item(conn, start, end)
    df = df[df["waste_rate"] > threshold].sort_values("waste_rate", ascending=False)
    recos: list[Recommendation] = []
    for _, r in df.iterrows():
        recos.append(
            Recommendation(
                type="excessive_waste",
                priority=1,
                message=(
                    f"Waste élevé sur {r['name']} : {r['waste_rate']:.0%} "
                    f"({int(r['waste'])} perdus sur {int(r['available'])}). "
                    "Réduis les commandes d'environ 20%."
                ),
                metric_value=float(r["waste_rate"]),
                item_id=str(r["item_id"]),
            )
        )
    return recos


def rule_frequent_stockout(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    min_zero_days: int = 5,
) -> list[Recommendation]:
    """Items avec ``qty_close = 0`` sur plus de `min_zero_days` jours."""
    where, params = kpi._where_date(start, end, "st.date")  # noqa: SLF001
    df = pd.read_sql(
        f"""SELECT st.item_id, i.name,
                   SUM(CASE WHEN st.qty_close = 0 THEN 1 ELSE 0 END) AS zero_days
            FROM stock st
            JOIN items i ON i.item_id = st.item_id
            {where}
            GROUP BY st.item_id, i.name
            HAVING zero_days > ?
            ORDER BY zero_days DESC""",
        conn,
        params=[*params, min_zero_days],
    )
    recos: list[Recommendation] = []
    for _, r in df.iterrows():
        recos.append(
            Recommendation(
                type="frequent_stockout",
                priority=1,
                message=(
                    f"Rupture fréquente sur {r['name']} : "
                    f"{int(r['zero_days'])} jours en rupture. "
                    "Augmente le stock tampon ou revois la fréquence de livraison."
                ),
                metric_value=float(r["zero_days"]),
                item_id=str(r["item_id"]),
            )
        )
    return recos


def rule_declining_item(
    conn: sqlite3.Connection,
    end: str | None = None,
    top_n: int = 10,
    window_days: int = 7,
    threshold: float = -0.20,
) -> list[Recommendation]:
    """Items du top CA (30j) dont le CA chute de plus de `threshold` semaine sur semaine."""
    rng = _default_range(conn, end, 30)
    if rng is None:
        return []
    ref_start, end_str = rng

    end_d = date.fromisoformat(end_str)
    curr_start = (end_d - timedelta(days=window_days - 1)).isoformat()
    prev_end = (end_d - timedelta(days=window_days)).isoformat()
    prev_start = (end_d - timedelta(days=2 * window_days - 1)).isoformat()

    top = kpi.top_items_by_revenue(conn, n=top_n, start=ref_start, end=end_str)
    if top.empty:
        return []

    def _rev(item_ids: list[str], start: str, end: str) -> dict[str, float]:
        if not item_ids:
            return {}
        placeholders = ",".join("?" * len(item_ids))
        rows = conn.execute(
            f"SELECT item_id, SUM(total) AS r FROM sales "
            f"WHERE date BETWEEN ? AND ? AND item_id IN ({placeholders}) "
            "GROUP BY item_id",
            [start, end, *item_ids],
        ).fetchall()
        return {row["item_id"]: float(row["r"] or 0.0) for row in rows}

    item_ids = list(top["item_id"])
    curr_rev = _rev(item_ids, curr_start, end_str)
    prev_rev = _rev(item_ids, prev_start, prev_end)

    recos: list[Recommendation] = []
    for _, r in top.iterrows():
        item_id = r["item_id"]
        prev = prev_rev.get(item_id, 0.0)
        curr = curr_rev.get(item_id, 0.0)
        if prev <= 0:
            continue
        delta = (curr - prev) / prev
        if delta <= threshold:
            recos.append(
                Recommendation(
                    type="declining_item",
                    priority=2,
                    message=(
                        f"{r['name']} en baisse de {delta:+.0%} "
                        f"(CA {curr:.0f}€ vs {prev:.0f}€ la semaine précédente). "
                        "Teste une promo ou revois la carte."
                    ),
                    metric_value=float(delta),
                    item_id=str(item_id),
                )
            )
    return recos


def rule_low_margin(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    margin_threshold: float = 0.30,
    min_qty: int = 50,
) -> list[Recommendation]:
    """Items vendus en volume avec une marge brute inférieure au seuil."""
    df = kpi.gross_margin_by_item(conn, start, end)
    df = df[(df["margin_rate"] < margin_threshold) & (df["qty"] >= min_qty)]
    df = df.sort_values("margin_rate")
    recos: list[Recommendation] = []
    for _, r in df.iterrows():
        recos.append(
            Recommendation(
                type="low_margin",
                priority=2,
                message=(
                    f"Marge faible sur {r['name']} : {r['margin_rate']:.0%} "
                    f"(vendu {int(r['qty'])} fois). "
                    "Renégocie le coût matière ou augmente le prix."
                ),
                metric_value=float(r["margin_rate"]),
                item_id=str(r["item_id"]),
            )
        )
    return recos


def rule_slow_weekday(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    threshold: float = 0.60,
) -> list[Recommendation]:
    """Jours de la semaine dont le CA moyen est < `threshold` × moyenne globale.

    Seuls les jours ouverts comptent (ceux sans vente sont exclus de fait).
    """
    df = kpi.revenue_by_day(conn, start, end)
    if df.empty:
        return []
    df = df.copy()
    df["weekday"] = pd.to_datetime(df["date"]).dt.dayofweek
    overall_avg = df["revenue"].mean()
    if overall_avg <= 0:
        return []
    per_wd = df.groupby("weekday")["revenue"].mean()
    recos: list[Recommendation] = []
    for wd, avg in per_wd.items():
        ratio = avg / overall_avg
        if ratio < threshold:
            name = WEEKDAY_NAMES_FR[int(wd)]
            recos.append(
                Recommendation(
                    type="slow_weekday",
                    priority=4,
                    message=(
                        f"{name.capitalize()} : CA moyen {avg:.0f}€ "
                        f"({ratio:.0%} de la moyenne). "
                        "Teste une offre happy hour ou un menu spécial."
                    ),
                    metric_value=float(ratio),
                )
            )
    return recos


# ---------------------------------------------------------------------------
# Orchestration + persistance
# ---------------------------------------------------------------------------


def run_all_rules(
    conn: sqlite3.Connection, end: str | None = None, window_days: int = 30
) -> list[Recommendation]:
    """Exécute les 5 règles sur la fenêtre par défaut (`window_days` derniers jours)."""
    rng = _default_range(conn, end, window_days)
    if rng is None:
        return []
    start, end_str = rng

    recos: list[Recommendation] = []
    recos.extend(rule_excessive_waste(conn, start, end_str))
    recos.extend(rule_frequent_stockout(conn, start, end_str))
    recos.extend(rule_declining_item(conn, end=end_str))
    recos.extend(rule_low_margin(conn, start, end_str))
    recos.extend(rule_slow_weekday(conn, start, end_str))
    recos.sort(key=lambda r: (r.priority, r.type, r.item_id or ""))
    return recos


def save_recommendations(
    conn: sqlite3.Connection, recos: list[Recommendation]
) -> int:
    """Persiste les recommandations (purge préalable de la table)."""
    conn.execute("DELETE FROM recommendations")
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO recommendations (generated_at, type, priority, message, metric_value) "
        "VALUES (?, ?, ?, ?, ?)",
        [(now, r.type, r.priority, r.message, r.metric_value) for r in recos],
    )
    conn.commit()
    return len(recos)

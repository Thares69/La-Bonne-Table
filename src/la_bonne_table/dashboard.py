"""Dashboard Streamlit V1 — La Bonne Table.

3 pages : Accueil (KPI + recommandations), Ventes (graphes), Stock (pertes + rotation).
Aucune logique métier ici — tout est délégué à kpi.py et rules.py.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import plotly.express as px
import streamlit as st

from la_bonne_table import kpi, rules
from la_bonne_table.db import DB_PATH, connect, init_schema

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="La Bonne Table", layout="wide")

CATEGORY_COLORS = {
    "entree": "#4CAF50",
    "plat": "#2196F3",
    "dessert": "#FF9800",
    "boisson": "#9C27B0",
}

CATEGORY_LABELS = {
    "entree": "Entr\u00e9e",
    "plat": "Plat",
    "dessert": "Dessert",
    "boisson": "Boisson",
}

RECO_TYPE_LABELS = {
    "excessive_waste": "Pertes excessives",
    "frequent_stockout": "Rupture de stock",
    "declining_item": "Produit en baisse",
    "low_margin": "Marge faible",
    "slow_weekday": "Jour creux",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_conn():
    if not Path(DB_PATH).exists():
        return None
    conn = connect()
    init_schema(conn)
    return conn


def _date_bounds(conn):
    row = conn.execute(
        "SELECT MIN(date) AS mn, MAX(date) AS mx FROM sales"
    ).fetchone()
    if row["mn"] is None:
        return None, None
    return date.fromisoformat(row["mn"]), date.fromisoformat(row["mx"])


def _reco_label(reco_type: str) -> str:
    return RECO_TYPE_LABELS.get(reco_type, reco_type.replace("_", " ").title())


def _bar_h(df, x, y, color=None, height=None):
    """Bar chart horizontal standardis\u00e9."""
    fig = px.bar(
        df,
        x=x,
        y=y,
        orientation="h",
        color=color,
        color_discrete_map=CATEGORY_COLORS if color == "category" else None,
    )
    fig.update_layout(
        yaxis={"autorange": "reversed", "title": ""},
        xaxis={"title": ""},
        margin={"l": 0, "r": 0, "t": 5, "b": 0},
        showlegend=color is not None,
        legend={"orientation": "h", "y": -0.15} if color else {},
        height=height or max(250, len(df) * 32 + 60),
    )
    return fig


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def render_sidebar(conn):
    st.sidebar.markdown("### La Bonne Table")
    st.sidebar.caption("Tableau de bord restaurant")

    page = st.sidebar.radio(
        "Navigation",
        ["Accueil", "Ventes", "Stock"],
        label_visibility="collapsed",
    )

    st.sidebar.divider()

    dmin, dmax = _date_bounds(conn)
    if dmin is None:
        st.sidebar.warning("Aucune donn\u00e9e en base.")
        return page, None, None

    st.sidebar.markdown("**P\u00e9riode d'analyse**")
    start = st.sidebar.date_input(
        "Du", value=dmin, min_value=dmin, max_value=dmax
    )
    end = st.sidebar.date_input(
        "Au", value=dmax, min_value=dmin, max_value=dmax
    )

    if start > end:
        st.sidebar.error("La date de d\u00e9but doit pr\u00e9c\u00e9der la fin.")
        return page, None, None

    return page, start.isoformat(), end.isoformat()


# ---------------------------------------------------------------------------
# Page : Accueil
# ---------------------------------------------------------------------------


def render_home(conn, start, end):
    st.header("Vue d'ensemble")
    st.caption("Indicateurs cl\u00e9s et alertes sur la p\u00e9riode s\u00e9lectionn\u00e9e")

    # --- KPI : performance ---
    rev = kpi.revenue_total(conn, start, end)
    n_tickets = kpi.ticket_count(conn, start, end)
    avg = kpi.average_ticket(conn, start, end)
    gm = kpi.global_gross_margin(conn, start, end)
    waste = kpi.waste_rate_global(conn, start, end)
    days = kpi.open_closed_days(conn, start, end)

    pc = kpi.period_comparison(conn, end=end, window_days=30)
    rev_delta = f"{pc.delta_pct:+.1%}" if pc and pc.previous_revenue > 0 else None

    c1, c2, c3 = st.columns(3)
    c1.metric("Chiffre d'affaires", f"{rev:,.0f} \u20ac", rev_delta)
    c2.metric("Nombre de tickets", f"{n_tickets:,}")
    c3.metric("Panier moyen", f"{avg:,.2f} \u20ac")

    # --- KPI : santé ---
    c4, c5, c6 = st.columns(3)
    c4.metric("Marge brute", f"{gm['margin_rate']:.1%}")
    c5.metric("Taux de pertes", f"{waste['waste_rate']:.1%}")
    c6.metric(
        "Jours ouverts",
        f"{days['open']} / {days['total']}",
        f"{days['closed']} ferm\u00e9(s)",
        delta_color="off",
    )

    # --- Recommandations ---
    st.divider()
    recos = rules.run_all_rules(conn, end=end)

    if not recos:
        st.success("Aucune alerte. Tout roule sur la p\u00e9riode.")
        return

    critical = [r for r in recos if r.priority == 1]
    high = [r for r in recos if r.priority == 2]
    info = [r for r in recos if r.priority >= 3]

    st.subheader(f"Recommandations ({len(recos)})")

    if critical:
        st.markdown("**A traiter en priorit\u00e9**")
        for r in critical:
            st.error(f"**{_reco_label(r.type)}** \u2014 {r.message}", icon="\u26a0\ufe0f")

    if high:
        st.markdown("**Opportunit\u00e9s d'am\u00e9lioration**")
        for r in high:
            st.warning(f"**{_reco_label(r.type)}** \u2014 {r.message}")

    if info:
        with st.expander(f"Observations ({len(info)})"):
            for r in info:
                st.info(f"**{_reco_label(r.type)}** \u2014 {r.message}")


# ---------------------------------------------------------------------------
# Page : Ventes
# ---------------------------------------------------------------------------


def render_sales(conn, start, end):
    st.header("Analyse des ventes")
    st.caption("\u00c9volution du chiffre d'affaires et classement des produits")

    # --- Comparaison 30j ---
    pc = kpi.period_comparison(conn, end=end, window_days=30)
    if pc:
        c1, c2 = st.columns(2)
        delta = f"{pc.delta_pct:+.1%}" if pc.previous_revenue > 0 else None
        c1.metric(
            "CA \u2014 30 derniers jours",
            f"{pc.current_revenue:,.0f} \u20ac",
            delta,
        )
        c2.metric(
            "CA \u2014 30 jours pr\u00e9c\u00e9dents",
            f"{pc.previous_revenue:,.0f} \u20ac",
        )

    # --- CA par jour ---
    st.subheader("\u00c9volution du CA journalier")
    df_rev = kpi.revenue_by_day(conn, start, end)
    if df_rev.empty:
        st.info("Aucune vente sur cette p\u00e9riode.")
        return

    fig = px.line(
        df_rev,
        x="date",
        y="revenue",
        markers=True,
        labels={"date": "", "revenue": "CA (\u20ac)"},
    )
    fig.update_layout(margin={"l": 0, "r": 0, "t": 5, "b": 0})
    st.plotly_chart(fig, use_container_width=True)

    # --- Top / Flop ---
    st.subheader("Classement des produits")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Meilleurs produits (CA)**")
        top = kpi.top_items_by_revenue(conn, n=5, start=start, end=end)
        st.plotly_chart(
            _bar_h(top, x="revenue", y="name", color="category"),
            use_container_width=True,
        )

    with col_right:
        st.markdown("**Moins performants (CA)**")
        flop = kpi.flop_items_by_revenue(conn, n=5, start=start, end=end)
        st.plotly_chart(
            _bar_h(flop, x="revenue", y="name", color="category"),
            use_container_width=True,
        )

    col_vol, col_margin = st.columns(2)
    with col_vol:
        st.markdown("**Les plus vendus (volume)**")
        vol = kpi.top_items_by_volume(conn, n=5, start=start, end=end)
        st.plotly_chart(
            _bar_h(vol, x="qty", y="name", color="category"),
            use_container_width=True,
        )

    # --- Marge par item ---
    with col_margin:
        st.markdown("**Marge brute par produit**")
        margin_df = kpi.gross_margin_by_item(conn, start, end)
        margin_df = margin_df.copy()
        margin_df["margin_pct"] = (margin_df["margin_rate"] * 100).round(1)
        fig = px.bar(
            margin_df.sort_values("margin_rate"),
            x="margin_pct",
            y="name",
            orientation="h",
            color="category",
            color_discrete_map=CATEGORY_COLORS,
            labels={"margin_pct": "Marge (%)", "name": ""},
        )
        fig.add_vline(
            x=30, line_dash="dash", line_color="red",
            annotation_text="seuil alerte",
        )
        fig.update_layout(
            yaxis={"autorange": "reversed", "title": ""},
            margin={"l": 0, "r": 0, "t": 5, "b": 0},
            height=max(400, len(margin_df) * 22 + 60),
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Page : Stock
# ---------------------------------------------------------------------------


def render_stock(conn, start, end):
    st.header("Gestion des stocks")
    st.caption("Pertes, rotation et tensions d'approvisionnement")

    # --- KPI card ---
    waste_g = kpi.waste_rate_global(conn, start, end)
    c1, c2, c3 = st.columns(3)
    c1.metric("Taux de pertes", f"{waste_g['waste_rate']:.1%}")
    c2.metric("Unit\u00e9s perdues", f"{waste_g['waste']:,}")
    c3.metric("Unit\u00e9s disponibles", f"{waste_g['available']:,}")

    # --- Pertes par item ---
    st.subheader("Pertes par produit")
    wdf = kpi.waste_rate_by_item(conn, start, end)
    wdf_plot = wdf[wdf["waste_rate"] > 0].sort_values("waste_rate", ascending=False)
    if not wdf_plot.empty:
        wdf_plot = wdf_plot.copy()
        wdf_plot["perte_pct"] = (wdf_plot["waste_rate"] * 100).round(1)
        fig = px.bar(
            wdf_plot,
            x="perte_pct",
            y="name",
            orientation="h",
            color="category",
            color_discrete_map=CATEGORY_COLORS,
            labels={"perte_pct": "Pertes (%)", "name": ""},
        )
        fig.add_vline(
            x=15, line_dash="dash", line_color="red",
            annotation_text="seuil alerte",
        )
        fig.update_layout(
            yaxis={"autorange": "reversed", "title": ""},
            margin={"l": 0, "r": 0, "t": 5, "b": 0},
            height=max(300, len(wdf_plot) * 28 + 60),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.success("Aucune perte enregistr\u00e9e sur la p\u00e9riode.")

    # --- Rotation stock ---
    col_rot, col_rupt = st.columns(2)

    with col_rot:
        st.subheader("Rotation des stocks")
        st.caption("Plus la valeur est basse, plus le produit stagne")
        rot = kpi.stock_rotation(conn, start, end)
        rot_low = rot[rot["avg_close"] > 0].sort_values("rotation").head(10)
        if not rot_low.empty:
            st.plotly_chart(
                _bar_h(rot_low, x="rotation", y="name", color="category"),
                use_container_width=True,
            )

    # --- Ruptures ---
    with col_rupt:
        st.subheader("Ruptures de stock")
        st.caption("Produits ayant \u00e9t\u00e9 \u00e0 z\u00e9ro au moins un jour")
        sout = kpi.stockout_days_by_item(conn, start, end)
        sout_pos = sout[sout["zero_days"] > 0]
        if sout_pos.empty:
            st.success("Aucune rupture sur la p\u00e9riode.")
        else:
            st.dataframe(
                sout_pos[["name", "category", "zero_days", "total_days"]].rename(
                    columns={
                        "name": "Produit",
                        "category": "Cat\u00e9gorie",
                        "zero_days": "Jours en rupture",
                        "total_days": "Jours mesur\u00e9s",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    conn = _open_conn()
    if conn is None:
        st.error(
            "Base introuvable. Lance d'abord :\n\n"
            "```bash\n"
            "uv run python scripts/seed_data.py\n"
            "uv run python -m la_bonne_table.ingest\n"
            "```"
        )
        return

    try:
        page, start, end = render_sidebar(conn)
        if start is None or end is None:
            st.info("S\u00e9lectionne une p\u00e9riode valide dans la sidebar.")
            return

        if page == "Accueil":
            render_home(conn, start, end)
        elif page == "Ventes":
            render_sales(conn, start, end)
        elif page == "Stock":
            render_stock(conn, start, end)
    finally:
        conn.close()


main()

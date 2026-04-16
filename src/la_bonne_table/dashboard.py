"""Dashboard Streamlit V1 — La Bonne Table.

3 pages : Accueil (KPI + recommandations), Ventes (graphes), Stock (waste + rotation).
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

COLORS = {
    "entree": "#4CAF50",
    "plat": "#2196F3",
    "dessert": "#FF9800",
    "boisson": "#9C27B0",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_conn():
    """Ouvre la connexion et initialise le schéma si besoin."""
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


def _compact_bar(df, x, y, color=None, title=None):
    """Bar chart horizontal compact."""
    fig = px.bar(
        df,
        x=x,
        y=y,
        orientation="h",
        color=color,
        color_discrete_map=COLORS if color == "category" else None,
        title=title,
    )
    fig.update_layout(
        yaxis={"autorange": "reversed", "title": ""},
        xaxis={"title": ""},
        margin={"l": 0, "r": 0, "t": 30 if title else 10, "b": 0},
        showlegend=color is not None,
        height=max(250, len(df) * 32 + 60),
    )
    return fig


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def render_sidebar(conn):
    st.sidebar.title("La Bonne Table")
    page = st.sidebar.radio("Navigation", ["Accueil", "Ventes", "Stock"])

    dmin, dmax = _date_bounds(conn)
    if dmin is None:
        st.sidebar.warning("Pas de ventes en base.")
        return page, None, None

    st.sidebar.caption(f"Donn\u00e9es du {dmin} au {dmax}")
    start = st.sidebar.date_input("D\u00e9but", value=dmin, min_value=dmin, max_value=dmax)
    end = st.sidebar.date_input("Fin", value=dmax, min_value=dmin, max_value=dmax)

    if start > end:
        st.sidebar.error("La date de d\u00e9but doit pr\u00e9c\u00e9der la date de fin.")
        return page, None, None

    return page, start.isoformat(), end.isoformat()


# ---------------------------------------------------------------------------
# Page : Accueil
# ---------------------------------------------------------------------------


def render_home(conn, start, end):
    st.header("Vue d'ensemble")

    # --- KPI cards ---
    rev = kpi.revenue_total(conn, start, end)
    n_tickets = kpi.ticket_count(conn, start, end)
    avg = kpi.average_ticket(conn, start, end)
    gm = kpi.global_gross_margin(conn, start, end)
    waste = kpi.waste_rate_global(conn, start, end)
    days = kpi.open_closed_days(conn, start, end)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("CA total", f"{rev:,.0f} \u20ac")
    c2.metric("Tickets", f"{n_tickets:,}")
    c3.metric("Panier moyen", f"{avg:,.2f} \u20ac")
    c4.metric("Marge brute", f"{gm['margin_rate']:.1%}")
    c5.metric("Waste global", f"{waste['waste_rate']:.1%}")
    c6.metric("Jours ouverts", f"{days['open']} / {days['total']}")

    # --- Delta 30j ---
    pc = kpi.period_comparison(conn, end=end, window_days=30)
    if pc and pc.previous_revenue > 0:
        st.caption(
            f"CA 30 derniers jours : **{pc.current_revenue:,.0f} \u20ac** "
            f"({pc.delta_pct:+.1%} vs p\u00e9riode pr\u00e9c\u00e9dente)"
        )

    # --- Recommandations ---
    st.divider()
    st.subheader("Recommandations")

    recos = rules.run_all_rules(conn, end=end)
    if not recos:
        st.success("Aucune alerte sur la p\u00e9riode. Tout roule.")
        return

    critical = [r for r in recos if r.priority == 1]
    high = [r for r in recos if r.priority == 2]
    info = [r for r in recos if r.priority >= 3]

    MAX_VISIBLE = 6
    shown = 0

    if critical:
        st.markdown("**Actions imm\u00e9diates**")
        for r in critical:
            if shown < MAX_VISIBLE:
                st.error(f"**{r.type.replace('_', ' ').title()}** \u2014 {r.message}")
                shown += 1

    if high:
        st.markdown("**Opportunit\u00e9s**")
        for r in high:
            if shown < MAX_VISIBLE:
                st.warning(f"**{r.type.replace('_', ' ').title()}** \u2014 {r.message}")
                shown += 1

    overflow = critical[MAX_VISIBLE:] + high[MAX_VISIBLE - len(critical):]
    if overflow or info:
        with st.expander(f"Voir tout ({len(recos)} recommandations)"):
            for r in overflow:
                st.warning(r.message)
            for r in info:
                st.info(r.message)


# ---------------------------------------------------------------------------
# Page : Ventes
# ---------------------------------------------------------------------------


def render_sales(conn, start, end):
    st.header("Ventes")

    # --- Comparaison ---
    pc = kpi.period_comparison(conn, end=end, window_days=30)
    if pc:
        c1, c2 = st.columns(2)
        delta = f"{pc.delta_pct:+.1%}" if pc.previous_revenue > 0 else "n/a"
        c1.metric("CA 30 derniers jours", f"{pc.current_revenue:,.0f} \u20ac", delta)
        c2.metric("CA 30 jours pr\u00e9c\u00e9dents", f"{pc.previous_revenue:,.0f} \u20ac")

    # --- CA par jour ---
    st.subheader("CA par jour")
    df_rev = kpi.revenue_by_day(conn, start, end)
    if not df_rev.empty:
        fig = px.line(
            df_rev,
            x="date",
            y="revenue",
            markers=True,
            labels={"date": "", "revenue": "CA (\u20ac)"},
        )
        fig.update_layout(margin={"l": 0, "r": 0, "t": 10, "b": 0})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Pas de ventes sur cette p\u00e9riode.")
        return

    # --- Top / Flop / Volume ---
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Top 5 par CA")
        top = kpi.top_items_by_revenue(conn, n=5, start=start, end=end)
        st.plotly_chart(
            _compact_bar(top, x="revenue", y="name", color="category"),
            use_container_width=True,
        )

    with col_right:
        st.subheader("Flop 5 par CA")
        flop = kpi.flop_items_by_revenue(conn, n=5, start=start, end=end)
        st.plotly_chart(
            _compact_bar(flop, x="revenue", y="name", color="category"),
            use_container_width=True,
        )

    st.subheader("Top 5 par volume")
    vol = kpi.top_items_by_volume(conn, n=5, start=start, end=end)
    st.plotly_chart(
        _compact_bar(vol, x="qty", y="name", color="category"),
        use_container_width=True,
    )

    # --- Marge par item ---
    st.subheader("Marge brute par produit")
    margin_df = kpi.gross_margin_by_item(conn, start, end)
    margin_df["margin_rate_pct"] = (margin_df["margin_rate"] * 100).round(1)
    fig = px.bar(
        margin_df.sort_values("margin_rate"),
        x="margin_rate_pct",
        y="name",
        orientation="h",
        color="category",
        color_discrete_map=COLORS,
        labels={"margin_rate_pct": "Marge (%)", "name": ""},
    )
    fig.add_vline(x=30, line_dash="dash", line_color="red", annotation_text="seuil 30%")
    fig.update_layout(
        yaxis={"autorange": "reversed", "title": ""},
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        height=max(400, len(margin_df) * 24 + 60),
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Page : Stock
# ---------------------------------------------------------------------------


def render_stock(conn, start, end):
    st.header("Stock")

    # --- KPI card ---
    waste_g = kpi.waste_rate_global(conn, start, end)
    c1, c2, c3 = st.columns(3)
    c1.metric("Waste global", f"{waste_g['waste_rate']:.1%}")
    c2.metric("Perdus", f"{waste_g['waste']:,}")
    c3.metric("Disponibles", f"{waste_g['available']:,}")

    # --- Waste par item ---
    st.subheader("Taux de perte par produit")
    wdf = kpi.waste_rate_by_item(conn, start, end)
    wdf_plot = wdf[wdf["waste_rate"] > 0].sort_values("waste_rate", ascending=False)
    if not wdf_plot.empty:
        wdf_plot = wdf_plot.copy()
        wdf_plot["waste_rate_pct"] = (wdf_plot["waste_rate"] * 100).round(1)
        fig = px.bar(
            wdf_plot,
            x="waste_rate_pct",
            y="name",
            orientation="h",
            color="category",
            color_discrete_map=COLORS,
            labels={"waste_rate_pct": "Waste (%)", "name": ""},
        )
        fig.add_vline(
            x=15, line_dash="dash", line_color="red", annotation_text="seuil 15%"
        )
        fig.update_layout(
            yaxis={"autorange": "reversed", "title": ""},
            margin={"l": 0, "r": 0, "t": 10, "b": 0},
            height=max(300, len(wdf_plot) * 28 + 60),
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- Rotation stock ---
    st.subheader("Rotation stock (10 plus faibles)")
    rot = kpi.stock_rotation(conn, start, end)
    rot_low = rot[rot["avg_close"] > 0].sort_values("rotation").head(10)
    if not rot_low.empty:
        st.plotly_chart(
            _compact_bar(rot_low, x="rotation", y="name", color="category"),
            use_container_width=True,
        )

    # --- Ruptures ---
    st.subheader("Jours en rupture par produit")
    sout = kpi.stockout_days_by_item(conn, start, end)
    sout_pos = sout[sout["zero_days"] > 0]
    if sout_pos.empty:
        st.success("Aucune rupture de stock sur la p\u00e9riode.")
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
            st.info("S\u00e9lectionne une p\u00e9riode valide.")
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

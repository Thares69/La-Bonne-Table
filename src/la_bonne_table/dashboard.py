"""Dashboard Streamlit V1 — La Bonne Table.

4 pages : Accueil (KPI + recommandations), Ventes (graphes), Stock (pertes + rotation),
Import (upload CSV + mode démo).
Aucune logique métier ici — tout est délégué à kpi.py et rules.py.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import plotly.express as px
import streamlit as st

from la_bonne_table import kpi, rules
from la_bonne_table.ai import provider as ai_provider
from la_bonne_table.ai import summary as ai_summary
from la_bonne_table.ai.context import build_context
from la_bonne_table.db import DB_PATH, connect, get_metadata, init_schema, set_metadata
from la_bonne_table.demo_data import generate_demo_csvs
from la_bonne_table.ingest import ingest_all, ingest_uploaded
from la_bonne_table.report import generate_html_report

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


def _is_demo(conn) -> bool:
    return get_metadata(conn, "dataset_type") == "demo"


def render_sidebar(conn):
    st.sidebar.markdown("### La Bonne Table")
    st.sidebar.caption("Tableau de bord restaurant")

    if _is_demo(conn):
        st.sidebar.info("**DEMO** — Donnees simulees")

    page = st.sidebar.radio(
        "Navigation",
        ["Accueil", "Ventes", "Stock", "Import"],
        label_visibility="collapsed",
    )

    if page == "Import":
        return page, None, None

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
# Synthese IA
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_summary(context_json: str) -> dict:
    """Cache key = serialisation JSON du contexte. Hit tant que les KPI sont identiques."""
    context = json.loads(context_json)
    result = ai_summary.generate_summary(context)
    return {"text": result.text, "is_ai": result.is_ai, "model": result.model}


def _render_ai_summary(conn, start, end):
    header_col, btn_col = st.columns([4, 1])
    with header_col:
        st.subheader("Synth\u00e8se IA")
    with btn_col:
        if st.button("Regenerer", key="ai_regen"):
            _cached_summary.clear()

    context = build_context(conn, start, end)
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)

    with st.spinner("Generation de la synthese..."):
        result = _cached_summary(context_json)

    if result["is_ai"]:
        st.caption(f"Generee par {result['model']}")
    elif ai_provider.is_available():
        st.warning("IA indisponible, synthese deterministe affichee.")
    else:
        st.caption("Mode deterministe (ANTHROPIC_API_KEY non configuree).")

    st.markdown(result["text"])


# ---------------------------------------------------------------------------
# Page : Accueil
# ---------------------------------------------------------------------------


def render_home(conn, start, end):
    col_title, col_export = st.columns([4, 1])
    with col_title:
        st.header("Vue d'ensemble")
        st.caption("Indicateurs cl\u00e9s et alertes sur la p\u00e9riode s\u00e9lectionn\u00e9e")
    with col_export:
        html = generate_html_report(conn, start, end)
        st.download_button(
            "Exporter HTML",
            data=html,
            file_name=f"rapport_{start}_{end}.html",
            mime="text/html",
        )

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

    # --- Synthese IA ---
    st.divider()
    _render_ai_summary(conn, start, end)

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
    st.plotly_chart(fig, width="stretch")

    # --- Top / Flop ---
    st.subheader("Classement des produits")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Meilleurs produits (CA)**")
        top = kpi.top_items_by_revenue(conn, n=5, start=start, end=end)
        st.plotly_chart(
            _bar_h(top, x="revenue", y="name", color="category"),
            width="stretch",
        )

    with col_right:
        st.markdown("**Moins performants (CA)**")
        flop = kpi.flop_items_by_revenue(conn, n=5, start=start, end=end)
        st.plotly_chart(
            _bar_h(flop, x="revenue", y="name", color="category"),
            width="stretch",
        )

    col_vol, col_margin = st.columns(2)
    with col_vol:
        st.markdown("**Les plus vendus (volume)**")
        vol = kpi.top_items_by_volume(conn, n=5, start=start, end=end)
        st.plotly_chart(
            _bar_h(vol, x="qty", y="name", color="category"),
            width="stretch",
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
        st.plotly_chart(fig, width="stretch")


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
        st.plotly_chart(fig, width="stretch")
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
                width="stretch",
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
                width="stretch",
                hide_index=True,
            )


# ---------------------------------------------------------------------------
# Page : Import
# ---------------------------------------------------------------------------


def _load_demo():
    """Generate demo CSVs to a temp dir and ingest them."""
    with tempfile.TemporaryDirectory() as tmp:
        generate_demo_csvs(Path(tmp))
        ingest_all(Path(tmp), DB_PATH)
    conn = connect()
    set_metadata(conn, "dataset_type", "demo")
    conn.close()


def _reset_db():
    """Delete the database file."""
    Path(DB_PATH).unlink(missing_ok=True)


def render_import():
    st.header("Import de donnees")
    st.caption("Charger un jeu de fichiers CSV ou lancer la demo")

    # --- Feedback from previous action ---
    if "import_counts" in st.session_state:
        counts = st.session_state.pop("import_counts")
        st.success("Import reussi !")
        cols = st.columns(len(counts))
        for col, (table, n) in zip(cols, counts.items(), strict=False):
            col.metric(table, f"{n} lignes")
        st.divider()

    if "demo_loaded" in st.session_state:
        st.session_state.pop("demo_loaded")
        st.success("Donnees de demonstration chargees. Va sur **Accueil** pour explorer.")
        st.divider()

    if "db_reset" in st.session_state:
        st.session_state.pop("db_reset")
        st.success("Base reinitialisee.")
        st.divider()

    # --- Demo + Reset ---
    col_demo, col_reset = st.columns(2)
    with col_demo:
        st.markdown("**Mode demo**")
        st.caption("Charge 90 jours de donnees simulees avec des signaux plantes.")
        if st.button("Charger la demo", type="primary"):
            with st.spinner("Generation et import..."):
                _load_demo()
            st.session_state["demo_loaded"] = True
            st.rerun()

    with col_reset:
        st.markdown("**Reinitialiser**")
        st.caption("Supprime toutes les donnees pour repartir de zero.")
        if st.button("Reinitialiser la base"):
            _reset_db()
            st.session_state["db_reset"] = True
            st.rerun()

    # --- Help ---
    with st.expander("Parcours de demo"):
        st.markdown(
            "1. Clique sur **Charger la demo** ci-dessus\n"
            "2. Va sur **Accueil** : 6 KPI + recommandations\n"
            "3. Va sur **Ventes** : courbe CA, top/flop, marges\n"
            "4. Va sur **Stock** : pertes, rotation, ruptures\n"
            "5. Reviens sur **Accueil** et clique **Exporter HTML**\n"
            "\n"
            "Signaux plantes dans la demo :\n"
            "- Poisson du jour : pertes ~20% (alerte critique)\n"
            "- Tajine agneau : ventes en baisse -36%\n"
            "- Pizza margherita : marge faible ~25%\n"
            "- Mardis : CA a 40% de la moyenne (jour creux)\n"
        )

    st.divider()

    # --- Manual CSV upload ---
    st.subheader("Import manuel")
    st.warning("L'import remplace integralement les donnees existantes.")

    col1, col2 = st.columns(2)
    with col1:
        items_file = st.file_uploader("items.csv", type="csv", key="up_items")
        sales_file = st.file_uploader("sales.csv", type="csv", key="up_sales")
    with col2:
        stock_file = st.file_uploader("stock.csv", type="csv", key="up_stock")
        calendar_file = st.file_uploader(
            "calendar.csv (optionnel)", type="csv", key="up_calendar",
        )

    required = {"items": items_file, "sales": sales_file, "stock": stock_file}
    missing = [name for name, f in required.items() if f is None]

    if missing:
        st.info(
            "Fichiers manquants : "
            + ", ".join(f"**{m}.csv**" for m in missing)
        )
        return

    if st.button("Lancer l'import", type="primary", key="btn_import"):
        files: dict = {k: v for k, v in required.items()}
        if calendar_file:
            files["calendar"] = calendar_file

        try:
            conn = connect()
            init_schema(conn)
            counts = ingest_uploaded(conn, files)
            conn.close()
            st.session_state["import_counts"] = counts
            st.rerun()
        except (ValueError, FileNotFoundError) as e:
            st.error(f"Erreur d'import : {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    conn = _open_conn()

    if conn is None:
        st.sidebar.markdown("### La Bonne Table")
        st.sidebar.caption("Tableau de bord restaurant")
        st.sidebar.radio(
            "Navigation", ["Import"], label_visibility="collapsed",
        )
        st.sidebar.caption("Aucune base detectee. Charge la demo ou importe tes CSV.")
        render_import()
        return

    try:
        page, start, end = render_sidebar(conn)

        if page == "Import":
            render_import()
            return

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

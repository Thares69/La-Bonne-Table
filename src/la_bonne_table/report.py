"""HTML report generation — La Bonne Table.

Pure function that builds a self-contained HTML string from KPI data.
No Streamlit dependency — reuses kpi.py and rules.py only.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from la_bonne_table import kpi, rules

PRIORITY_ICONS = {1: "!!!", 2: "!!", 3: "!", 4: "i"}


def generate_html_report(
    conn: sqlite3.Connection,
    start: str,
    end: str,
) -> str:
    """Build a self-contained HTML report for the given period."""
    # --- Gather data ---
    rev = kpi.revenue_total(conn, start, end)
    n_tickets = kpi.ticket_count(conn, start, end)
    avg = kpi.average_ticket(conn, start, end)
    gm = kpi.global_gross_margin(conn, start, end)
    waste = kpi.waste_rate_global(conn, start, end)
    days = kpi.open_closed_days(conn, start, end)
    top = kpi.top_items_by_revenue(conn, n=10, start=start, end=end)
    margin_df = kpi.gross_margin_by_item(conn, start, end)
    waste_df = kpi.waste_rate_by_item(conn, start, end)
    recos = rules.run_all_rules(conn, end=end)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- KPI cards ---
    kpi_rows = [
        ("Chiffre d'affaires", f"{rev:,.0f} \u20ac"),
        ("Nombre de tickets", f"{n_tickets:,}"),
        ("Panier moyen", f"{avg:,.2f} \u20ac"),
        ("Marge brute", f"{gm['margin_rate']:.1%}"),
        ("Taux de pertes", f"{waste['waste_rate']:.1%}"),
        ("Jours ouverts", f"{days['open']} / {days['total']}"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><span class="kpi-label">{label}</span>'
        f'<span class="kpi-value">{value}</span></div>'
        for label, value in kpi_rows
    )

    # --- Recommendations ---
    if recos:
        reco_rows = "".join(
            f"<tr><td>{PRIORITY_ICONS.get(r.priority, '')}</td>"
            f"<td>{rules.PRIORITY_LABELS.get(r.priority, '')}</td>"
            f"<td>{_esc(r.message)}</td></tr>"
            for r in recos
        )
        reco_html = (
            "<h2>Recommandations</h2>"
            '<table><thead><tr><th></th><th>Priorit\u00e9</th>'
            "<th>Message</th></tr></thead>"
            f"<tbody>{reco_rows}</tbody></table>"
        )
    else:
        reco_html = "<h2>Recommandations</h2><p>Aucune alerte.</p>"

    # --- Top products table ---
    top_rows = "".join(
        f"<tr><td>{_esc(str(row['name']))}</td>"
        f"<td>{row['category']}</td>"
        f"<td>{row['qty']}</td>"
        f"<td>{row['revenue']:,.0f} \u20ac</td></tr>"
        for _, row in top.iterrows()
    )
    top_html = (
        "<h2>Top produits (CA)</h2>"
        "<table><thead><tr><th>Produit</th><th>Cat\u00e9gorie</th>"
        "<th>Qt\u00e9</th><th>CA</th></tr></thead>"
        f"<tbody>{top_rows}</tbody></table>"
    )

    # --- Margin table ---
    margin_df = margin_df.copy()
    margin_df["margin_pct"] = (margin_df["margin_rate"] * 100).round(1)
    margin_rows = ""
    for _, row in margin_df.iterrows():
        cls = ' class="warn"' if row["margin_pct"] < 30 else ""
        margin_rows += (
            f"<tr><td>{_esc(str(row['name']))}</td>"
            f"<td>{row['category']}</td>"
            f"<td>{row['margin_pct']:.1f}%</td>"
            f"<td{cls}>{row['gross_margin']:,.0f} \u20ac</td></tr>"
        )
    margin_html = (
        "<h2>Marge brute par produit</h2>"
        "<table><thead><tr><th>Produit</th><th>Cat\u00e9gorie</th>"
        "<th>Marge %</th><th>Marge brute</th></tr></thead>"
        f"<tbody>{margin_rows}</tbody></table>"
    )

    # --- Waste table (only items with waste > 0) ---
    waste_pos = waste_df[waste_df["waste_rate"] > 0].sort_values(
        "waste_rate", ascending=False,
    )
    if not waste_pos.empty:
        waste_rows = "".join(
            f"<tr><td>{_esc(str(row['name']))}</td>"
            f"<td>{row['waste']}</td>"
            f"<td>{row['waste_rate']:.1%}</td></tr>"
            for _, row in waste_pos.iterrows()
        )
        waste_html = (
            "<h2>Pertes par produit</h2>"
            "<table><thead><tr><th>Produit</th><th>Unit\u00e9s perdues</th>"
            "<th>Taux</th></tr></thead>"
            f"<tbody>{waste_rows}</tbody></table>"
        )
    else:
        waste_html = "<h2>Pertes</h2><p>Aucune perte sur la p\u00e9riode.</p>"

    return _TEMPLATE.format(
        start=start,
        end=end,
        now=now,
        kpi_html=kpi_html,
        reco_html=reco_html,
        top_html=top_html,
        margin_html=margin_html,
        waste_html=waste_html,
    )


def _esc(text: str) -> str:
    """Minimal HTML escaping."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>La Bonne Table — Rapport {start} / {end}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
         sans-serif; max-width: 900px; margin: 2rem auto; color: #222;
         line-height: 1.5; }}
  h1 {{ border-bottom: 2px solid #2196F3; padding-bottom: .3rem; }}
  h2 {{ color: #2196F3; margin-top: 2rem; }}
  .meta {{ color: #888; font-size: .85rem; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(3, 1fr);
               gap: 1rem; margin: 1.5rem 0; }}
  .kpi {{ background: #f8f9fa; border-radius: 8px; padding: 1rem;
          text-align: center; }}
  .kpi-label {{ display: block; font-size: .8rem; color: #666;
                text-transform: uppercase; letter-spacing: .05em; }}
  .kpi-value {{ display: block; font-size: 1.4rem; font-weight: 700;
                margin-top: .3rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: .8rem 0; }}
  th, td {{ text-align: left; padding: .45rem .6rem;
            border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #f5f5f5; font-size: .8rem; text-transform: uppercase;
       letter-spacing: .04em; }}
  .warn {{ color: #c62828; font-weight: 600; }}
  @media print {{ body {{ margin: 0; }} }}
</style>
</head>
<body>
<h1>La Bonne Table</h1>
<p class="meta">P\u00e9riode : {start} \u2192 {end} &mdash; g\u00e9n\u00e9r\u00e9 le {now}</p>

<div class="kpi-grid">
{kpi_html}
</div>

{reco_html}

{top_html}

{margin_html}

{waste_html}

</body>
</html>
"""

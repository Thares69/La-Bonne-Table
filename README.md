# La Bonne Table

MVP data-analytics pour restaurant indépendant.

Pipeline : **CSV → SQLite → KPI → recommandations → dashboard Streamlit**.

## Stack

Python 3.11, pandas, sqlite3 (natif), Streamlit, Plotly, pytest, ruff, uv.

## Quickstart

```bash
# 1. installer les dépendances
uv sync --extra dev

# 2. générer les données simulées (90 jours, 1 restaurant fictif)
uv run python scripts/seed_data.py

# 3. ingestion CSV -> SQLite (à venir S2)
# uv run python -m la_bonne_table.ingest

# 4. lancer le dashboard
uv run streamlit run src/la_bonne_table/dashboard.py
```

## Structure

```
la-bonne-table/
├── data/
│   ├── raw/                # CSV sources (générés ou uploadés)
│   └── la_bonne_table.db   # SQLite (gitignored)
├── scripts/
│   └── seed_data.py        # génération données simulées
├── src/la_bonne_table/
│   ├── db.py               # connexion + schéma SQLite
│   ├── ingest.py           # CSV -> DB
│   ├── kpi.py              # calcul des KPI
│   ├── rules.py            # moteur de recommandations
│   └── dashboard.py        # UI Streamlit
└── tests/
```

## Roadmap

- **S1** socle projet + données simulées
- **S2** ingestion CSV + SQLite
- **S3** KPI (CA, panier moyen, top/flop, marge, waste, rotation)
- **S4** moteur de règles (5 règles)
- **S5** dashboard Streamlit
- **S6** polish + export

Voir `CLAUDE.md` pour les règles de dev et le backlog V2.

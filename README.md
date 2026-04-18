# La Bonne Table

MVP data-analytics pour restaurant independant.

Pipeline : **CSV -> SQLite -> KPI -> recommandations -> dashboard Streamlit -> export HTML**.

## Demo en ligne

**[la-bonne-table-b757dsscm7njhpibw6wd.streamlit.app](https://la-bonne-table-b757dsscm7njhpibw6wd.streamlit.app)**

Hebergee sur Streamlit Community Cloud. A l'ouverture, cliquer **Charger la demo** dans la sidebar pour generer le dataset simule (90 jours, 25 produits, signaux plantes). La base est ephemere — chaque redeploy ou mise en veille la reinitialise.

## Stack

Python 3.11+, pandas, sqlite3 (natif), Streamlit, Plotly, pytest, ruff, uv.

## Quickstart

```bash
# 1. Installer les dependances
uv sync --extra dev

# 2. Generer les donnees simulees (90 jours, 25 produits, 1 restaurant fictif)
uv run python scripts/seed_data.py

# 3. Ingerer les CSV dans SQLite
uv run python -m la_bonne_table.ingest

# 4. Lancer le dashboard
uv run streamlit run src/la_bonne_table/dashboard.py
```

Le dashboard est accessible sur `http://localhost:8501`.

## Mode demo

Le seed genere un jeu de donnees realiste avec des signaux plantes :

- **P107 (Poisson du jour)** : taux de pertes eleve (~20%) → regle `excessive_waste`
- **P106 (Tajine agneau)** : ventes en baisse (-36%) → regle `declining_item`
- **P108 (Pizza margherita)** : marge faible (~25%, seuil a 30%) → regle `low_margin`
- **Mardis** : CA a ~40% de la moyenne → regle `slow_weekday`
- **Lundis** : fermes (visible dans le calendrier)

Les 4 signaux plantes + 1 pattern naturel (Burger classique en baisse) declenchent 5 recommandations au total.

Pour verifier en CLI avant le dashboard :

```bash
uv run python scripts/show_kpi.py     # affiche les KPI principaux
uv run python scripts/show_rules.py   # affiche les recommandations
```

## Flux complet

```
                    +------------------+
                    |  CSV (4 fichiers)|
                    | items, sales,    |
                    | stock, calendar  |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
     CLI: python -m              Dashboard: page Import
     la_bonne_table.ingest       (upload via navigateur)
              |                             |
              +--------------+--------------+
                             |
                    +--------v---------+
                    |     SQLite       |
                    | la_bonne_table.db|
                    +--------+---------+
                             |
                    +--------v---------+
                    |   kpi.py         |
                    | 13 KPI calcules  |
                    +--------+---------+
                             |
                    +--------v---------+
                    |   rules.py       |
                    | 5 regles metier  |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
     +--------v---------+         +--------v---------+
     |    Dashboard      |         |   Export HTML    |
     | 4 pages Streamlit |         | rapport autonome |
     +-------------------+         +------------------+
```

### Format des CSV

| Fichier | Colonnes requises |
|---|---|
| `items.csv` | `item_id, name, category, unit_cost, sell_price` |
| `sales.csv` | `date, ticket_id, item_id, quantity, unit_price, total` |
| `stock.csv` | `date, item_id, qty_open, qty_received, qty_close, waste` |
| `calendar.csv` | `date, is_open, notes` |

Dates au format `YYYY-MM-DD`. `calendar.csv` est optionnel a l'upload (requis pour la detection des jours creux).

### Pages du dashboard

| Page | Contenu |
|---|---|
| **Accueil** | 6 KPI, comparaison 30j, recommandations groupees par priorite, bouton export HTML |
| **Ventes** | CA journalier, top/flop 5 produits, volume, marge brute par produit |
| **Stock** | Taux de pertes, pertes par produit, rotation des stocks, ruptures |
| **Import** | Upload CSV depuis le navigateur, validation, ingestion vers SQLite |

### Export HTML

Depuis la page Accueil, le bouton **Exporter HTML** genere un rapport autonome (CSS inline, pas de dependance externe) contenant :

- KPI principaux
- Recommandations avec priorite
- Top 10 produits par CA
- Marge brute par produit (alerte visuelle sous 30%)
- Pertes par produit

Le fichier est ouvrable dans n'importe quel navigateur et imprimable en PDF.

## Deploiement (Streamlit Community Cloud)

App live : [la-bonne-table-b757dsscm7njhpibw6wd.streamlit.app](https://la-bonne-table-b757dsscm7njhpibw6wd.streamlit.app)

Pour reproduire le deploiement :

1. Pousser le repo sur GitHub (public ou prive).
2. Aller sur [share.streamlit.io](https://share.streamlit.io) et se connecter avec GitHub.
3. **New app** -> selectionner le repo + la branche `main`.
4. **Main file path** : `src/la_bonne_table/dashboard.py`
5. **Deploy**. Streamlit Cloud installe `requirements.txt` automatiquement (Python fixe a 3.11 via `runtime.txt`).

A l'ouverture, la base est vide : cliquer **Charger la demo** dans la sidebar pour generer les donnees simulees. Les uploads CSV fonctionnent aussi. La base SQLite est ephemere (reset a chaque redeploy ou apres mise en veille) — c'est voulu pour une demo.

## Structure

```
la-bonne-table/
├── data/
│   ├── raw/                    # CSV sources (generes ou uploades)
│   └── la_bonne_table.db      # SQLite (gitignored)
├── scripts/
│   ├── seed_data.py            # generation donnees simulees
│   ├── show_kpi.py             # verification KPI en CLI
│   └── show_rules.py           # verification regles en CLI
├── src/la_bonne_table/
│   ├── db.py                   # connexion + schema SQLite
│   ├── ingest.py               # CSV -> DB (CLI + upload)
│   ├── kpi.py                  # 13 KPI (fonctions pures sur sqlite3)
│   ├── rules.py                # 5 regles metier -> recommandations
│   ├── report.py               # generation rapport HTML
│   └── dashboard.py            # UI Streamlit (4 pages)
└── tests/
    ├── conftest.py             # fixture tmp_db
    ├── test_ingest.py          # 15 tests ingestion
    ├── test_kpi.py             # 19 tests KPI
    ├── test_rules.py           # 13 tests regles
    └── test_report.py          # 6 tests export
```

## Developpement

```bash
uv run pytest                  # 53 tests
uv run ruff check .            # lint
uv run ruff check --fix .      # lint + autofix
```

## Sessions realisees

| Session | Contenu |
|---|---|
| S1 | Socle projet, schema SQLite, seed data |
| S2 | Ingestion CSV -> SQLite avec validation |
| S3 | 13 KPI (CA, panier moyen, marge, pertes, rotation, comparaison 30j) |
| S4 | Moteur de regles (5 regles, 4 niveaux de priorite) |
| S5 | Dashboard Streamlit (3 pages) |
| S6 | Polish UX dashboard |
| S7 | Upload CSV depuis le dashboard |
| S8 | Export rapport HTML, nettoyage deprecations Streamlit |

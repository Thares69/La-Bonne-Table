# La Bonne Table — CLAUDE.md

## Contexte
MVP data-analytics pour restaurant indépendant. Pipeline CSV → SQLite → KPI → recommandations → Streamlit.
Pas d'agents IA, pas de LLM, pas d'ORM en V1. Simplicité > élégance.

## Stack figée V1
Python 3.11, pandas, sqlite3 (natif, pas d'ORM), Streamlit, Plotly, pytest, ruff, uv.

Aucune dépendance supplémentaire sans justification explicite.

## Conventions
- Code, identifiants et commits en **anglais**. Discussions et docs utilisateur en **français**.
- Package : `la_bonne_table`. Repo : `la-bonne-table`. DB : `la_bonne_table.db`.
- CSV de référence : `date,ticket_id,item_id,quantity,unit_price,total` pour `sales.csv`.
- Dates au format ISO `YYYY-MM-DD` partout (string côté CSV/SQLite, `pd.Timestamp` côté pandas).

## Règles de dev
- Tests obligatoires pour `ingest.py`, `kpi.py`, `rules.py`. Dashboard non testé.
- Chaque règle métier = fonction pure dans `rules.py`, testée en isolation avec fixture déterministe.
- Fonctions SQL via `sqlite3` + `row_factory = sqlite3.Row`. Pas de requêtes construites par concat de strings — uniquement paramètres `?`.
- Pandas pour les agrégations complexes, SQL pour les lectures simples.
- `data/raw/*.csv` et `data/*.db` sont gitignored. Seul le code est versionné.

## Commandes
```bash
uv sync --extra dev
uv run python scripts/seed_data.py
uv run streamlit run src/la_bonne_table/dashboard.py
uv run pytest
uv run ruff check --fix .
```

## KPI V1
CA (jour/semaine/période), panier moyen (via `ticket_id`), top/flop 5 plats, marge brute par plat, taux de perte, rotation stock.

## Règles V1
1. Plat en chute (≥ -20% semaine N vs N-1, priorité 2).
2. Waste excessif (> 15%, priorité 1).
3. Marge faible (< 30% sur plat vendu > 50x/mois, priorité 2).
4. Rupture fréquente (`qty_close = 0` > 5 jours/mois, priorité 1).
5. Jour creux (CA jour < 60% moyenne, exclure jours fermés via `calendar.csv`, priorité 3).

## Hors MVP (V2+, NE PAS commencer avant démo MVP)
Agents IA, LangGraph, CrewAI, LLM, FastAPI, auth, multi-tenant, vectorstore, POS temps réel, Docker, CI/CD, déploiement cloud.

## Décisions figées
- `ticket_id` dans `sales.csv` pour permettre le panier moyen.
- `calendar.csv` explicite pour distinguer jour fermé vs jour à 0 vente.
- sqlite3 natif — pas de SQLModel/SQLAlchemy tant que les requêtes restent < 30 lignes.

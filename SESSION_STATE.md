# La Bonne Table — Etat du projet

## Statut global

**MVP complet, montrable et deploye en production.**

App live : [la-bonne-table-b757dsscm7njhpibw6wd.streamlit.app](https://la-bonne-table-b757dsscm7njhpibw6wd.streamlit.app)

## Sessions realisees

| Session | Contenu | Statut |
|---|---|---|
| S1 | Socle projet, schema SQLite, seed data (90j, 25 produits) | Done |
| S2 | Ingestion CSV -> SQLite, validation, idempotence | Done |
| S3 | 13 KPI (CA, panier moyen, marge, pertes, rotation, comparaison 30j) | Done |
| S4 | Moteur de regles (5 regles, 4 niveaux de priorite) | Done |
| S5 | Dashboard Streamlit (3 pages : Accueil, Ventes, Stock) | Done |
| S6 | Polish UX dashboard (couleurs, labels, layout) | Done |
| S7 | Upload CSV depuis le dashboard (page Import) | Done |
| S8 | Export rapport HTML, nettoyage deprecations Streamlit | Done |
| S9 | README, documentation, mode demo integre | Done |
| S10 | Deploiement Streamlit Cloud (requirements, demo_data module, runtime.txt) | Done |

## Deploiement

- **Plateforme** : Streamlit Community Cloud (gratuit)
- **Entrypoint** : `src/la_bonne_table/dashboard.py`
- **Runtime** : Python 3.11 (`runtime.txt`)
- **Dependances prod** : `requirements.txt` (pandas, numpy, streamlit, plotly)
- **Verifications post-deploy** : app accessible, mode demo fonctionnel, KPI + recommandations + bandeau DEMO visibles, 4 pages navigables.

## Repo

- **Branche** : main
- **Remote** : `github.com/Thares69/La-Bonne-Table`
- **Tests** : 57 (ingest 15, kpi 19, rules 13, report 6, demo_data 2, autres)
- **Lint** : ruff clean

## Modules

| Module | Role | Tests |
|---|---|---|
| `db.py` | Connexion SQLite, schema 5 tables | via conftest |
| `ingest.py` | CSV -> DB (CLI + file-like pour upload) | 15 |
| `kpi.py` | 13 KPI, fonctions pures sur sqlite3 | 19 |
| `rules.py` | 5 regles metier -> recommandations | 13 |
| `report.py` | Generation rapport HTML autonome | 6 |
| `dashboard.py` | UI Streamlit 4 pages | non teste (MVP) |

## Donnees de demo

Dataset seed (SEED=42) : 90 jours, 2026-01-15 -> 2026-04-14, 25 produits.

Signaux plantes et recommandations generees :

| Signal | Produit | Regle declenchee | Priorite |
|---|---|---|---|
| Pertes ~20% | P107 Poisson du jour | `excessive_waste` | 1 (critique) |
| Ventes -36% | P106 Tajine agneau | `declining_item` | 2 (elevee) |
| Ventes -20% | P101 Burger classique | `declining_item` | 2 (elevee) |
| Marge ~25% | P108 Pizza margherita | `low_margin` | 2 (elevee) |
| CA mardi 40% moy | — | `slow_weekday` | 4 (info) |

KPI cles : CA 81 281 EUR, 2 868 tickets, panier moyen 28.34 EUR, marge 71.5%, pertes 3.3%.

## Reporte (V2+)

- Auth / multi-tenant
- Agents IA / LLM
- FastAPI / API REST
- Docker / CI/CD / deploiement cloud
- Export PDF natif
- Import POS temps reel

## Scenario de demo

Voir section dediee dans ce fichier :

### Preparation

```bash
uv sync --extra dev
uv run python scripts/seed_data.py
uv run python -m la_bonne_table.ingest
uv run streamlit run src/la_bonne_table/dashboard.py
```

### Deroulement (5-7 min)

**1. Accueil — vue d'ensemble** (~1 min)
- Montrer les 6 KPI : CA, tickets, panier moyen, marge, pertes, jours ouverts
- Pointer le delta -13.5% sur le CA (comparaison 30j)
- Parcourir les recommandations : 1 critique, 3 elevees, 1 info

**2. Ventes — analyse detaillee** (~1.5 min)
- Courbe CA journalier : pointer la saisonnalite et les creux du mardi
- Top/flop 5 : Burger classique en tete, Plat vegetarien en queue
- Marge par produit : montrer Pizza margherita sous le seuil rouge (25%)

**3. Stock — gestion des pertes** (~1.5 min)
- KPI pertes globales : 3.3%
- Barre de pertes par produit : Poisson du jour a 20% (au-dessus du seuil)
- Rotation : Plat vegetarien stagne (rotation = 11)
- Ruptures : tableau des produits ayant ete a zero

**4. Export HTML** (~30 sec)
- Depuis Accueil, cliquer "Exporter HTML"
- Ouvrir le fichier dans un navigateur : rapport complet, imprimable

**5. Import CSV** (~1.5 min)
- Naviguer vers la page Import
- Charger les 4 fichiers CSV (ou 3, montrer que calendar est optionnel)
- Lancer l'import : montrer le feedback (lignes chargees par table)
- Revenir sur Accueil : les KPI sont recalcules

### Captures d'ecran recommandees

1. **Accueil complet** : les 6 KPI + la section recommandations depliee
2. **Recommandation critique** : zoom sur l'alerte Poisson du jour (waste 20%)
3. **Ventes — marge** : graphe horizontal avec le seuil rouge a 30%
4. **Stock — pertes** : graphe avec Poisson du jour au-dessus du seuil 15%
5. **Import** : les 4 uploaders remplis + bouton actif
6. **Export HTML** : le rapport ouvert dans un navigateur
7. **CLI** : sortie de `show_rules.py` (montre que le moteur tourne aussi sans dashboard)

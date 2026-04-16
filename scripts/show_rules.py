"""Exécute les règles sur la base ingérée et imprime les recommandations.

Usage : ``uv run python scripts/show_rules.py``

Persiste également les recommandations dans la table `recommendations`.
"""
from __future__ import annotations

from la_bonne_table import rules
from la_bonne_table.db import connect


def main() -> None:
    conn = connect()
    recos = rules.run_all_rules(conn)
    n = rules.save_recommendations(conn, recos)

    print(f"{n} recommandation(s) générée(s)\n")
    for r in recos:
        label = rules.PRIORITY_LABELS[r.priority].upper()
        tag = f"[{r.priority} {label:8s} | {r.type:18s}]"
        print(f"{tag} {r.message}")

    conn.close()


if __name__ == "__main__":
    main()

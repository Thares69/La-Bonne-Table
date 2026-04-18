"""Couche IA de La Bonne Table.

Greffe non intrusive sur le moteur deterministe : les KPI et regles restent
la source de verite, l'IA se contente d'expliquer, synthetiser et prioriser.
"""
from la_bonne_table.ai.summary import SummaryResult, generate_summary

__all__ = ["SummaryResult", "generate_summary"]

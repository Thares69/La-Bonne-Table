"""Synthese dirigeant : LLM si dispo, fallback deterministe sinon.

Sections fixes (titres markdown exacts) :
    ## Resume
    ## Alertes prioritaires
    ## Opportunites
    ## Plan d'action
    ## Limites
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from la_bonne_table.ai import provider

SYSTEM_PROMPT = """Tu es un copilote data pour un restaurant independant.
Tu recois un contexte JSON avec des KPI et des recommandations deja calculees
par un moteur deterministe.

REGLES ABSOLUES :
- Utilise EXCLUSIVEMENT les chiffres fournis dans le contexte. Zero invention.
- Si un chiffre n'est pas dans le contexte, ne l'evoque pas.
- Ton factuel, concis, oriente decision. Aucun remplissage.
- Reponds en francais.

STRUCTURE DE REPONSE (markdown, respecte les titres exacts et l'ordre) :

## Resume
2-3 phrases. Reprend les chiffres cles de la periode (CA, tickets, marge, pertes).

## Alertes prioritaires
Bullets (- ...). Reprend les recommandations priorite 1 et 2. Si aucune,
ecris "Aucune alerte critique sur la periode."

## Opportunites
Bullets. Signaux priorite 3-4 et patterns top/flop interessants.

## Plan d'action
3 a 5 actions concretes, ordonnees par impact. Chaque action cite le produit,
le jour ou le KPI concerne avec le chiffre du contexte.

## Limites
Bullets courts. Ex : periode limitee, donnees fournisseurs absentes, dataset demo, etc.
"""


@dataclass
class SummaryResult:
    text: str
    is_ai: bool
    model: str | None = None


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "n/d"
    return f"{x * 100:+.1f}%".replace("+-", "-")


def _fallback_summary(context: dict[str, Any]) -> str:
    """Template deterministe : reprend les KPI et recos sans LLM."""
    p = context["period"]
    r = context["revenue"]
    h = context["health"]
    recos = context["recommendations"]
    top = context["top_items"]
    flop = context["flop_items"]

    crit = [x for x in recos if x["priority"] == 1]
    high = [x for x in recos if x["priority"] == 2]
    info = [x for x in recos if x["priority"] >= 3]

    delta_line = ""
    cmp = r["comparison_30d"]
    if cmp and cmp["delta_pct"] is not None:
        delta_line = f" (tendance {_fmt_pct(cmp['delta_pct'])} vs 30j precedents)"

    resume = (
        f"Sur la periode du {p['start']} au {p['end']} "
        f"({p['days_open']}/{p['days_total']} jours ouverts), "
        f"le CA ressort a {r['total']:,.0f} EUR sur {r['tickets']:,} tickets "
        f"(panier moyen {r['average_ticket']:.2f} EUR){delta_line}. "
        f"Marge brute {h['gross_margin_rate'] * 100:.1f}%, "
        f"pertes {h['waste_rate'] * 100:.1f}%."
    ).replace(",", " ")

    def _bullets(items: list[dict]) -> str:
        if not items:
            return "- Aucun signal sur la periode."
        return "\n".join(f"- {x['message']}" for x in items)

    alertes_body = (
        _bullets(crit + high) if (crit or high)
        else "Aucune alerte critique sur la periode."
    )
    opportunites_body = (
        _bullets(info) if info else "- Aucun signal secondaire detecte."
    )

    plan: list[str] = []
    for reco in (crit + high + info)[:5]:
        plan.append(f"- {reco['message']}")
    if not plan and top:
        plan.append(
            f"- Capitaliser sur {top[0]['name']} "
            f"(meilleure contribution CA : {top[0]['revenue']:,.0f} EUR).".replace(",", " ")
        )
    if not plan:
        plan.append("- Pas d'action prioritaire identifiee sur la periode.")

    limites = [
        "- Synthese generee sans IA (cle ANTHROPIC_API_KEY non configuree).",
        f"- Dataset : {context['dataset_type']}.",
        f"- Periode analysee : {p['days_total']} jours.",
    ]
    if flop:
        limites.append(
            "- Les produits en queue de classement ne sont pas forcement problematiques "
            "(depend de la strategie carte)."
        )

    return (
        "## Resume\n"
        f"{resume}\n\n"
        "## Alertes prioritaires\n"
        f"{alertes_body}\n\n"
        "## Opportunites\n"
        f"{opportunites_body}\n\n"
        "## Plan d'action\n"
        + "\n".join(plan)
        + "\n\n"
        "## Limites\n"
        + "\n".join(limites)
    )


def _build_user_prompt(context: dict[str, Any]) -> str:
    ctx_json = json.dumps(context, ensure_ascii=False, indent=2)
    return (
        "Voici le contexte structure de la periode analysee. "
        "Utilise uniquement ces chiffres pour produire la synthese.\n\n"
        "```json\n"
        + ctx_json
        + "\n```"
    )


def generate_summary(context: dict[str, Any]) -> SummaryResult:
    """Retourne une synthese : LLM si dispo, fallback deterministe sinon."""
    if not provider.is_available():
        return SummaryResult(text=_fallback_summary(context), is_ai=False, model=None)

    try:
        resp = provider.call_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(context),
        )
    except Exception as e:  # noqa: BLE001
        # Fallback robuste : on annote le texte pour que l'UI puisse signaler.
        text = _fallback_summary(context) + f"\n\n> Note : appel IA echoue ({type(e).__name__})."
        return SummaryResult(text=text, is_ai=False, model=None)

    return SummaryResult(text=resp.text, is_ai=True, model=resp.model)

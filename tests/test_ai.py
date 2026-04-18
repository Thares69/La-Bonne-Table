from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from la_bonne_table.ai import provider, summary
from la_bonne_table.ai.context import build_context


@pytest.fixture
def populated_db(tmp_db: sqlite3.Connection) -> sqlite3.Connection:
    tmp_db.executemany(
        "INSERT INTO items (item_id, name, category, unit_cost, sell_price) VALUES (?,?,?,?,?)",
        [
            ("A", "Item A", "plat", 4.0, 10.0),
            ("B", "Item B", "plat", 7.0, 10.0),
        ],
    )
    tmp_db.executemany(
        "INSERT INTO calendar (date, is_open, notes) VALUES (?,?,?)",
        [
            ("2026-01-01", 1, ""),
            ("2026-01-02", 0, "ferme"),
            ("2026-01-03", 1, ""),
        ],
    )
    tmp_db.executemany(
        "INSERT INTO sales (date, ticket_id, item_id, quantity, unit_price, total) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("2026-01-01", "T1", "A", 2, 10.0, 20.0),
            ("2026-01-01", "T1", "B", 1, 10.0, 10.0),
            ("2026-01-01", "T2", "A", 1, 10.0, 10.0),
            ("2026-01-03", "T3", "B", 3, 10.0, 30.0),
        ],
    )
    tmp_db.executemany(
        "INSERT INTO stock (date, item_id, qty_open, qty_received, qty_close, waste) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("2026-01-01", "A", 10, 5, 11, 1),
            ("2026-01-01", "B", 8, 0, 7, 0),
            ("2026-01-03", "A", 11, 0, 11, 0),
            ("2026-01-03", "B", 7, 5, 9, 0),
        ],
    )
    tmp_db.commit()
    return tmp_db


# ---------------------------------------------------------------------------
# context.build_context
# ---------------------------------------------------------------------------


def test_build_context_shape(populated_db):
    ctx = build_context(populated_db, "2026-01-01", "2026-01-03")

    assert set(ctx.keys()) == {
        "period", "revenue", "health", "top_items", "flop_items",
        "recommendations", "dataset_type",
    }
    assert ctx["period"]["start"] == "2026-01-01"
    assert ctx["period"]["end"] == "2026-01-03"
    assert ctx["revenue"]["total"] == 70.0
    assert ctx["revenue"]["tickets"] == 3
    assert ctx["revenue"]["average_ticket"] == pytest.approx(70.0 / 3, rel=1e-3)


def test_build_context_values_are_json_safe(populated_db):
    """Aucune valeur DataFrame / Row — tout est natif serialisable."""
    import json

    ctx = build_context(populated_db, "2026-01-01", "2026-01-03")
    # Si un type non-serialisable trainait, json.dumps echouerait.
    serialized = json.dumps(ctx)
    assert isinstance(serialized, str) and len(serialized) > 0


def test_build_context_dataset_type_default(populated_db):
    """Sans metadata explicite, dataset_type vaut 'unknown'."""
    ctx = build_context(populated_db, "2026-01-01", "2026-01-03")
    assert ctx["dataset_type"] == "unknown"


def test_build_context_reads_dataset_type_metadata(populated_db):
    from la_bonne_table.db import set_metadata

    set_metadata(populated_db, "dataset_type", "demo")
    ctx = build_context(populated_db, "2026-01-01", "2026-01-03")
    assert ctx["dataset_type"] == "demo"


# ---------------------------------------------------------------------------
# summary — fallback deterministe
# ---------------------------------------------------------------------------

FAKE_CONTEXT = {
    "period": {
        "start": "2026-01-01", "end": "2026-01-31",
        "days_open": 25, "days_closed": 6, "days_total": 31,
    },
    "revenue": {
        "total": 50000.0, "tickets": 1500, "average_ticket": 33.33,
        "comparison_30d": {
            "window_days": 30,
            "current_revenue": 50000.0,
            "previous_revenue": 55000.0,
            "delta_pct": -0.09,
        },
    },
    "health": {
        "gross_margin_rate": 0.71,
        "waste_rate": 0.033,
        "waste_units": 50,
        "available_units": 1500,
    },
    "top_items": [
        {"name": "Burger", "category": "plat", "revenue": 8000.0},
    ],
    "flop_items": [
        {"name": "Salade", "category": "entree", "revenue": 200.0},
    ],
    "recommendations": [
        {
            "type": "excessive_waste",
            "priority": 1,
            "message": "Waste eleve sur Poisson : 20%.",
            "metric_value": 0.20,
            "item_id": "P107",
            "priority_label": "critique",
        },
        {
            "type": "slow_weekday",
            "priority": 4,
            "message": "Mardi : CA a 55% de la moyenne.",
            "metric_value": 0.55,
            "item_id": None,
            "priority_label": "info",
        },
    ],
    "dataset_type": "demo",
}


def test_fallback_has_all_required_sections():
    """Sans cle API, la synthese retourne toutes les sections markdown attendues."""
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(provider, "get_api_key", return_value=None),
    ):
        result = summary.generate_summary(FAKE_CONTEXT)

    assert result.is_ai is False
    assert result.model is None
    for section in (
        "## Resume",
        "## Alertes prioritaires",
        "## Opportunites",
        "## Plan d'action",
        "## Limites",
    ):
        assert section in result.text, f"Section manquante : {section}"


def test_fallback_cites_provided_numbers_only():
    """Le fallback reprend les chiffres du contexte sans en inventer."""
    with patch.object(provider, "get_api_key", return_value=None):
        result = summary.generate_summary(FAKE_CONTEXT)

    assert "50 000" in result.text or "50000" in result.text
    assert "1 500" in result.text or "1500" in result.text
    assert "Waste eleve sur Poisson" in result.text
    assert "Mardi" in result.text


def test_fallback_handles_no_recommendations():
    ctx = {**FAKE_CONTEXT, "recommendations": []}
    with patch.object(provider, "get_api_key", return_value=None):
        result = summary.generate_summary(ctx)
    assert "Aucune alerte critique" in result.text


# ---------------------------------------------------------------------------
# provider — detection cle + mock appel
# ---------------------------------------------------------------------------


def test_get_api_key_from_env():
    fake_secrets = MagicMock(get=MagicMock(return_value=None))
    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True),
        patch("streamlit.secrets", new=fake_secrets),
    ):
        assert provider.get_api_key() == "sk-test"


def test_get_api_key_none_when_unset():
    fake_secrets = MagicMock(get=MagicMock(return_value=None))
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("streamlit.secrets", new=fake_secrets),
    ):
        assert provider.get_api_key() is None


def test_is_available_false_without_key():
    with patch.object(provider, "get_api_key", return_value=None):
        assert provider.is_available() is False


def test_summary_uses_llm_when_available():
    """Avec cle + SDK mocke, generate_summary renvoie le texte du LLM."""
    fake_block = MagicMock(text="## Resume\nSynthese IA mockee.")
    fake_msg = MagicMock(content=[fake_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg

    with (
        patch.object(provider, "get_api_key", return_value="sk-test"),
        patch.object(provider, "is_available", return_value=True),
        patch("anthropic.Anthropic", return_value=fake_client),
    ):
        result = summary.generate_summary(FAKE_CONTEXT)

    assert result.is_ai is True
    assert result.model == provider.DEFAULT_MODEL
    assert "Synthese IA mockee" in result.text

    # Le prompt contient bien le contexte JSON
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == provider.DEFAULT_MODEL
    assert call_kwargs["temperature"] <= 0.3
    user_prompt = call_kwargs["messages"][0]["content"]
    assert "50000" in user_prompt  # chiffre du contexte injecte


def test_summary_falls_back_on_llm_error():
    """Si l'appel LLM leve, on retombe sur le fallback avec annotation."""
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("boom")

    with (
        patch.object(provider, "is_available", return_value=True),
        patch.object(provider, "get_api_key", return_value="sk-test"),
        patch("anthropic.Anthropic", return_value=fake_client),
    ):
        result = summary.generate_summary(FAKE_CONTEXT)

    assert result.is_ai is False
    assert "appel IA echoue" in result.text
    assert "## Resume" in result.text

"""Acces LLM : detection cle API + appel Claude.

La cle est lue dans cet ordre :
    1. ``st.secrets["ANTHROPIC_API_KEY"]`` (Streamlit Cloud ou .streamlit/secrets.toml)
    2. variable d'env ``ANTHROPIC_API_KEY``

Import d'``anthropic`` et de ``streamlit`` en lazy : le module reste importable
meme si l'une ou l'autre des deps manque (utile pour les tests unitaires).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class LLMResponse:
    text: str
    model: str


def get_api_key() -> str | None:
    """Retourne la cle API ou None si aucune source configuree."""
    try:
        import streamlit as st

        key = st.secrets.get("ANTHROPIC_API_KEY")  # type: ignore[attr-defined]
        if key:
            return str(key)
    except Exception:
        # st.secrets leve si secrets.toml absent / on est hors contexte Streamlit
        pass
    return os.environ.get("ANTHROPIC_API_KEY") or None


def is_available() -> bool:
    """True si une cle est configuree ET le SDK ``anthropic`` est importable."""
    if not get_api_key():
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def call_claude(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1200,
    temperature: float = 0.2,
) -> LLMResponse:
    """Appelle Claude. Leve ``RuntimeError`` si la cle est absente."""
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    # L'API renvoie une liste de blocs ; on ne garde que le texte.
    parts: list[str] = []
    for block in msg.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return LLMResponse(text="\n".join(parts).strip(), model=model)

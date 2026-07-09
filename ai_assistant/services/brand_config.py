"""Per-brand Config-DS-shaped JSON — local files now; GET /merged in production."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from config import SITE_ID_DEFAULT

_BRANDS_DIR = Path(__file__).resolve().parents[2] / "config" / "brands"

# Short aliases accepted on site_id (API / tests)
_SITE_ALIASES: dict[str, str] = {
    "brand_alpha": "brand_alpha_us",
    "brand_beta": "brand_beta_us",
    "brand_gamma": "brand_gamma_us",
}

_PERSONALITY_KEYS = (
    "site_id",
    "brand_slug",
    "persona_name",
    "tone",
    "system_prompt",
    "response_length",
    "content_domains",
    "input_filter_topics",
    "output_filter",
    "max_response_tokens",
    "concorde_site_id",
)

_REQUIRED_PROMPTS = (
    "input_guardrail",
    "generate_response_context",
    "thread_title",
    "output_guardrail",
    "guardrail_retry_user",
    "fallback_blocked",
    "fallback_guardrail",
)


def resolve_site_id(site_id: str | None) -> str:
    key = (site_id or SITE_ID_DEFAULT).strip().lower()
    return _SITE_ALIASES.get(key, key)


def site_id_from_state(state: object) -> str:
    """Resolved brand slug from graph/API state (uses SITE_ID_DEFAULT when unset)."""
    site_id = state.get("site_id") if isinstance(state, dict) else getattr(state, "site_id", None)
    return resolve_site_id(site_id)


@lru_cache
def load_brand_config(site_id: str) -> dict:
    """
    Load merged ai_assistant_personality + prompts for a site.

    File layout: config/brands/{site_id}.json (Config-DS local stand-in).
    """
    resolved = resolve_site_id(site_id)
    path = _BRANDS_DIR / f"{resolved}.json"
    if not path.is_file():
        fallback = resolve_site_id(SITE_ID_DEFAULT)
        path = _BRANDS_DIR / f"{fallback}.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"No brand config for site_id={site_id!r} (resolved {resolved!r}) in {_BRANDS_DIR}"
            )
        resolved = fallback

    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    prompts = data.get("prompts")
    if not isinstance(prompts, dict):
        raise ValueError(f"Brand config {path.name} must include a 'prompts' object")

    missing = [name for name in _REQUIRED_PROMPTS if name not in prompts]
    if missing:
        raise ValueError(f"Brand config {path.name} missing prompts: {missing}")

    data["site_id"] = data.get("site_id") or resolved
    return data


def personality_fields(config: dict) -> dict:
    """Slice returned to AgentState — matches Config-DS §4.2 merged document."""
    return {k: config[k] for k in _PERSONALITY_KEYS if k in config}


@lru_cache
def load_personality(site_id: str) -> dict:
    """Backward-compatible name used by load_context."""
    return personality_fields(load_brand_config(site_id))


def list_prompts(site_id: str) -> list[str]:
    return sorted(load_brand_config(site_id).get("prompts", {}).keys())


def _format_template(template: str, variables: dict[str, str]) -> str:
    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(_SafeDict(variables))


def get_prompt(site_id: str, name: str, **variables: str) -> str:
    config = load_brand_config(site_id)
    prompts = config["prompts"]
    if name not in prompts:
        raise KeyError(f"Prompt {name!r} not in brand config for {config['site_id']}")
    return _format_template(prompts[name], variables)

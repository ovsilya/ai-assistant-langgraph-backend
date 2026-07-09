"""Resolve prompt templates from per-brand JSON (Config-DS local stand-in)."""

from ai_assistant.services.brand_config import get_prompt
from ai_assistant.services.brand_config import list_prompts as _list_prompts
from config import SITE_ID_DEFAULT


def load_prompt(name: str, *, site: str | None = None, **variables: str) -> str:
    """
    Load a prompt template and substitute {placeholders}.

    `site` is the API site_id (e.g. brand_alpha_us, brand_beta_us, brand_gamma → brand_gamma_us).
    """
    site_key = site or SITE_ID_DEFAULT
    return get_prompt(site_key, name, **variables)


def list_prompts(site: str | None = None) -> list[str]:
    return _list_prompts(site or SITE_ID_DEFAULT)

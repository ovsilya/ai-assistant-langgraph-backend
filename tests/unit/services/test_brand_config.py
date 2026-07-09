import pytest

from ai_assistant.prompts.loader import list_prompts, load_prompt
from ai_assistant.services.brand_config import (
    get_prompt,
    load_brand_config,
    load_personality,
    resolve_site_id,
)


class TestBrandConfig:
    def test_all_brand_alpha_prompts_in_json(self):
        names = list_prompts("brand_alpha_us")
        assert "input_guardrail" in names
        assert len(names) >= 7

    def test_load_prompt_substitutes(self):
        text = load_prompt(
            "input_guardrail",
            site="brand_alpha_us",
            message="hello",
            input_filter_topics="[]",
            content_domains="[]",
        )
        assert "hello" in text

    def test_generate_response_prompt_includes_suggestions_and_domains(self):
        text = load_prompt(
            "generate_response_context",
            site="brand_alpha_us",
            article_block="(no articles)",
            page_url="https://www.meridian.example.com/",
            length_hint="one short paragraph",
            content_domains="cars, culture",
        )
        assert "---SUGGESTIONS---" in text
        assert "cars, culture" in text

    def test_personality_from_brand_json(self):
        personality = load_personality("brand_alpha_us")
        assert "Meridian Advisor" in personality["system_prompt"]
        assert personality["site_id"] == "brand_alpha_us"

    def test_site_aliases(self):
        assert resolve_site_id("brand_gamma") == "brand_gamma_us"
        assert resolve_site_id("brand_beta") == "brand_beta_us"

    def test_brand_beta_and_rw_configs_load(self):
        for site in ("brand_beta_us", "brand_gamma_us"):
            cfg = load_brand_config(site)
            assert cfg["prompts"]["input_guardrail"]
            assert cfg["system_prompt"]

    def test_unknown_site_falls_back_to_default(self):
        cfg = load_brand_config("unknown_brand_xyz")
        assert cfg["site_id"] == "brand_alpha_us"

    def test_get_prompt_missing_raises(self):
        with pytest.raises(KeyError):
            get_prompt("brand_alpha_us", "nonexistent_prompt_name")

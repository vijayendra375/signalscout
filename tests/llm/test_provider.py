"""Optional LLM provider selection and the anti-hallucination numeric guard."""

from app.llm.provider import (
    DeterministicProvider,
    get_provider,
    is_grounded,
)
from app.config.settings import Settings


def test_default_provider_is_deterministic_and_disabled():
    provider = get_provider(Settings())
    assert isinstance(provider, DeterministicProvider)
    assert provider.enabled is False
    assert provider.available() is False
    assert provider.complete("s", "u") is None


def test_unknown_provider_falls_back_to_deterministic():
    provider = get_provider(Settings(model_provider="some-unknown-thing"))
    assert isinstance(provider, DeterministicProvider)


def test_openai_compatible_not_available_without_key(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    provider = get_provider(Settings(
        model_provider="openai_compatible",
        model_name="some-model",
        model_base_url="http://localhost:8000/v1",
        model_api_key_env="MY_KEY",
    ))
    assert provider.enabled is True
    assert provider.available() is False
    assert provider.complete("s", "u") is None


def test_is_grounded_allows_only_known_numbers():
    source = "Revenue 1,000,000 NOK and 250 employees."
    assert is_grounded("The company reported 1000000 NOK revenue.", source) is True
    assert is_grounded("Revenue was 2,000,000 NOK.", source) is False
    # No numbers at all is always grounded.
    assert is_grounded("A Norwegian company.", source) is True

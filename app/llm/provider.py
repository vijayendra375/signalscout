"""Optional language-model provider abstraction.

SignalScout's identity resolution, evidence collection and numeric facts are
fully deterministic and require no model. A language model may optionally be
used only to *rephrase already-validated facts*; it is never the authority for
company identity or numbers.

Design guarantees:
* The default provider is ``deterministic`` and performs no network I/O, so the
  core pipeline works at $0 even when no model is configured.
* Enabling a model is explicit via ``SIGNALSCOUT_MODEL_PROVIDER``. The code never
  silently switches to a paid service.
* API keys are read from an environment variable (name configurable via
  ``SIGNALSCOUT_MODEL_API_KEY_ENV``) and are never logged or emitted.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

import requests

from app.config.settings import Settings, settings as default_settings


DETERMINISTIC_NAMES = {"", "deterministic", "none", "disabled", "off", "local-rules"}
OPENAI_COMPATIBLE_NAMES = {"openai", "openai_compatible", "openai-compatible", "nvidia", "nim", "vllm"}


class LLMProvider:
    """Base interface. The default implementation is a no-op."""

    name = "deterministic"
    enabled = False

    def available(self) -> bool:
        return False

    def complete(self, system: str, user: str, max_tokens: int = 400) -> Optional[str]:
        return None


class DeterministicProvider(LLMProvider):
    """No-op provider: the deterministic synthesizer is authoritative."""

    name = "deterministic"
    enabled = False


class OpenAICompatibleProvider(LLMProvider):
    """Optional adapter for an OpenAI-compatible (or NVIDIA NIM) chat endpoint."""

    enabled = True

    def __init__(self, base_url: str, model: str, api_key_env: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout

    @property
    def name(self) -> str:  # type: ignore[override]
        return f"openai_compatible:{self.model}"

    def available(self) -> bool:
        return bool(self.base_url and self.model and os.environ.get(self.api_key_env))

    def complete(self, system: str, user: str, max_tokens: int = 400) -> Optional[str]:
        if not self.available():
            return None
        api_key = os.environ.get(self.api_key_env, "")
        url = f"{self.base_url}/chat/completions"
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.0,
                    "max_tokens": max_tokens,
                },
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return None
            payload = resp.json()
            choices = payload.get("choices") or []
            if not choices:
                return None
            return (choices[0].get("message") or {}).get("content")
        except Exception:
            # Never raise into the pipeline; fall back to deterministic synthesis.
            return None


def get_provider(config: Optional[Settings] = None) -> LLMProvider:
    cfg = config or default_settings
    provider = (cfg.model_provider or "deterministic").strip().lower()
    if provider in OPENAI_COMPATIBLE_NAMES:
        return OpenAICompatibleProvider(
            base_url=cfg.model_base_url,
            model=cfg.model_name,
            api_key_env=cfg.model_api_key_env,
        )
    if provider not in DETERMINISTIC_NAMES:
        # Unknown provider name: stay deterministic rather than guessing.
        return DeterministicProvider()
    return DeterministicProvider()


_NUMBER_RE = re.compile(r"\d[\d\s.,]*")


def _numbers(text: str) -> List[str]:
    out = []
    for match in _NUMBER_RE.findall(text or ""):
        digits = re.sub(r"\D", "", match)
        if digits:
            out.append(digits)
    return out


def is_grounded(candidate_text: str, allowed_text: str) -> bool:
    """Return True only when every number in the candidate appears in the allowed source.

    This is a hard anti-hallucination guard: an optional model may rephrase, but
    it may not introduce any numeric figure that is not present in validated facts.
    """
    allowed_digits = set(_numbers(allowed_text))
    for number in _numbers(candidate_text):
        if number not in allowed_digits:
            return False
    return True

"""Central settings and configuration management for SignalScout.

All values can be overridden with environment variables so that a clean-machine
evaluator run needs no code changes and no secrets in the repository.
"""

from __future__ import annotations

import os
from typing import Optional
from pydantic import BaseModel, Field


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw if raw is not None and raw.strip() != "" else default


class Settings(BaseModel):
    # Execution & concurrency
    max_workers: int = Field(default=8, description="Number of parallel worker threads for batch processing")
    checkpoint_every: int = Field(default=25, description="Frequency of batch checkpointing")

    # Network & timeouts
    request_timeout_seconds: float = Field(default=8.0, description="Socket and HTTP read timeout")
    max_retries: int = Field(default=3, description="Maximum retry count for transient HTTP failures")
    backoff_factor: float = Field(default=1.5, description="Exponential backoff factor")
    max_response_bytes: int = Field(default=10 * 1024 * 1024, description="Maximum downloaded response size (10 MB)")
    user_agent: str = Field(
        default="SignalScout/1.0 (+https://builderr.ai/challenges/signalpost; research-bot)",
        description="Compliant User-Agent identifier",
    )

    # Rate limits & delay
    brreg_rate_limit_per_second: float = Field(default=10.0, description="Max queries per second to official Brreg APIs")
    website_delay_seconds: float = Field(default=0.5, description="Politeness delay between requests to the same domain")

    # Budgets
    max_requests_per_company: int = Field(default=12, description="Ceiling on HTTP requests per target company (enforced)")
    max_pages_per_website: int = Field(default=5, description="Max successfully-crawled pages when exploring a company website")
    max_website_attempts: int = Field(default=6, description="Ceiling on website fetch attempts (incl. 404s) per company")
    max_sitemaps_per_website: int = Field(default=3, description="Max sitemap files to follow per website (index + children)")
    max_urls_per_sitemap: int = Field(default=50, description="Max URLs to extract from a single sitemap document")
    global_request_budget: int = Field(default=2000, description="Hard ceiling on total outbound requests per run (0 = unlimited)")
    run_deadline_seconds: int = Field(default=2700, description="Wall-clock ceiling per run in seconds (0 = unlimited); 2700 = 45 min")

    # Storage
    db_path: str = Field(default="data/signalscout.db", description="SQLite database path for snapshot persistence")

    # Third-party cost enforcement
    declared_third_party_cost_usd: float = Field(default=0.0, description="Guaranteed $0.00 third-party cost")

    # Optional language-model provider (deterministic by default; never auto-switches to paid)
    model_provider: str = Field(default="deterministic", description="deterministic | openai_compatible | disabled")
    model_name: str = Field(default="", description="Model identifier for optional provider")
    model_base_url: str = Field(default="", description="Base URL for an OpenAI-compatible endpoint")
    model_api_key_env: str = Field(
        default="SIGNALSCOUT_MODEL_API_KEY",
        description="Name of the environment variable holding the provider API key (never logged)",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            max_workers=_env_int("SIGNALSCOUT_MAX_WORKERS", 8),
            checkpoint_every=_env_int("SIGNALSCOUT_CHECKPOINT_EVERY", 25),
            request_timeout_seconds=_env_float("SIGNALSCOUT_REQUEST_TIMEOUT", 8.0),
            max_retries=_env_int("SIGNALSCOUT_MAX_RETRIES", 3),
            backoff_factor=_env_float("SIGNALSCOUT_BACKOFF_FACTOR", 1.5),
            max_response_bytes=_env_int("SIGNALSCOUT_MAX_RESPONSE_BYTES", 10 * 1024 * 1024),
            user_agent=_env_str("SIGNALSCOUT_USER_AGENT", cls.model_fields["user_agent"].default),
            max_requests_per_company=_env_int("SIGNALSCOUT_MAX_REQUESTS_PER_COMPANY", 12),
            max_pages_per_website=_env_int("SIGNALSCOUT_MAX_PAGES_PER_WEBSITE", 5),
            max_website_attempts=_env_int("SIGNALSCOUT_MAX_WEBSITE_ATTEMPTS", 6),
            max_sitemaps_per_website=_env_int("SIGNALSCOUT_MAX_SITEMAPS_PER_WEBSITE", 3),
            max_urls_per_sitemap=_env_int("SIGNALSCOUT_MAX_URLS_PER_SITEMAP", 50),
            global_request_budget=_env_int("SIGNALSCOUT_GLOBAL_REQUEST_BUDGET", 2000),
            run_deadline_seconds=_env_int("SIGNALSCOUT_RUN_DEADLINE_SECONDS", 2700),
            db_path=_env_str("SIGNALSCOUT_DB_PATH", "data/signalscout.db"),
            declared_third_party_cost_usd=_env_float("SIGNALSCOUT_DECLARED_COST_USD", 0.0),
            model_provider=_env_str("SIGNALSCOUT_MODEL_PROVIDER", "deterministic"),
            model_name=_env_str("SIGNALSCOUT_MODEL_NAME", ""),
            model_base_url=_env_str("SIGNALSCOUT_MODEL_BASE_URL", ""),
            model_api_key_env=_env_str("SIGNALSCOUT_MODEL_API_KEY_ENV", "SIGNALSCOUT_MODEL_API_KEY"),
        )


# Global singleton settings (environment-aware)
settings = Settings.from_env()

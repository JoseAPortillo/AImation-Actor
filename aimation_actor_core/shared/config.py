"""Typed application configuration (SDD §2.2, shared).

Uses Pydantic Settings with strict typing. All secrets come from the
environment, never from source files (SDD §4.3).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration loaded from environment / .env.

    Attributes:
        app_name: Human-readable service name.
        host: Bind address. MUST stay loopback (SDD §4.2).
        port: Local API port (must be > 1024 for unprivileged runs).
        session_token: Per-instance token shared with Tauri/plugins.
        rate_limit_per_second: Max requests per second per session.
        max_video_bytes: Hard cap for uploaded video files.
    """

    model_config = SettingsConfigDict(
        env_prefix="AIMATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AImation Actor Core"
    host: str = Field(default="127.0.0.1", pattern=r"^127\.0\.0\.1$|^localhost$")
    port: int = Field(default=8765, ge=1024, le=65535)
    session_token: str = Field(
        default="",
        description="Per-instance token. Auto-generated at startup when empty.",
    )
    rate_limit_per_second: int = Field(default=10, ge=1)
    max_video_bytes: int = Field(default=2 * 1024**3, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()

"""Configuration helpers for the Atlassian CLI."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, ValidationError


class ConfluenceCredentials(BaseModel):
    """Connection information for the Confluence REST API."""

    base_url: HttpUrl = Field(..., description="Base URL of the Confluence instance")
    email: str = Field(..., description="Account email associated with the API token")
    api_token: str = Field(..., description="API token generated from Atlassian account")


class SyncDefaults(BaseModel):
    """Default context parameters for synchronization operations."""

    space_key: Optional[str] = Field(None, description="Default Confluence space key")
    parent_page_id: Optional[str] = Field(
        None, description="Default parent page ID that acts as the synchronization root"
    )


class AtlassianConfig(BaseModel):
    """Aggregate configuration for the CLI."""

    credentials: ConfluenceCredentials
    defaults: SyncDefaults = Field(default_factory=SyncDefaults)


ENV_PREFIX = "ATLASSIAN"
DEFAULT_CONFIG_PATHS = (
    Path.cwd() / "atlassian-cli.toml",
    Path.home() / ".config" / "atlassian-cli" / "config.toml",
)


@dataclasses.dataclass
class ConfigSource:
    """Result of attempting to resolve configuration data."""

    config: Optional[AtlassianConfig]
    path: Optional[Path]
    error: Optional[Exception]


def _load_from_env() -> dict[str, object]:
    """Return a dictionary with configuration values extracted from environment variables."""

    def _get(name: str) -> Optional[str]:
        return os.getenv(f"{ENV_PREFIX}_{name}")

    env_data: dict[str, object] = {}
    for key in ("BASE_URL", "EMAIL", "API_TOKEN"):
        value = _get(key)
        if value:
            env_data[key.lower()] = value

    defaults: dict[str, str] = {}
    for key in ("SPACE_KEY", "PARENT_PAGE_ID"):
        value = _get(key)
        if value:
            defaults[key.lower()] = value

    if env_data:
        env_data["defaults"] = defaults

    return env_data


def _load_toml(path: Path) -> Optional[dict]:
    if not path.exists():
        return None

    try:  # Python 3.11+
        import tomllib  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback
        import tomli as tomllib  # type: ignore

    with path.open("rb") as handle:
        return tomllib.load(handle)


def resolve_config(explicit_path: Optional[Path] = None) -> ConfigSource:
    """Discover configuration using the first available source.

    The priority order is:
    1. Explicit path provided via CLI argument.
    2. Default configuration files in the working directory or the user's config directory.
    3. Environment variables with the `ATLASSIAN_` prefix.
    """

    errors: list[Exception] = []
    sources: list[tuple[Optional[Path], Optional[dict]]] = []

    if explicit_path:
        try:
            data = _load_toml(explicit_path)
            if data is not None:
                sources.append((explicit_path, data))
        except Exception as exc:  # pragma: no cover - configuration loading failure path
            errors.append(exc)

    if not sources:
        for path in DEFAULT_CONFIG_PATHS:
            try:
                data = _load_toml(path)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
                continue
            if data is not None:
                sources.append((path, data))
                break

    if not sources:
        env_data = _load_from_env()
        if env_data:
            # remap env data structure to align with Pydantic model
            combined = {
                "credentials": {
                    "base_url": env_data.get("base_url"),
                    "email": env_data.get("email"),
                    "api_token": env_data.get("api_token"),
                },
                "defaults": {
                    "space_key": env_data.get("defaults", {}).get("space_key"),
                    "parent_page_id": env_data.get("defaults", {}).get("parent_page_id"),
                },
            }
            sources.append((None, combined))

    for path, data in sources:
        if data is None:
            continue
        try:
            config = AtlassianConfig.model_validate(data)
            return ConfigSource(config=config, path=path, error=None)
        except ValidationError as exc:
            errors.append(exc)

    error = errors[0] if errors else None
    return ConfigSource(config=None, path=None, error=error)


def ensure_config(
    *,
    base_url: Optional[str] = None,
    email: Optional[str] = None,
    api_token: Optional[str] = None,
    space_key: Optional[str] = None,
    parent_page_id: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> AtlassianConfig:
    """Resolve configuration from precedence order and fall back to explicit CLI options."""

    source = resolve_config(config_path)

    if source.config:
        config = source.config.model_copy(deep=True)
    else:
        if not all([base_url, email, api_token]):
            hint = " or configuration file" if config_path else ""
            raise RuntimeError(
                "Missing Confluence credentials. Provide them via CLI options, environment variables," + hint
            )
        config = AtlassianConfig(
            credentials=ConfluenceCredentials(
                base_url=base_url,
                email=email,
                api_token=api_token,
            ),
            defaults=SyncDefaults(space_key=space_key, parent_page_id=parent_page_id),
        )

    if base_url:
        config.credentials.base_url = base_url
    if email:
        config.credentials.email = email
    if api_token:
        config.credentials.api_token = api_token
    if space_key:
        config.defaults.space_key = space_key
    if parent_page_id:
        config.defaults.parent_page_id = parent_page_id

    return config

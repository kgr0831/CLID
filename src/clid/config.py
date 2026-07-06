"""Configuration: repo paths, ``.env`` loading, ``models.toml`` parsing."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    p = (start or Path(__file__)).resolve()
    for parent in [p, *p.parents]:
        if (parent / "pyproject.toml").exists() or (parent / "config" / "models.toml").exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root()


def load_env(path: str | Path | None = None) -> None:
    """Minimal .env loader (no python-dotenv). Does not override existing env."""
    env_path = Path(path) if path else REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Endpoint:
    base_url: str
    model: str
    api_key: str


@dataclass
class Settings:
    backend: str                       # "mock" | "openai"
    sandbox: str                       # "local" | "docker"
    orchestrator: Endpoint
    coder: Endpoint
    strategy_mode: str                 # "sequential_swap" | "concurrent"
    models_toml: dict = field(default_factory=dict)
    prompts_dir: Path = REPO_ROOT / "config" / "prompts"
    runs_dir: Path = REPO_ROOT / "runs"
    workspaces_dir: Path = REPO_ROOT / "workspaces"

    @property
    def review(self) -> dict:
        return self.models_toml.get("review", {})

    def prompt(self, mode: str) -> str:
        f = self.prompts_dir / f"{mode}.md"
        return f.read_text(encoding="utf-8") if f.exists() else ""


def _toml() -> dict:
    f = REPO_ROOT / "config" / "models.toml"
    if not f.exists():
        return {}
    return tomllib.loads(f.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_env()
    toml = _toml()
    return Settings(
        backend=os.environ.get("CLID_BACKEND", "mock"),
        sandbox=os.environ.get("CLID_SANDBOX", "local"),
        orchestrator=Endpoint(
            base_url=os.environ.get("CLID_ORCH_BASE_URL", "http://127.0.0.1:8080/v1"),
            model=os.environ.get("CLID_ORCH_MODEL", "orchestrator"),
            api_key=os.environ.get("CLID_ORCH_API_KEY", "sk-local"),
        ),
        coder=Endpoint(
            base_url=os.environ.get("CLID_CODER_BASE_URL", "http://127.0.0.1:8080/v1"),
            model=os.environ.get("CLID_CODER_MODEL", "coder"),
            api_key=os.environ.get("CLID_CODER_API_KEY", "sk-local"),
        ),
        strategy_mode=toml.get("strategy", {}).get("mode", "sequential_swap"),
        models_toml=toml,
    )

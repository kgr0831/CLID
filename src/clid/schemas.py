"""Structured I/O contracts for every orchestrator mode + the Coder.

These mirror the JSON schemas in ``config/prompts/*.md`` and give the pipeline
a validated, typed surface regardless of backend. Validation is lenient
(``extra="ignore"``, defaults everywhere) so a real quantized model that drops a
field degrades gracefully instead of crashing the run.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ── 1 · classify ─────────────────────────────────────────────────────────────
class Classification(_Base):
    domain: str = "other"
    language: str = "python"
    project_type: str = "script"
    summary: str = ""
    confidence: float = 0.5


# ── 2 · design ───────────────────────────────────────────────────────────────
class FilePlan(_Base):
    path: str
    role: str = "core_logic"           # boilerplate | core_logic | test | config
    purpose: str = ""
    spec: str = ""
    depends_on: list[str] = Field(default_factory=list)


class BuildPlan(_Base):
    install: str = ""
    test: str = ""
    entrypoint: str = ""


class Design(_Base):
    root: str = "project"
    files: list[FilePlan] = Field(default_factory=list)
    build: BuildPlan = Field(default_factory=BuildPlan)
    notes: str = ""


# ── 3 · delegate ─────────────────────────────────────────────────────────────
class DelegateTask(_Base):
    path: str
    route: str = "coder"               # coder | template
    system_prompt: str = "You are a Coder."
    instructions: str = ""
    context_files: list[str] = Field(default_factory=list)
    acceptance: str = ""


class Delegation(_Base):
    tasks: list[DelegateTask] = Field(default_factory=list)


# ── 4 · coder ────────────────────────────────────────────────────────────────
class CoderOutput(_Base):
    path: str
    content: str = ""
    notes: str = ""


# ── 5 · diagnose ─────────────────────────────────────────────────────────────
class Issue(_Base):
    path: str = ""
    kind: str = "other"
    detail: str = ""
    fix_hint: str = ""


class Diagnosis(_Base):
    consistent: bool = True
    issues: list[Issue] = Field(default_factory=list)


# ── 6 · judge ────────────────────────────────────────────────────────────────
class JudgeVerdict(_Base):
    verdict: str = "fail"              # pass | fail
    route: str = "coder"              # coder | runner | sub | halt
    target_path: str = ""
    reason: str = ""
    correction: str = ""

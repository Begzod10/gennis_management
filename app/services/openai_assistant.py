"""OpenAI-backed helpers for mission assignment suggestions.

The endpoint passes a compact, anonymised view of eligible executors plus the
mission title and description; we ask the model to rank the best matches and
explain its reasoning. Networking uses httpx because it is already a project
dependency — we do not add the openai SDK.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class OpenAIError(RuntimeError):
    """Raised when the upstream model call fails or returns an unusable shape."""


@dataclass(frozen=True)
class ExecutorCandidate:
    id: int
    name: str
    role: str
    job: Optional[str] = None
    section: Optional[str] = None
    project: Optional[str] = None
    branch: Optional[str] = None
    completed_missions: int = 0
    recent_mission_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutorSuggestion:
    user_id: int
    score: float
    reason: str


@dataclass(frozen=True)
class MissionContext:
    """Optional metadata the model uses to rank candidates."""
    project_name: Optional[str] = None
    project_description: Optional[str] = None
    section_name: Optional[str] = None
    branch_name: Optional[str] = None
    location_name: Optional[str] = None


_SYSTEM_PROMPT = (
    "You are an assignment assistant for a company task tracker. "
    "Given a mission's title, description, and optional project/section/branch "
    "context, rank the most relevant executors from a candidate list. Use each "
    "candidate's role, job, current memberships, and especially their past "
    "mission titles as evidence. Prefer specialists whose role, job, or prior "
    "missions match the new mission's domain. "
    "Differentiate candidates: every chosen candidate must have a reason that "
    "cites something specific about THAT candidate (their job, role, or a past "
    "mission title) — never reuse the same reason or assign identical scores "
    "to multiple candidates unless they are genuinely indistinguishable. "
    "If the input is too vague to differentiate, return only one candidate. "
    "Return strict JSON only — no prose, no markdown."
)


def _candidates_payload(candidates: List[ExecutorCandidate]) -> list[dict]:
    payload = []
    for c in candidates:
        item = {
            "id": c.id,
            "name": c.name,
            "role": c.role,
            "job": c.job,
            "section": c.section,
            "project": c.project,
            "branch": c.branch,
        }
        if c.completed_missions:
            item["completed_missions"] = c.completed_missions
        if c.recent_mission_titles:
            item["recent_mission_titles"] = list(c.recent_mission_titles)
        payload.append(item)
    return payload


def _context_lines(ctx: Optional["MissionContext"]) -> str:
    if not ctx:
        return ""
    parts = []
    if ctx.project_name:
        parts.append(f"Project: {ctx.project_name}")
        if ctx.project_description:
            parts.append(f"Project description: {ctx.project_description}")
    if ctx.section_name:
        parts.append(f"Section: {ctx.section_name}")
    if ctx.branch_name:
        parts.append(f"Branch: {ctx.branch_name}")
    if ctx.location_name:
        parts.append(f"Location: {ctx.location_name}")
    return ("\n".join(parts) + "\n") if parts else ""


def _user_prompt(
    title: str,
    description: Optional[str],
    candidates: List[ExecutorCandidate],
    top_k: int,
    context: Optional["MissionContext"],
) -> str:
    return (
        f"Mission title: {title}\n"
        f"Mission description: {description or '(none)'}\n"
        f"{_context_lines(context)}"
        f"\nCandidates (JSON):\n{json.dumps(_candidates_payload(candidates), ensure_ascii=False)}\n\n"
        f"Pick up to {top_k} best executors. "
        "Respond as JSON with this exact shape:\n"
        '{"suggestions": [{"user_id": <int>, "score": <float between 0 and 1>, "reason": "<short reason>"}]}'
    )


def suggest_executors(
    title: str,
    description: Optional[str],
    candidates: List[ExecutorCandidate],
    top_k: int = 3,
    timeout: float = 20.0,
    context: Optional[MissionContext] = None,
) -> List[ExecutorSuggestion]:
    """Call the chat completion API and return a ranked list of executor suggestions."""
    if not settings.OPENAI_API_KEY:
        raise OpenAIError("OPENAI_API_KEY is not configured")
    if not candidates:
        return []

    payload = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(title, description, candidates, top_k, context)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions"

    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("OpenAI transport error: %s url=%s", exc, url)
        raise OpenAIError(f"OpenAI transport error: {exc}") from exc

    if resp.status_code >= 400:
        snippet = resp.text[:500].replace("\n", " ")
        logger.warning(
            "OpenAI returned %s url=%s body=%s", resp.status_code, url, snippet
        )
        raise OpenAIError(f"OpenAI HTTP {resp.status_code}: {snippet}")

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        raw = parsed.get("suggestions", [])
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Could not parse OpenAI response: %s — body=%s", exc, resp.text[:500])
        raise OpenAIError(f"Unparseable OpenAI response: {exc}") from exc

    candidate_ids = {c.id for c in candidates}
    suggestions: List[ExecutorSuggestion] = []
    for item in raw:
        try:
            uid = int(item["user_id"])
            if uid not in candidate_ids:
                continue
            suggestions.append(
                ExecutorSuggestion(
                    user_id=uid,
                    score=float(item.get("score", 0.0)),
                    reason=str(item.get("reason", "")).strip(),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions[:top_k]

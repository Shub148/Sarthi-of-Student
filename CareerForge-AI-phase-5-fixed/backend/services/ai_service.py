import json
import os
import re
from typing import Any

import httpx

from . import resume_service


AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()


def is_configured() -> bool:
    # Gemini is the only supported provider in this application. Treat the
    # presence of its key as the source of truth so a stale AI_PROVIDER value
    # cannot silently disable the existing Gemini integration.
    return bool(GEMINI_API_KEY)


def _number(value: Any, default: float) -> float:
    try:
        return round(max(0.0, min(10.0, float(value))), 1)
    except (TypeError, ValueError):
        return default


def _clean_json(text: str) -> dict[str, Any]:
    """Parse a model response that may be wrapped in a markdown code fence."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("AI response was not a JSON object.")
    return parsed


def _normalise(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Keep AI output safe and predictable for the frontend."""
    result = dict(fallback)
    category_defaults = fallback.get("categories", {})
    raw_categories = raw.get("categories", {})
    if isinstance(raw_categories, dict):
        result["categories"] = {
            key: _number(raw_categories.get(key), default)
            for key, default in category_defaults.items()
        }

    result["score"] = _number(raw.get("score"), fallback.get("score", 0))
    for key in ("strengths", "weaknesses", "recommendations"):
        value = raw.get(key)
        if isinstance(value, list):
            result[key] = [str(item).strip() for item in value if str(item).strip()][:7]

    suggestions = raw.get("suggestions")
    if isinstance(suggestions, list):
        safe_suggestions = []
        for item in suggestions[:6]:
            if not isinstance(item, dict):
                continue
            safe_suggestions.append({
                "section": str(item.get("section", "Profile")).strip() or "Profile",
                "current": str(item.get("current", "")).strip(),
                "improved": str(item.get("improved", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
            })
        if safe_suggestions:
            result["suggestions"] = safe_suggestions

    assessment = raw.get("recruiter_assessment")
    if isinstance(assessment, str) and assessment.strip():
        result["recruiter_assessment"] = assessment.strip()
    # This label is intentionally added server-side so it cannot be omitted by a model.
    result["disclaimer"] = (
        "AI-generated recruiter-style simulation — not a real recruiter's opinion."
    )
    return result


def _prompt(profile: dict[str, Any]) -> str:
    profile_json = json.dumps(profile, ensure_ascii=False)
    return f"""
You are a career profile editor. Analyze the following professional profile for the
target role. Do not invent experience, employers, metrics, or skills. Be specific,
truthful, concise, and useful to a job seeker.

Return ONLY valid JSON with exactly these keys:
score (number 0-10),
categories (object with exactly these keys: profile_completeness, headline, about,
skills, experience, projects, target_role_alignment, recruiter_readability; values 0-10),
strengths (array of 2-5 strings),
weaknesses (array of 2-5 strings),
recommendations (array of 3-7 exact actions),
recruiter_assessment (string beginning with "AI-generated recruiter-style simulation:"),
suggestions (array of up to 6 objects, each with section, current, improved, reason).
The current/improved text must be grounded in the supplied profile. If a section is
empty, use "[section is empty]" as current and provide a practical example template
with placeholders rather than fabricated claims.

Profile:
{profile_json}
""".strip()


async def analyze_profile(profile: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Use Gemini when configured, otherwise keep the deterministic result."""
    if not is_configured():
        fallback["mode"] = "rule-based"
        fallback["analysis_label"] = "Rule-based analysis"
        return fallback

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": _prompt(profile)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            result = _normalise(_clean_json(text), fallback)
            result["mode"] = "ai"
            result["analysis_label"] = "AI-assisted analysis"
            return result
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        # A provider outage or malformed response must never make the core feature unusable.
        fallback["mode"] = "rule-based"
        fallback["analysis_label"] = "Rule-based analysis"
        return fallback


def _merge_project(base: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key in (
        "title", "description", "one_line_description", "portfolio_value", "difficulty",
        "estimated_development_complexity", "complexity", "why", "portfolio_gap",
        "recruiter_value", "recruiter_takeaway",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    for key in ("technologies", "stack", "gap_fixes", "skills_demonstrated", "core_features", "important_features", "advanced_features"):
        value = raw.get(key)
        if isinstance(value, list) and value:
            result[key] = [str(item).strip() for item in value if str(item).strip()][:12]
    for key in ("before", "after", "blueprint"):
        value = raw.get(key)
        if isinstance(value, dict):
            merged = dict(result.get(key) or {})
            merged.update({nested_key: nested_value for nested_key, nested_value in value.items() if nested_value})
            result[key] = merged
    return result


def _normalise_projects(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(fallback)
    fallback_projects = fallback.get("projects", [])
    raw_projects = raw.get("projects")
    if isinstance(raw_projects, list) and raw_projects:
        result["projects"] = [
            _merge_project(fallback_projects[index], item if isinstance(item, dict) else {})
            for index, item in enumerate(raw_projects[:len(fallback_projects)])
        ]
        if len(result["projects"]) < 3:
            result["projects"] = fallback_projects
    result["projects"] = sorted(result["projects"], key=lambda item: float(item.get("score", 0)), reverse=True)
    for index, project in enumerate(result["projects"], start=1):
        project["rank"] = index
    result["best_project"] = result["projects"][0] if result["projects"] else None

    for key in ("career_gap", "recruiter_view"):
        value = raw.get(key)
        if isinstance(value, dict):
            merged = dict(result.get(key) or {})
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, list):
                    merged[nested_key] = [str(item).strip() for item in nested_value if str(item).strip()][:12]
                elif isinstance(nested_value, str) and nested_value.strip():
                    merged[nested_key] = nested_value.strip()
                elif isinstance(nested_value, dict):
                    merged[nested_key] = {**(merged.get(nested_key) or {}), **nested_value}
            result[key] = merged
    result["mode"] = "ai"
    result["analysis_label"] = "AI-assisted recommendation"
    result["recruiter_disclaimer"] = (
        "Recruiter perspective is an AI-generated estimate and does not represent an actual recruiter's opinion."
    )
    return result


def _projects_prompt(context: dict[str, Any], fallback: dict[str, Any]) -> str:
    return f"""
You are a careful career project strategist. Recommend the next portfolio project for this
specific person, not generic beginner projects. Use only the supplied evidence. Do not
invent employers, metrics, skills, repositories, or experience. The deterministic draft
below is a candidate set: improve its wording and specificity, but keep the projects tied
to the target role and the biggest portfolio gap.

Return ONLY valid JSON with these keys:
career_gap (object), recruiter_view (object), projects (array of 3-4 objects).
Each project must preserve these fields when possible: title, description, why, portfolio_gap,
difficulty, estimated_development_complexity, technologies, skills_demonstrated,
core_features, advanced_features, recruiter_value, before, after, score, score_breakdown,
blueprint. Blueprint must include problem_statement, target_users, core_features,
advanced_features, technology_stack, architecture, database_design, api_design,
folder_structure, roadmap, testing_strategy, deployment, readme_structure.
Do not lower the usefulness of the deterministic score fields and do not use GitHub stars
as the quality score.

USER CONTEXT:
{json.dumps(context, ensure_ascii=False)}

DETERMINISTIC DRAFT:
{json.dumps(fallback, ensure_ascii=False)}
""".strip()


async def analyze_projects(context: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Use the existing Gemini abstraction for project wording, with a safe fallback."""
    if not is_configured():
        fallback["mode"] = "rule-based"
        fallback["analysis_label"] = "Rule-based recommendation"
        return fallback

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": _projects_prompt(context, fallback)}]}],
        "generationConfig": {
            "temperature": 0.25,
            "responseMimeType": "application/json",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return _normalise_projects(_clean_json(text), fallback)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        fallback["mode"] = "rule-based"
        fallback["analysis_label"] = "Rule-based recommendation"
        return fallback


def _resume_prompt(resume: dict[str, Any]) -> str:
    # Keep the request bounded even if a text file is close to the upload limit.
    source = dict(resume)
    source["original_text"] = str(source.get("original_text", ""))[:50000]
    return f"""
You are a careful resume analyst. Analyse only the supplied resume text and target role.
Never invent a skill, employer, title, project, certification, achievement, metric, or
technology. Missing information must be described as missing. Do not claim to reproduce
any ATS vendor. The recruiter review is an AI-generated simulation, not a hiring decision.

Return ONLY valid JSON with these keys:
score (number 0-10),
category_scores (object with exactly these keys: ats_compatibility, content_quality,
role_alignment, skills, experience, projects, achievements, formatting_structure,
keyword_coverage, readability; values 0-10),
ats_analysis (object), role_alignment (object), keywords (object),
bullet_suggestions (array), project_analysis (array), experience_analysis (array),
recruiter_review (object), strengths (array), weaknesses (array), action_plan (array),
improvements (array).
Every improvement must have section, current, suggested, and why. Suggestions must preserve
facts from the supplied text. If a metric is unavailable, say to add a verified result
instead of creating one. Keep the section and analysis structure from the deterministic
draft where possible.

DETERMINISTIC DRAFT:
{json.dumps(source, ensure_ascii=False)}
""".strip()


def _safe_list(value: Any, limit: int = 12) -> list[Any]:
    return value[:limit] if isinstance(value, list) else []


def _normalise_resume(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Merge only structurally valid AI fields over the deterministic analysis."""
    result = dict(fallback)
    categories = raw.get("category_scores")
    if not isinstance(categories, dict):
        categories = raw.get("categories")
    if isinstance(categories, dict):
        defaults = fallback.get("category_scores", fallback.get("categories", {}))
        result["category_scores"] = {
            key: _number(categories.get(key), default)
            for key, default in defaults.items()
        }
        result["categories"] = result["category_scores"]
    result["score"] = _number(raw.get("score"), fallback.get("score", 0))
    for key in ("strengths", "action_plan"):
        value = raw.get(key)
        if isinstance(value, list) and value:
            result[key] = [str(item).strip() for item in value if str(item).strip()][:8]
    weaknesses = raw.get("weaknesses")
    if isinstance(weaknesses, list) and weaknesses:
        safe_weaknesses = []
        for item in weaknesses[:8]:
            if isinstance(item, dict):
                safe_weaknesses.append({
                    "priority": str(item.get("priority", "Medium")).strip() or "Medium",
                    "item": str(item.get("item", item.get("text", ""))).strip(),
                })
            elif str(item).strip():
                safe_weaknesses.append({"priority": "Medium", "item": str(item).strip()})
        if safe_weaknesses:
            result["weaknesses"] = safe_weaknesses
    for key in ("ats_analysis", "role_alignment", "keywords", "recruiter_review"):
        value = raw.get(key)
        if isinstance(value, dict):
            result[key] = {**(fallback.get(key) or {}), **value}
    for key in ("bullet_suggestions", "project_analysis", "experience_analysis", "improvements"):
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        safe_items = []
        for item in value[:10]:
            if not isinstance(item, dict):
                continue
            safe_items.append({
                **item,
                "section": str(item.get("section", "Resume")).strip() or "Resume",
                "current": str(item.get("current", item.get("current_text", ""))).strip(),
                "suggested": str(item.get("suggested", item.get("suggested_text", item.get("improved", "")))).strip(),
                "why": str(item.get("why", item.get("reason", ""))).strip(),
            })
        if safe_items:
            result[key] = safe_items
    result["recruiter_review"] = {
        **(result.get("recruiter_review") or {}),
        "disclaimer": (
            "AI-generated recruiter-style simulation. This is not an actual recruiter's "
            "opinion or hiring decision."
        ),
    }
    result["improvements"] = _safe_improvement_items(
        result.get("improvements", []),
        str(fallback.get("text", fallback.get("original_text", ""))),
    )
    result["mode"] = "ai"
    result["analysis_mode"] = "gemini"
    result["analysis_label"] = "AI-assisted analysis"
    return result


async def analyze_resume(resume: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Use Gemini for resume analysis, falling back safely on any provider problem."""
    if not is_configured():
        fallback["mode"] = "rule-based"
        fallback["analysis_mode"] = "rule-based"
        fallback["analysis_label"] = "Rule-based analysis"
        return fallback
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": _resume_prompt(resume)}]}],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = _clean_json(text)
            if not isinstance(parsed.get("category_scores", parsed.get("categories")), dict):
                raise ValueError("Missing category scores")
            return _normalise_resume(parsed, fallback)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        fallback["mode"] = "rule-based"
        fallback["analysis_mode"] = "rule-based"
        fallback["analysis_label"] = "Rule-based analysis"
        return fallback


def _improvement_prompt(
    resume_text: str,
    target_role: str,
    user_feedback: str,
    mode: str,
    fallback: dict[str, Any],
    strict: bool = False,
) -> str:
    strict_instruction = """
IMPORTANT RETRY RULE: The previous draft contained an identical or unsupported
suggestion. For every item, current must be copied exactly from the resume and
suggested must be a materially different rewrite. Preserve every number, date,
URL, email, employer, title, technology, certification, and achievement; do not
introduce any new factual token. If you cannot safely improve a section, omit it.
""" if strict else ""
    return f"""
You improve resumes without changing the truth. Use only facts present in the resume.
The user's instruction and mode must influence the suggestions. Never create metrics,
skills, companies, job titles, projects, certifications, education, or achievements.
Suggestions are drafts for the user to accept, edit, or reject; do not rewrite the whole
resume. Return ONLY JSON: {{"improvements":[{{"section":"...", "current_text":"...",
"suggested_text":"...", "why":"...", "confidence":"...", "factual_basis":"..."}}]}}.
The aliases current and suggested are also accepted. Keep current text exact when it
comes from the resume. If a result is unavailable, say "Add a measurable result if
you can verify one."
{strict_instruction}

TARGET ROLE: {target_role}
USER INSTRUCTION: {user_feedback or "Keep claims truthful and make the resume clearer."}
IMPROVEMENT MODE: {mode or "general"}
RESUME:
{resume_text[:50000]}

DETERMINISTIC SUGGESTIONS:
{json.dumps(fallback, ensure_ascii=False)}
""".strip()


def _safe_improvement_items(items: Any, resume_text: str) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    safe: list[dict[str, str]] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        current = str(item.get("current", item.get("current_text", ""))).strip()
        suggested = str(item.get("suggested", item.get("suggested_text", item.get("improved", "")))).strip()
        if resume_service.validate_improvement(resume_text, current, suggested):
            continue
        safe.append({
            "section": str(item.get("section", "Resume")).strip() or "Resume",
            "current": current,
            "suggested": suggested,
            "why": str(item.get("why", item.get("reason", ""))).strip()
                or "Improves clarity while preserving the supplied facts.",
            "confidence": str(item.get("confidence", "")).strip(),
            "factual_basis": str(item.get("factual_basis", "")).strip()
                or "Wording is based only on the supplied resume text.",
        })
    return safe


async def improve_resume(
    resume_text: str,
    target_role: str,
    user_feedback: str,
    mode: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not is_configured():
        return fallback
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    async def request(strict: bool) -> tuple[list[dict[str, str]], bool]:
        payload = {
            "contents": [{
                "parts": [{
                    "text": _improvement_prompt(
                        resume_text, target_role, user_feedback, mode, fallback, strict
                    )
                }]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            body = response.json()
            parsed = _clean_json(body["candidates"][0]["content"]["parts"][0]["text"])
            items = parsed.get("improvements")
            if not isinstance(items, list):
                raise ValueError("Malformed improvement response")
            rejected = any(
                isinstance(item, dict)
                and bool(resume_service.validate_improvement(
                    resume_text,
                    str(item.get("current", item.get("current_text", ""))).strip(),
                    str(item.get("suggested", item.get("suggested_text", item.get("improved", "")))).strip(),
                ))
                for item in items
            )
            return _safe_improvement_items(items, resume_text), rejected

    try:
        safe, rejected = await request(strict=False)
        # A model may return an identical or unsafe pair while still producing
        # valid JSON. Retry once with a stronger instruction before falling back.
        if rejected or not safe:
            safe, _ = await request(strict=True)
        if not safe:
            return fallback
        return {
            "suggestions": safe,
            "instruction": user_feedback,
            "mode": "gemini",
            "analysis_mode": "gemini",
            "analysis_label": "AI-assisted suggestions",
        }
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return fallback
import base64
import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx


GITHUB_API = "https://api.github.com"
CACHE_TTL_SECONDS = 300
_analysis_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class GitHubAPIError(Exception):
    def __init__(self, status_code: int, detail: str, kind: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.kind = kind


def normalize_username(username: str) -> str:
    value = username.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", value):
        raise GitHubAPIError(
            400,
            "Enter a valid GitHub username using 1–39 letters, numbers, or hyphens.",
            "invalid_username",
        )
    return value


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(value: str | None) -> int | None:
    parsed = _parse_date(value)
    if not parsed:
        return None
    return max(0, (datetime.now(timezone.utc) - parsed).days)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", text.lower()))


def _role_terms(target_role: str) -> list[str]:
    return sorted(_tokens(target_role))


def _role_evidence(target_role: str) -> list[str]:
    role = target_role.lower()
    if any(term in role for term in ("java", "spring")):
        return ["Java", "Spring Boot", "REST API", "PostgreSQL", "Docker", "Testing"]
    if any(term in role for term in ("frontend", "front-end", "react", "ui")):
        return ["JavaScript", "TypeScript", "React", "HTML/CSS", "Testing", "Accessibility"]
    if any(term in role for term in ("data", "machine learning", "ml", "analyst")):
        return ["Python", "SQL", "Pandas", "Data visualization", "Testing", "Deployment"]
    if any(term in role for term in ("devops", "platform", "sre", "cloud")):
        return ["Docker", "CI/CD", "Linux", "Cloud", "Observability", "Testing"]
    if any(term in role for term in ("mobile", "android", "ios")):
        return ["Mobile UI", "API integration", "Local storage", "Testing", "Release", "Analytics"]
    return ["Python", "JavaScript", "API", "Database", "Testing", "Deployment"]


def _contains_technology(text: str, technology: str) -> bool:
    low = text.lower()
    aliases = {
        "spring boot": ("spring", "spring boot"),
        "rest api": ("rest", "api", "endpoint"),
        "html/css": ("html", "css"),
        "data visualization": ("visualization", "dashboard", "plotly", "tableau"),
        "ci/cd": ("ci/cd", "github actions", "jenkins", "pipeline"),
        "api integration": ("api", "integration"),
        "local storage": ("sqlite", "local storage", "realm"),
        "observability": ("observability", "prometheus", "grafana", "logging"),
    }
    terms = aliases.get(technology.lower(), (technology.lower(),))
    return any(term in low for term in terms)


def analyze_readme(content: str | None) -> dict[str, Any]:
    if not content:
        return {
            "exists": False,
            "score": 0.0,
            "checks": {
                "description": False, "problem": False, "features": False,
                "technology_stack": False, "setup": False, "usage": False,
                "screenshots_or_demo": False, "architecture": False,
                "api_information": False, "deployment": False,
            },
            "summary": "No README found through the public GitHub API.",
        }

    low = content.lower()
    checks = {
        "description": len(content.strip()) >= 120 or bool(re.search(r"^#{1,3}\s", content, re.MULTILINE)),
        "problem": any(word in low for word in ("problem", "purpose", "solve", "built to")),
        "features": "feature" in low or "what it does" in low,
        "technology_stack": any(word in low for word in ("tech stack", "technologies", "built with", "## stack")),
        "setup": any(word in low for word in ("install", "setup", "getting started", "requirements")),
        "usage": any(word in low for word in ("usage", "run it", "example", "quick start")),
        "screenshots_or_demo": any(word in low for word in ("screenshot", "demo", "live site", "deployed")),
        "architecture": any(word in low for word in ("architecture", "system design", "folder structure")),
        "api_information": any(word in low for word in ("api", "endpoint", "request", "response")),
        "deployment": any(word in low for word in ("deploy", "deployment", "docker", "vercel", "railway")),
    }
    score = round(sum(checks.values()) / len(checks) * 10, 1)
    return {
        "exists": True,
        "score": score,
        "checks": checks,
        "summary": f"{sum(checks.values())}/{len(checks)} useful README signals detected.",
    }


def _activity_score(updated_at: str | None) -> float:
    age = _days_since(updated_at)
    if age is None:
        return 2.0
    if age <= 90:
        return 10.0
    if age <= 365:
        return 8.0
    if age <= 730:
        return 5.0
    return 2.5


def _repo_score(
    repo: dict[str, Any],
    readme: dict[str, Any],
    languages: dict[str, int],
    target_role: str,
) -> tuple[float, dict[str, float], float]:
    description = 10.0 if repo.get("description") else 2.0
    documentation = readme["score"] if readme["exists"] else (4.0 if repo.get("description") else 1.0)
    technical_depth = min(10.0, 3.0 + len(languages) * 1.3 + (1.4 if repo.get("topics") else 0))
    corpus = " ".join([
        repo.get("name", ""),
        repo.get("description") or "",
        " ".join(languages.keys()),
        " ".join(repo.get("topics") or []),
    ])
    role_words = _tokens(target_role)
    corpus_words = _tokens(corpus)
    relevance = 6.0 if not role_words else min(10.0, 3.0 + 7.0 * len(role_words & corpus_words) / len(role_words))
    activity = _activity_score(repo.get("updated_at"))
    originality = 3.0 if repo.get("fork") else (5.0 if repo.get("archived") else 9.0)
    completeness = 4.0
    completeness += 2.0 if repo.get("default_branch") else 0
    completeness += 2.0 if repo.get("size", 0) > 10 else 0
    completeness += 2.0 if languages else 0
    completeness = min(10.0, completeness)
    presentation = min(10.0, 3.0 + (2.0 if repo.get("homepage") else 0) + (2.0 if repo.get("topics") else 0) + (3.0 if repo.get("description") else 0))
    community = min(10.0, 5.0 + (0.8 if repo.get("forks_count", 0) else 0) + (0.5 if repo.get("watchers_count", 0) else 0) + min(1.2, repo.get("stargazers_count", 0) * 0.15))
    breakdown = {
        "documentation": round(documentation, 1),
        "description": round(description, 1),
        "technical_depth": round(technical_depth, 1),
        "technology_relevance": round(relevance, 1),
        "activity": round(activity, 1),
        "originality": round(originality, 1),
        "repository_completeness": round(completeness, 1),
        "presentation": round(presentation, 1),
        "community_signals": round(community, 1),
    }
    # Stars are intentionally capped inside community_signals; they cannot dominate.
    weights = {
        "documentation": .18, "description": .10, "technical_depth": .15,
        "technology_relevance": .12, "activity": .10, "originality": .10,
        "repository_completeness": .10, "presentation": .10, "community_signals": .05,
    }
    score = round(sum(breakdown[key] * weight for key, weight in weights.items()), 1)
    return max(0.0, min(10.0, score)), breakdown, relevance


def _repo_strengths(repo: dict[str, Any], readme: dict[str, Any], score: float, relevance: float) -> list[str]:
    strengths = []
    if repo.get("description"):
        strengths.append("Clear project description")
    if readme["score"] >= 7:
        strengths.append("README explains how to use the project")
    if len(repo.get("languages", {})) >= 2:
        strengths.append("Shows meaningful technical breadth")
    if _activity_score(repo.get("updated_at")) >= 8:
        strengths.append("Recently maintained")
    if relevance >= 7:
        strengths.append("Aligned with the target role")
    return strengths[:3] or ["Original public repository to build on"]


def _repo_weaknesses(repo: dict[str, Any], readme: dict[str, Any], relevance: float) -> list[str]:
    weaknesses = []
    if not repo.get("description"):
        weaknesses.append("Add a concise description")
    if not readme["exists"]:
        weaknesses.append("Add a README with setup and usage")
    elif readme["score"] < 6:
        weaknesses.append("Expand the README beyond a basic overview")
    if _activity_score(repo.get("updated_at")) <= 5:
        weaknesses.append("Show recent maintenance or a clear project status")
    if relevance < 5:
        weaknesses.append("Make the role-relevant technology more visible")
    if repo.get("archived"):
        weaknesses.append("Archived repositories should not lead your portfolio")
    return weaknesses[:3] or ["Add screenshots, results, or deeper technical context"]


def _recommend_projects(target_role: str, evidence: list[dict[str, Any]], repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing = [item["name"] for item in evidence if not item["present"]]
    role = target_role or "your target role"
    primary = next((repo.get("language") for repo in repos if repo.get("language") and repo.get("language") != "Unknown"), "the strongest language in your GitHub")
    recommendations = []
    if missing:
        focus = missing[:3]
        recommendations.append({
            "title": f"Production-ready {role} showcase",
            "problem": f"Many portfolio projects stop before demonstrating {', '.join(focus)}.",
            "why": f"This project closes the most visible GitHub evidence gaps for {role}.",
            "technologies": [primary, *focus],
            "important_features": [f"Demonstrate {item}" for item in focus] + ["Document tradeoffs and measurable results"],
            "difficulty": "Advanced",
            "skills_demonstrated": focus + ["Architecture", "Documentation"],
            "recruiter_takeaway": "You can take a project from working code to a credible production-style portfolio piece.",
            "readme_structure": ["Problem", "Architecture", "Setup", "API or user flow", "Testing", "Deployment", "Tradeoffs"],
        })
    top_name = repos[0].get("name") if repos else "your current project"
    recommendations.append({
        "title": f"Case-study upgrade for {top_name}",
        "problem": "Strong code is difficult to evaluate when the repository does not show decisions, results, and usage clearly.",
        "why": "Turning your best existing work into a complete case study creates more signal without starting from zero.",
        "technologies": [primary, "Markdown", "CI/CD"],
        "important_features": ["Before/after result", "Architecture diagram", "Demo or screenshots", "Automated checks"],
        "difficulty": "Intermediate",
        "skills_demonstrated": ["Technical communication", "Testing", "Project ownership"],
        "recruiter_takeaway": "You understand how to present engineering work, not only write it.",
        "readme_structure": ["One-line pitch", "Demo", "Why it exists", "Architecture", "Local setup", "Results", "Roadmap"],
    })
    recommendations.append({
        "title": f"Small systems experiment for {role}",
        "problem": "A focused experiment can make a missing engineering concern visible without bloating a portfolio.",
        "why": f"Use a narrow, measurable build to add depth around {missing[0] if missing else 'performance and reliability'}.",
        "technologies": [primary, missing[0] if missing else "Observability"],
        "important_features": ["Baseline measurement", "One deliberate improvement", "Short technical write-up"],
        "difficulty": "Intermediate",
        "skills_demonstrated": ["Experiment design", "Debugging", "Evidence-based decisions"],
        "recruiter_takeaway": "You investigate tradeoffs and communicate what changed.",
        "readme_structure": ["Question", "Baseline", "Experiment", "Findings", "Reproduction steps", "Next step"],
    })
    return recommendations


class GitHubService:
    def __init__(self, client: httpx.AsyncClient, token: str = ""):
        self.client = client
        self.token = token
        self._requests: dict[str, Any] = {}

    def _headers(self, raw: bool = False) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "User-Agent": "CareerForge-AI",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
        }

    async def get(self, path: str, raw: bool = False, allow_missing: bool = False) -> Any:
        cache_key = f"{raw}:{path}"
        if cache_key in self._requests:
            return self._requests[cache_key]
        try:
            response = await self.client.get(GITHUB_API + path, headers=self._headers(raw))
        except httpx.RequestError as exc:
            raise GitHubAPIError(502, "GitHub could not be reached. Check the network and try again.", "network") from exc
        if response.status_code == 404 and allow_missing:
            return None
        if response.status_code == 404:
            raise GitHubAPIError(404, "GitHub user or repository not found.", "not_found")
        if response.status_code == 403 and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "rate limit" in response.text.lower()
        ):
            raise GitHubAPIError(429, "GitHub API rate limit reached. Try again later or configure GITHUB_TOKEN.", "rate_limit")
        if response.status_code in (401, 403):
            raise GitHubAPIError(502, "GitHub rejected the public API request. Try again later.", "github_error")
        try:
            response.raise_for_status()
            result = response.text if raw else response.json()
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise GitHubAPIError(502, "GitHub returned an unexpected response. Try again later.", "github_error") from exc
        self._requests[cache_key] = result
        return result

    async def readme(self, owner: str, name: str) -> str | None:
        body = await self.get(f"/repos/{owner}/{name}/readme", allow_missing=True)
        if not body:
            return None
        if isinstance(body, str):
            return body
        encoded = body.get("content", "")
        try:
            return base64.b64decode(encoded).decode("utf-8", errors="ignore")
        except (ValueError, TypeError):
            return None

    async def analyze(self, username: str, target_role: str = "") -> dict[str, Any]:
        username = normalize_username(username)
        cache_key = f"{username.lower()}::{target_role.strip().lower()}"
        cached = _analysis_cache.get(cache_key)
        if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        user = await self.get(f"/users/{username}")
        raw_repos = await self.get(f"/users/{username}/repos?per_page=100&sort=updated&direction=desc")
        original_repos = [repo for repo in raw_repos if not repo.get("fork")]
        original_repos.sort(key=lambda repo: (
            bool(repo.get("description")),
            bool(repo.get("language")),
            repo.get("stargazers_count", 0),
            repo.get("updated_at") or "",
        ), reverse=True)
        # README and language endpoints are the expensive part of an analysis.
        # Inspect the strongest 12 repositories deeply and use public list metadata
        # for the rest so one click cannot burn through the unauthenticated quota.
        important_names = {repo.get("name") for repo in original_repos[:12]}

        analyzed = []
        for repo in original_repos:
            name = repo.get("name", "")
            if name in important_names:
                languages = await self.get(f"/repos/{username}/{name}/languages", allow_missing=True) or {}
                readme = analyze_readme(await self.readme(username, name))
            else:
                primary_language = repo.get("language")
                languages = {primary_language: 1} if primary_language else {}
                readme = analyze_readme(None)
            score, breakdown, relevance = _repo_score(repo, readme, languages, target_role)
            enriched = {
                "name": name,
                "description": repo.get("description") or "",
                "language": repo.get("language") or "Unknown",
                "languages": languages,
                "stars": repo.get("stargazers_count", 0),
                "forks": repo.get("forks_count", 0),
                "watchers": repo.get("watchers_count", 0),
                "size_kb": repo.get("size", 0),
                "updated_at": repo.get("updated_at"),
                "created_at": repo.get("created_at"),
                "topics": repo.get("topics") or [],
                "homepage": repo.get("homepage") or "",
                "default_branch": repo.get("default_branch") or "main",
                "archived": bool(repo.get("archived")),
                "fork": bool(repo.get("fork")),
                "html_url": repo.get("html_url"),
                "readme_url": f"https://github.com/{username}/{name}#readme",
                "readme": readme,
                "score": score,
                "score_breakdown": breakdown,
                "role_relevance": relevance,
            }
            enriched["strengths"] = _repo_strengths(enriched, readme, score, relevance)
            enriched["weaknesses"] = _repo_weaknesses(enriched, readme, relevance)
            enriched["improvements"] = enriched["weaknesses"]
            analyzed.append(enriched)

        analyzed.sort(key=lambda item: item["score"], reverse=True)
        for index, repo in enumerate(analyzed, start=1):
            repo["rank"] = index
            repo["rank_reason"] = (
                "Strongest mix of documentation, technical evidence, activity, and presentation."
                if index == 1 else
                f"Ranks #{index} because its overall portfolio signal is behind the repositories above it."
            )

        recent_repos = [repo for repo in analyzed if _activity_score(repo.get("updated_at")) >= 8]
        activity_score = 8.0 if recent_repos else (5.0 if analyzed else 2.0)
        profile_fields = [
            bool(user.get("login")), bool(user.get("name")), bool(user.get("bio")),
            bool(user.get("html_url")), bool(user.get("avatar_url")), bool(user.get("public_repos")),
        ]
        profile_completeness = round(sum(profile_fields) / len(profile_fields) * 10, 1)
        profile_score = round(min(10, profile_completeness * .8 + (1.5 if user.get("followers", 0) else .5) + (.5 if recent_repos else 0)), 1)
        repository_score = round(sum(repo["score"] for repo in analyzed) / len(analyzed), 1) if analyzed else 2.0
        documentation_score = round(sum(repo["readme"]["score"] for repo in analyzed) / len(analyzed), 1) if analyzed else 0.0
        role_alignment = round(sum(repo["role_relevance"] for repo in analyzed) / len(analyzed), 1) if analyzed else 2.0
        categories = {
            "profile_signal": profile_score,
            "repository_quality": repository_score,
            "documentation": documentation_score,
            "activity": activity_score,
            "role_alignment": role_alignment,
        }
        overall = round(sum(categories.values()) / len(categories), 1)
        corpus = " ".join(
            [repo["name"] + " " + repo["description"] + " " + repo["language"] + " " + " ".join(repo["languages"].keys()) + " " + " ".join(repo["topics"]) for repo in analyzed]
        )
        evidence = [{"name": item, "present": _contains_technology(corpus, item)} for item in _role_evidence(target_role)]
        missing = [item["name"] for item in evidence if not item["present"]]
        best = analyzed[0] if analyzed else None
        recruiter = {
            "strongest_signal": f"{best['name']} scores {best['score']}/10 with {best['readme']['score']}/10 documentation." if best else "No original public repository was found.",
            "biggest_concern": "The profile has limited public evidence to evaluate." if not analyzed else (best["weaknesses"][0] if best["weaknesses"] else "The portfolio needs more visible outcomes."),
            "missing_evidence": f"Make {', '.join(missing[:3])} visible in a project or README." if missing else "No major technology evidence gap was detected from public metadata.",
            "portfolio_credibility": "Early-stage public footprint" if overall < 5 else ("Credible foundation with room to sharpen" if overall < 7.5 else "Strong public portfolio signal"),
            "technology_alignment": f"{len(evidence) - len(missing)}/{len(evidence)} target signals found." if evidence else "Add a target role to compare technology alignment.",
        }
        highlighted = [repo["name"] for repo in analyzed[:3]]
        not_highlighted = [repo["name"] for repo in analyzed[3:]]
        pinning = {
            "recommended": highlighted,
            "first": highlighted[0] if highlighted else None,
            "do_not_highlight": not_highlighted,
        }
        language_totals: dict[str, int] = {}
        for repo in analyzed:
            for language, byte_count in repo["languages"].items():
                language_totals[language] = language_totals.get(language, 0) + byte_count

        result = {
            "profile": {
                "login": user.get("login"),
                "name": user.get("name"),
                "bio": user.get("bio"),
                "profile_url": user.get("html_url"),
                "followers": user.get("followers", 0),
                "following": user.get("following", 0),
                "public_repos": user.get("public_repos", 0),
                "account_activity": {"recent_original_repositories": len(recent_repos), "last_updated": analyzed[0].get("updated_at") if analyzed else None},
                "completeness": profile_completeness,
                "score": profile_score,
            },
            "username": username,
            "target_role": target_role,
            "score": overall,
            "categories": categories,
            "repositories": analyzed,
            "repository_count": len(analyzed),
            "language_summary": [{"name": name, "bytes": count} for name, count in Counter(language_totals).most_common(8)],
            "best_repository": best,
            "pinning": pinning,
            "recruiter_view": recruiter,
            "recruiter_disclaimer": "AI-generated recruiter-style simulation — not an actual recruiter's opinion.",
            "technology_evidence": evidence,
            "portfolio_gaps": missing,
            "recommended_projects": _recommend_projects(target_role, evidence, analyzed),
            "scoring_note": "Repository scores weight documentation, technical depth, relevance, activity, completeness, and presentation. Stars contribute only a capped community signal.",
            "issues": (
                ["Add a concise GitHub bio focused on your target role."] if not user.get("bio") else []
            ) + (
                ["Build and pin 2–3 strong original projects."] if len(analyzed) < 3 else []
            ) + ([f"Make {', '.join(missing[:3])} visible in project evidence."] if missing else []),
        }
        _analysis_cache[cache_key] = (time.time(), result)
        return result


async def analyze_github(username: str, target_role: str = "", token: str = "") -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        return await GitHubService(client, token=token).analyze(username, target_role)
"""Personalized project recommendations built from the user's real career evidence."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from services import ai_service


_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 300

ROLE_PROFILES = {
    "java_backend": {
        "label": "Java Backend Developer",
        "terms": ("java", "spring", "backend", "microservices", "jvm"),
        "requirements": ("Java", "Spring Boot", "REST APIs", "SQL", "Testing", "Docker", "Cloud", "CI/CD"),
        "default_stack": ("Java", "Spring Boot", "PostgreSQL", "Docker", "JUnit", "GitHub Actions"),
    },
    "python_backend": {
        "label": "Python Backend Developer",
        "terms": ("python", "django", "fastapi", "flask", "backend", "api"),
        "requirements": ("Python", "REST APIs", "SQL", "Testing", "Docker", "Cloud", "CI/CD"),
        "default_stack": ("Python", "FastAPI", "PostgreSQL", "Docker", "Pytest", "GitHub Actions"),
    },
    "frontend": {
        "label": "Frontend Developer",
        "terms": ("frontend", "front-end", "react", "vue", "angular", "ui", "web designer"),
        "requirements": ("HTML/CSS", "JavaScript", "Component architecture", "Accessibility", "Testing", "Performance", "Deployment"),
        "default_stack": ("React", "TypeScript", "Vite", "Playwright", "CSS", "Vercel"),
    },
    "fullstack": {
        "label": "Full-Stack Developer",
        "terms": ("fullstack", "full-stack", "full stack", "web developer"),
        "requirements": ("Frontend", "REST APIs", "SQL", "Authentication", "Testing", "Deployment", "CI/CD"),
        "default_stack": ("React", "TypeScript", "FastAPI", "PostgreSQL", "Docker", "GitHub Actions"),
    },
    "data_ml": {
        "label": "Data / Machine Learning Engineer",
        "terms": ("data", "machine learning", "ml", "analytics", "ai", "data scientist"),
        "requirements": ("Python", "Data pipelines", "SQL", "Model evaluation", "Testing", "Deployment", "Monitoring"),
        "default_stack": ("Python", "Pandas", "scikit-learn", "FastAPI", "PostgreSQL", "Docker"),
    },
    "devops": {
        "label": "DevOps / Cloud Engineer",
        "terms": ("devops", "cloud", "sre", "platform", "infrastructure", "site reliability"),
        "requirements": ("Linux", "Docker", "Cloud", "Infrastructure as code", "CI/CD", "Monitoring", "Security"),
        "default_stack": ("Linux", "Docker", "Terraform", "GitHub Actions", "AWS", "Prometheus"),
    },
    "mobile": {
        "label": "Mobile Developer",
        "terms": ("mobile", "android", "ios", "flutter", "react native", "swift", "kotlin"),
        "requirements": ("Mobile UI", "State management", "API integration", "Testing", "Offline support", "Release process"),
        "default_stack": ("React Native", "TypeScript", "Expo", "FastAPI", "SQLite", "EAS"),
    },
    "general": {
        "label": "Software Developer",
        "terms": (),
        "requirements": ("Programming", "APIs", "Data persistence", "Testing", "Deployment", "Documentation"),
        "default_stack": ("JavaScript", "Python", "REST APIs", "SQLite", "Docker", "GitHub Actions"),
    },
}

SIGNAL_ALIASES = {
    "java": ("java", "jvm", "spring"),
    "spring boot": ("spring", "spring boot"),
    "python": ("python", "django", "fastapi", "flask"),
    "javascript": ("javascript", "typescript", "node", "react", "vue", "angular"),
    "html/css": ("html", "css", "tailwind", "bootstrap"),
    "frontend": ("frontend", "front-end", "react", "vue", "angular", "html", "css"),
    "rest apis": ("rest", "api", "fastapi", "flask", "spring boot", "express"),
    "sql": ("sql", "postgres", "postgresql", "mysql", "sqlite", "database"),
    "testing": ("test", "testing", "pytest", "junit", "jest", "playwright", "cypress"),
    "docker": ("docker", "container", "kubernetes"),
    "cloud": ("aws", "azure", "gcp", "cloud", "vercel", "render", "railway", "heroku"),
    "ci/cd": ("ci/cd", "github actions", "gitlab ci", "jenkins", "pipeline"),
    "accessibility": ("accessibility", "wcag", "aria", "screen reader"),
    "performance": ("performance", "lighthouse", "caching", "optimization", "optimized"),
    "deployment": ("deploy", "deployment", "production", "hosting"),
    "monitoring": ("monitor", "observability", "prometheus", "grafana", "logging"),
    "authentication": ("auth", "authentication", "oauth", "jwt", "login"),
    "data pipelines": ("pipeline", "etl", "airflow", "spark", "streaming"),
    "model evaluation": ("model evaluation", "precision", "recall", "f1", "validation"),
    "infrastructure as code": ("terraform", "pulumi", "cloudformation", "infrastructure as code"),
    "security": ("security", "owasp", "secrets", "vulnerability"),
    "documentation": ("readme", "documentation", "architecture", "setup"),
}

GAP_WHY = {
    "Testing": "Tests turn a working demo into evidence that you can protect behavior as a codebase changes.",
    "Docker": "Containerization shows that your project can be run consistently outside your laptop.",
    "Cloud": "A live deployment gives recruiters proof that you understand the path from code to a usable product.",
    "CI/CD": "Automated checks and delivery show an engineering workflow beyond writing features locally.",
    "Accessibility": "Accessible interfaces demonstrate product maturity and attention to users often missed in portfolio demos.",
    "Performance": "Measured performance turns visual polish into engineering evidence with an outcome recruiters can verify.",
    "Monitoring": "Operational visibility shows you can reason about software after it ships.",
    "Model evaluation": "Evaluation evidence separates a machine-learning experiment from a trustworthy applied system.",
    "Documentation": "A clear README makes your strongest work easy to assess in the short time a recruiter has.",
    "Deployment": "Deployment evidence makes the project feel complete rather than stopping at a local prototype.",
}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        clean = _text(value)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def _words(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(_words(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_words(item) for item in value.values())
    return _text(value).lower()


def _role_profile(role: str) -> tuple[str, dict[str, Any]]:
    role_lower = role.lower()
    for key, profile in ROLE_PROFILES.items():
        if key == "general":
            continue
        if any(term in role_lower for term in profile["terms"]):
            return key, profile
    return "general", ROLE_PROFILES["general"]


def _profile_input(context: dict[str, Any]) -> dict[str, Any]:
    profile = context.get("profile") if isinstance(context.get("profile"), dict) else {}
    nested = profile.get("input") if isinstance(profile.get("input"), dict) else {}
    return nested or profile


def _profile_analysis(context: dict[str, Any]) -> dict[str, Any]:
    profile = context.get("profile") if isinstance(context.get("profile"), dict) else {}
    nested = profile.get("analysis") if isinstance(profile.get("analysis"), dict) else {}
    return nested or profile


def _normalise_context(raw: dict[str, Any]) -> dict[str, Any]:
    profile_input = _profile_input(raw)
    profile_analysis = _profile_analysis(raw)
    github = raw.get("github") if isinstance(raw.get("github"), dict) else {}
    resume = raw.get("resume") if isinstance(raw.get("resume"), dict) else {}

    target_role = (
        _text(raw.get("target_role"))
        or _text(profile_input.get("target_role"))
        or _text(github.get("target_role"))
        or "Software Developer"
    )
    skills = _unique(
        list(raw.get("skills") or [])
        + list(profile_input.get("skills") or [])
        + list(resume.get("skills") or [])
    )
    repositories = github.get("repositories") if isinstance(github.get("repositories"), list) else []
    languages = []
    for repository in repositories:
        if isinstance(repository, dict):
            languages.extend((repository.get("languages") or {}).keys())
            if repository.get("language"):
                languages.append(repository["language"])
    languages.extend(github.get("languages") or [])

    return {
        "target_role": target_role,
        "skills": _unique(skills),
        "profile": {
            "input": profile_input,
            "analysis": profile_analysis,
        },
        "github": {
            "username": _text(github.get("username")),
            "score": github.get("score", raw.get("github_score", 0)),
            "languages": _unique(languages),
            "repositories": repositories[:12],
            "repository_count": github.get("repository_count", len(repositories)),
            "best_repository": github.get("best_repository") or {},
            "portfolio_gaps": github.get("portfolio_gaps") or [],
            "technology_evidence": github.get("technology_evidence") or [],
            "categories": github.get("categories") or {},
        },
        "resume": {
            "score": resume.get("score", raw.get("resume_score", 0)),
            "skills": _unique(resume.get("skills") or []),
            "projects": resume.get("projects") or "",
            "experience": resume.get("experience") or "",
            "text": _text(resume.get("text")),
            "recommendations": resume.get("recommendations") or [],
            "categories": resume.get("categories") or {},
        },
        "scores": {
            "profile": profile_analysis.get("score", raw.get("profile_score", 0)),
            "github": github.get("score", raw.get("github_score", 0)),
            "resume": resume.get("score", raw.get("resume_score", 0)),
        },
    }


def _evidence_corpus(context: dict[str, Any]) -> str:
    profile_input = context["profile"]["input"]
    profile_analysis = context["profile"]["analysis"]
    github = context["github"]
    resume = context["resume"]
    parts = [
        _words(context["target_role"]),
        _words(context["skills"]),
        _words(profile_input),
        _words(profile_analysis.get("strengths")),
        _words(profile_analysis.get("recommendations")),
        _words(github.get("languages")),
        _words(github.get("technology_evidence")),
        _words(github.get("repositories")),
        _words(github.get("best_repository")),
        _words(github.get("categories")),
        _words(resume),
    ]
    return " ".join(parts)


def _has_signal(signal: str, corpus: str) -> bool:
    aliases = SIGNAL_ALIASES.get(signal.lower(), (signal.lower(),))
    return any(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", corpus) for alias in aliases)


def _role_gap(context: dict[str, Any], role_profile: dict[str, Any]) -> dict[str, Any]:
    corpus = _evidence_corpus(context)
    requirements = list(role_profile["requirements"])
    demonstrated = [item for item in requirements if _has_signal(item, corpus)]
    missing = [item for item in requirements if item not in demonstrated]
    github = context["github"]
    if github.get("repository_count", 0) == 0 and "Original public projects" not in missing:
        missing.insert(0, "Original public projects")
    if not github.get("technology_evidence") and "Technology evidence" not in missing:
        missing.append("Technology evidence")

    priority_order = (
        "Original public projects", "Testing", "Docker", "Cloud", "Deployment",
        "CI/CD", "Monitoring", "Accessibility", "Performance", "Model evaluation",
        "Documentation", "Technology evidence",
    )
    biggest = next((item for item in priority_order if item in missing), missing[0] if missing else "Production depth")
    repo_count = github.get("repository_count", 0)
    current_evidence = []
    if context["skills"]:
        current_evidence.append("Skills listed: " + ", ".join(context["skills"][:7]))
    if github.get("languages"):
        current_evidence.append("GitHub languages: " + ", ".join(github["languages"][:6]))
    if repo_count:
        current_evidence.append(f"{repo_count} original public repositories analyzed")
    if context["resume"].get("score"):
        current_evidence.append(f"Resume analysis score: {context['resume']['score']}/10")
    if not current_evidence:
        current_evidence.append("There is not enough submitted evidence yet.")

    why = GAP_WHY.get(biggest, f"{biggest} is one of the clearest signals for {context['target_role']}.")
    evidence_to_add = {
        "Original public projects": "A complete, role-specific repository with a clear README, tests, and a live demo.",
        "Technology evidence": f"An end-to-end project that uses {', '.join(role_profile['default_stack'][:4])}.",
        "Production depth": "A complete release path with tests, deployment, documentation, and measured outcomes.",
    }.get(biggest, f"Visible {biggest.lower()} evidence inside code, tests, deployment configuration, and the README.")

    return {
        "role_requirements": requirements,
        "demonstrated": demonstrated,
        "missing": missing,
        "biggest": {
            "name": biggest,
            "why_it_matters": why,
            "current_evidence": current_evidence,
            "evidence_to_add": evidence_to_add,
        },
    }


def _stage(context: dict[str, Any]) -> str:
    text = _evidence_corpus(context)
    if any(term in text for term in ("student", "fresher", "entry level", "intern")):
        return "early-career"
    if context["github"].get("repository_count", 0) >= 6 or context["resume"].get("experience"):
        return "developing professional"
    return "early-career"


def _role_noun(role: str) -> str:
    clean = re.sub(r"\b(developer|engineer|specialist|professional)\b", "", role, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or "Developer"


def _stack(role_profile: dict[str, Any], context: dict[str, Any], additions: tuple[str, ...] = ()) -> list[str]:
    actual = context["skills"] + context["github"]["languages"]
    selected = []
    for item in list(actual) + list(role_profile["default_stack"]) + list(additions):
        if item.lower() not in {value.lower() for value in selected}:
            selected.append(item)
    return selected[:8]


def _score(values: dict[str, float]) -> tuple[float, dict[str, float]]:
    weights = {
        "role_alignment": 0.20,
        "skill_gap_coverage": 0.20,
        "portfolio_value": 0.15,
        "technical_depth": 0.15,
        "uniqueness": 0.10,
        "recruiter_signal": 0.10,
        "feasibility": 0.10,
    }
    breakdown = {key: round(max(0, min(10, values.get(key, 0))), 1) for key in weights}
    return round(sum(breakdown[key] * weight for key, weight in weights.items()), 1), breakdown


def _blueprint(title: str, stack: list[str], core: list[str], advanced: list[str], role: str) -> dict[str, Any]:
    backend = next((item for item in stack if item.lower() in {"fastapi", "django", "flask", "spring boot"}), "REST API service")
    database = next((item for item in stack if item.lower() in {"postgresql", "postgres", "mysql", "sqlite"}), "PostgreSQL")
    frontend = next((item for item in stack if item.lower() in {"react", "typescript", "javascript", "html/css"}), "Responsive web client")
    return {
        "problem_statement": f"Build {title} to solve a concrete workflow problem for people working with {role.lower()} data and decisions.",
        "target_users": "Job seekers, hiring teams, or technical users who need a reliable and explainable workflow.",
        "core_features": core,
        "advanced_features": advanced,
        "technology_stack": {
            "frontend": frontend,
            "backend": f"{backend} behind a documented REST API",
            "database": database,
            "authentication": "JWT or OAuth with protected user-owned resources",
            "apis": "REST endpoints with validation, pagination, and useful error responses",
            "deployment": "Dockerized service deployed to Render, Railway, Fly.io, or an equivalent low-cost host",
            "testing": "Unit tests, API integration tests, and one end-to-end happy path",
        },
        "architecture": "Frontend → REST API → backend services → database, with background jobs for imports or long-running analysis.",
        "database_design": [
            "users(id, email, created_at)",
            "projects(id, user_id, title, status, created_at)",
            "events(id, project_id, event_type, payload, created_at)",
            "evaluations(id, project_id, metric, value, created_at)",
        ],
        "api_design": [
            "POST /api/auth/login",
            "GET /api/projects",
            "POST /api/projects",
            "GET /api/projects/{id}",
            "POST /api/projects/{id}/evaluate",
            "GET /api/projects/{id}/events",
        ],
        "folder_structure": [
            "frontend/",
            "backend/main.py",
            "backend/services/",
            "backend/models/",
            "backend/tests/",
            "README.md",
            "Dockerfile",
        ],
        "roadmap": [
            "Phase 1 — Define the user workflow and data model",
            "Phase 2 — Ship the core API and first usable screen",
            "Phase 3 — Add validation, tests, and role-specific evidence",
            "Phase 4 — Add deployment, observability, and failure handling",
            "Phase 5 — Document the architecture and publish a demo",
        ],
        "testing_strategy": "Test validation and authorization at the API boundary, service logic with fixtures, database relationships, failure states, and one browser-level critical flow.",
        "deployment": "Use a free or low-cost frontend host plus Render, Railway, Fly.io, or a small cloud service for the API and managed PostgreSQL where needed.",
        "readme_structure": [
            "Project overview",
            "Features",
            "Screenshots and demo",
            "Tech stack",
            "Architecture",
            "Installation",
            "Usage",
            "API documentation",
            "Database design",
            "Testing",
            "Deployment",
            "Future improvements",
        ],
    }


def _candidate(
    *,
    title: str,
    description: str,
    why: str,
    gap: str,
    stack: list[str],
    core: list[str],
    advanced: list[str],
    skills: list[str],
    difficulty: str,
    complexity: str,
    scores: dict[str, float],
    role: str,
    recruiter_value: str,
) -> dict[str, Any]:
    score, breakdown = _score(scores)
    blueprint = _blueprint(title, stack, core, advanced, role)
    return {
        "title": title,
        "description": description,
        "one_line_description": description,
        "portfolio_value": f"Adds visible evidence of {gap.lower()}, product judgment, and a complete delivery path.",
        "difficulty": difficulty,
        "estimated_development_complexity": complexity,
        "complexity": complexity,
        "technologies": stack,
        "stack": stack,
        "why": why,
        "portfolio_gap": gap,
        "gap_fixes": [gap, "Documentation", "Production depth"],
        "skills_demonstrated": _unique(skills),
        "core_features": core,
        "important_features": core,
        "advanced_features": advanced,
        "recruiter_value": recruiter_value,
        "recruiter_takeaway": recruiter_value,
        "before": {
            "demonstrates": [gap if gap in scores and scores.get("skill_gap_coverage", 0) < 8 else "Existing technical foundation"],
            "missing": [gap, "A complete public delivery story"],
        },
        "after": {
            "demonstrates": _unique([gap, *skills, "Tests", "Deployment", "Documentation"]),
            "evidence_to_publish": ["Source code", "Tests", "Architecture diagram", "README", "Live demo or screenshots"],
        },
        "score": score,
        "score_breakdown": breakdown,
        "blueprint": blueprint,
    }


def _build_candidates(context: dict[str, Any], role_key: str, role_profile: dict[str, Any], gap: dict[str, Any]) -> list[dict[str, Any]]:
    role = context["target_role"]
    noun = _role_noun(role)
    biggest = gap["biggest"]["name"]
    base_stack = _stack(role_profile, context)
    core_common = ["Role-based workflow", "Input validation", "Search and filtering", "Useful empty and error states"]
    candidates: list[dict[str, Any]] = []

    if role_key in {"java_backend", "python_backend", "fullstack"}:
        api_name = "Spring Boot" if role_key == "java_backend" else "FastAPI"
        candidates.append(_candidate(
            title=f"{api_name} {noun} Operations Platform",
            description=f"A production-shaped platform that helps teams track, evaluate, and act on {noun.lower()} workflows.",
            why=f"It turns your current {', '.join(context['skills'][:2]) or 'development'} evidence into a complete service with the missing {biggest.lower()} signal.",
            gap=biggest,
            stack=_stack(role_profile, context, ("Docker", "PostgreSQL", "GitHub Actions")),
            core=core_common + ["Create and update workflow records", "Audit trail for important changes"],
            advanced=["Background processing", "Role-based access control", "Rate limiting and API observability"],
            skills=[api_name, "REST APIs", "SQL", "Testing", "Docker", "CI/CD"],
            difficulty="Advanced",
            complexity="4–6 weeks for a polished portfolio release",
            scores={"role_alignment": 9.6, "skill_gap_coverage": 9.5, "portfolio_value": 9.4, "technical_depth": 9.2, "uniqueness": 8.0, "recruiter_signal": 9.4, "feasibility": 7.7},
            role=role,
            recruiter_value="Signals API design, persistence, validation, tests, deployment, and the ability to think beyond a CRUD demo.",
        ))
        candidates.append(_candidate(
            title=f"Test-First {noun} Reliability Lab",
            description=f"A measurable test and failure-analysis workspace for a {noun.lower()} service.",
            why=f"Your portfolio can show features; this project makes the less visible {biggest.lower()} engineering discipline impossible to miss.",
            gap="Testing" if "Testing" in gap["missing"] else biggest,
            stack=_stack(role_profile, context, ("Pytest" if role_key == "python_backend" else "JUnit", "Docker", "GitHub Actions")),
            core=["Define service contracts", "Run regression suites", "Compare baseline and changed behavior", "Show failure explanations"],
            advanced=["Mutation testing", "Contract-test fixtures", "CI quality gate with coverage trend"],
            skills=[api_name, "Testing", "CI/CD", "API design", "Observability"],
            difficulty="Advanced",
            complexity="3–5 weeks for a strong first release",
            scores={"role_alignment": 9.2, "skill_gap_coverage": 9.8 if "Testing" in gap["missing"] else 8.7, "portfolio_value": 9.1, "technical_depth": 9.4, "uniqueness": 8.7, "recruiter_signal": 9.5, "feasibility": 8.0},
            role=role,
            recruiter_value="A recruiter sees engineering rigor: contracts, repeatable verification, quality gates, and failure-aware design.",
        ))
    elif role_key == "frontend":
        candidates.append(_candidate(
            title=f"Accessible {noun} Workflow Studio",
            description=f"A polished, keyboard-first web product that makes a complex {noun.lower()} workflow easy to complete.",
            why=f"It gives your frontend work a stronger {biggest.lower()} signal while preserving the UI strength you already demonstrate.",
            gap=biggest,
            stack=_stack(role_profile, context, ("TypeScript", "Playwright", "Vite")),
            core=["Responsive workflow screens", "Keyboard navigation", "Accessible form validation", "Loading, error, and empty states"],
            advanced=["WCAG audit report", "Performance budget", "Reusable component library"],
            skills=["Component architecture", "Accessibility", "Performance", "Testing", "Deployment"],
            difficulty="Intermediate",
            complexity="2–4 weeks for a polished portfolio release",
            scores={"role_alignment": 9.6, "skill_gap_coverage": 9.6 if biggest in {"Accessibility", "Performance", "Testing"} else 8.6, "portfolio_value": 9.2, "technical_depth": 8.6, "uniqueness": 8.5, "recruiter_signal": 9.2, "feasibility": 9.0},
            role=role,
            recruiter_value="Shows that your interface decisions are supported by accessibility, performance, testing, and reusable architecture evidence.",
        ))
        candidates.append(_candidate(
            title=f"Performance-Tracked {noun} Dashboard",
            description=f"A data-rich dashboard with real user-facing performance measurements and a documented design system.",
            why=f"It converts visual polish into measurable {biggest.lower()} evidence and gives reviewers a project they can inspect quickly.",
            gap="Performance" if "Performance" in gap["missing"] else biggest,
            stack=_stack(role_profile, context, ("TypeScript", "Playwright", "Lighthouse CI")),
            core=["Dashboard with filtering and drill-down", "Reusable charts and tables", "Responsive layouts", "Performance score panel"],
            advanced=["Virtualized large lists", "Offline-friendly caching", "Visual regression checks"],
            skills=["JavaScript", "Component architecture", "Performance", "Testing", "Data visualization"],
            difficulty="Intermediate",
            complexity="2–4 weeks for a strong first release",
            scores={"role_alignment": 9.3, "skill_gap_coverage": 9.7 if "Performance" in gap["missing"] else 8.5, "portfolio_value": 9.0, "technical_depth": 8.8, "uniqueness": 8.4, "recruiter_signal": 9.0, "feasibility": 8.9},
            role=role,
            recruiter_value="Gives a technical reviewer concrete evidence of performance thinking instead of relying only on screenshots.",
        ))
    elif role_key == "data_ml":
        candidates.append(_candidate(
            title=f"Evaluated {noun} Decision Pipeline",
            description=f"An end-to-end data product that turns messy inputs into explainable {noun.lower()} decisions.",
            why=f"It closes the gap between notebooks and production evidence by making {biggest.lower()} part of the product itself.",
            gap=biggest,
            stack=_stack(role_profile, context, ("Pandas", "scikit-learn", "MLflow", "Docker")),
            core=["Data ingestion and validation", "Reproducible transformation pipeline", "Explainable result view", "Dataset quality report"],
            advanced=["Model comparison", "Drift detection", "Scheduled retraining job"],
            skills=["Python", "Data pipelines", "SQL", "Model evaluation", "API design", "Deployment"],
            difficulty="Advanced",
            complexity="4–6 weeks for a portfolio-grade release",
            scores={"role_alignment": 9.7, "skill_gap_coverage": 9.6, "portfolio_value": 9.5, "technical_depth": 9.5, "uniqueness": 8.8, "recruiter_signal": 9.6, "feasibility": 7.6},
            role=role,
            recruiter_value="Shows the full path from data quality to evaluation, serving, and monitoring rather than only a model score.",
        ))
        candidates.append(_candidate(
            title=f"Data Quality Observatory for {noun}",
            description=f"A monitoring workspace that makes pipeline health, missingness, drift, and data freshness visible.",
            why=f"Data quality is a high-signal way to add {biggest.lower()} evidence without repeating another generic prediction demo.",
            gap="Monitoring" if "Monitoring" in gap["missing"] else biggest,
            stack=_stack(role_profile, context, ("Pandas", "PostgreSQL", "Prometheus", "Docker")),
            core=["Dataset profiling", "Freshness and schema checks", "Quality score history", "Alert explanations"],
            advanced=["Anomaly detection", "Webhook notifications", "Role-based dashboards"],
            skills=["Python", "SQL", "Data pipelines", "Monitoring", "Testing"],
            difficulty="Advanced",
            complexity="3–5 weeks for a strong first release",
            scores={"role_alignment": 9.4, "skill_gap_coverage": 9.7 if "Monitoring" in gap["missing"] else 8.8, "portfolio_value": 9.2, "technical_depth": 9.3, "uniqueness": 9.0, "recruiter_signal": 9.4, "feasibility": 8.0},
            role=role,
            recruiter_value="Demonstrates the operational thinking that separates a data experiment from a dependable data product.",
        ))
    elif role_key == "devops":
        candidates.append(_candidate(
            title=f"Self-Service Delivery Platform for {noun}",
            description=f"A small internal platform that standardizes service deployment, checks, rollback, and release visibility.",
            why=f"It directly adds the missing {biggest.lower()} evidence expected in platform work and produces artifacts recruiters can inspect.",
            gap=biggest,
            stack=_stack(role_profile, context, ("Terraform", "Docker", "GitHub Actions", "Prometheus")),
            core=["Service registration", "Environment configuration", "Deployment status", "Rollback checklist"],
            advanced=["Infrastructure as code", "Policy checks", "OpenTelemetry traces", "Cost-aware environment controls"],
            skills=["Docker", "Cloud", "Infrastructure as code", "CI/CD", "Monitoring", "Security"],
            difficulty="Advanced",
            complexity="4–6 weeks for a portfolio-grade release",
            scores={"role_alignment": 9.8, "skill_gap_coverage": 9.8, "portfolio_value": 9.5, "technical_depth": 9.7, "uniqueness": 9.0, "recruiter_signal": 9.7, "feasibility": 7.3},
            role=role,
            recruiter_value="Shows production ownership: repeatable infrastructure, delivery controls, observability, and safe failure handling.",
        ))
        candidates.append(_candidate(
            title=f"Incident Readiness Lab for {noun}",
            description=f"A sandbox that injects service failures and measures detection, diagnosis, and recovery.",
            why=f"It makes your operational judgment visible and targets the difference between listing cloud tools and proving you can run systems.",
            gap="Monitoring" if "Monitoring" in gap["missing"] else biggest,
            stack=_stack(role_profile, context, ("Docker", "Prometheus", "Grafana", "GitHub Actions")),
            core=["Synthetic service checks", "Failure injection scenarios", "Alert routing", "Incident timeline"],
            advanced=["SLO dashboards", "Runbook suggestions", "Post-incident report generator"],
            skills=["Linux", "Docker", "Monitoring", "CI/CD", "Incident response"],
            difficulty="Advanced",
            complexity="3–5 weeks for a strong first release",
            scores={"role_alignment": 9.5, "skill_gap_coverage": 9.5 if "Monitoring" in gap["missing"] else 8.7, "portfolio_value": 9.3, "technical_depth": 9.6, "uniqueness": 9.2, "recruiter_signal": 9.5, "feasibility": 8.0},
            role=role,
            recruiter_value="A technical recruiter can see measurable operational scenarios rather than a static infrastructure diagram.",
        ))
    elif role_key == "mobile":
        candidates.append(_candidate(
            title=f"Offline-First {noun} Companion",
            description=f"A mobile workflow that remains useful offline, syncs safely, and exposes the reliability decisions behind it.",
            why=f"It adds a differentiated {biggest.lower()} signal while giving your mobile work a complete product narrative.",
            gap=biggest,
            stack=_stack(role_profile, context, ("React Native", "Expo", "SQLite", "EAS")),
            core=["Offline create and edit", "Sync status", "Conflict-safe updates", "Accessible mobile navigation"],
            advanced=["Push notifications", "Background sync", "Crash reporting dashboard"],
            skills=["Mobile UI", "State management", "API integration", "Offline support", "Testing"],
            difficulty="Advanced",
            complexity="3–5 weeks for a portfolio-grade release",
            scores={"role_alignment": 9.6, "skill_gap_coverage": 9.4, "portfolio_value": 9.3, "technical_depth": 9.2, "uniqueness": 8.9, "recruiter_signal": 9.3, "feasibility": 8.0},
            role=role,
            recruiter_value="Shows mobile-specific product judgment: reliability, state, sync, accessibility, and release discipline.",
        ))
        candidates.append(_candidate(
            title=f"Release-Ready {noun} Field App",
            description=f"A focused mobile app with analytics, API integration, test coverage, and a documented release process.",
            why=f"It makes the missing {biggest.lower()} evidence visible without repeating a basic mobile UI clone.",
            gap=biggest,
            stack=_stack(role_profile, context, ("React Native", "Expo", "FastAPI", "EAS")),
            core=["Role-specific mobile workflow", "Secure API integration", "Usage analytics", "Loading and failure states"],
            advanced=["Deep links", "Feature flags", "Automated preview builds"],
            skills=["Mobile UI", "API integration", "Authentication", "Testing", "Release process"],
            difficulty="Intermediate",
            complexity="2–4 weeks for a strong first release",
            scores={"role_alignment": 9.2, "skill_gap_coverage": 9.3, "portfolio_value": 8.9, "technical_depth": 8.7, "uniqueness": 8.5, "recruiter_signal": 9.0, "feasibility": 8.7},
            role=role,
            recruiter_value="Shows a shippable mobile product with real integration and release evidence, not only a screen collection.",
        ))
    else:
        candidates.append(_candidate(
            title=f"Evidence-First {noun} Portfolio Platform",
            description=f"A focused product that turns a real {noun.lower()} workflow into measurable, documented software.",
            why=f"It is anchored to your target role and closes the biggest detected gap: {biggest.lower()}.",
            gap=biggest,
            stack=_stack(role_profile, context, ("Docker", "PostgreSQL", "GitHub Actions")),
            core=core_common + ["Track measurable outcomes", "Export a shareable project report"],
            advanced=["Authentication", "Background jobs", "Public demo mode", "Audit history"],
            skills=["Programming", "APIs", "Data persistence", "Testing", "Deployment", "Documentation"],
            difficulty="Intermediate",
            complexity="3–5 weeks for a polished portfolio release",
            scores={"role_alignment": 9.0, "skill_gap_coverage": 9.2, "portfolio_value": 9.1, "technical_depth": 8.7, "uniqueness": 8.3, "recruiter_signal": 9.0, "feasibility": 8.6},
            role=role,
            recruiter_value="Creates one coherent repository where a reviewer can inspect product thinking, code quality, tests, and delivery.",
        ))
        candidates.append(_candidate(
            title=f"Production Signals Lab for {noun}",
            description=f"A compact system that measures quality, usage, and reliability for a {noun.lower()} workflow.",
            why=f"It adds {biggest.lower()} evidence in a way that complements—rather than duplicates—your current projects.",
            gap=biggest,
            stack=_stack(role_profile, context, ("Docker", "SQLite", "GitHub Actions", "OpenTelemetry")),
            core=["Define measurable signals", "Collect events", "Show trend dashboard", "Document trade-offs"],
            advanced=["Alert thresholds", "Synthetic checks", "Pluggable adapters"],
            skills=["APIs", "Testing", "Deployment", "Monitoring", "Documentation"],
            difficulty="Advanced",
            complexity="3–5 weeks for a strong first release",
            scores={"role_alignment": 8.8, "skill_gap_coverage": 9.4, "portfolio_value": 9.0, "technical_depth": 9.1, "uniqueness": 9.0, "recruiter_signal": 9.2, "feasibility": 8.0},
            role=role,
            recruiter_value="Adds measurable engineering evidence and gives interviewers meaningful design trade-offs to discuss.",
        ))

    # Every role receives a third and fourth option, but their wording and stack are
    # derived from the role, existing evidence, and the current gap.
    candidates.append(_candidate(
        title=f"Documentation-First {noun} Reference App",
        description=f"A small but complete reference implementation that teaches the architecture of a {noun.lower()} system.",
        why=f"If your current work is difficult to evaluate quickly, this creates a clean public proof point for {biggest.lower()} and documentation.",
        gap="Documentation" if "Documentation" in gap["missing"] else biggest,
        stack=_stack(role_profile, context, ("Docker",)),
        core=["Clear domain model", "Small end-to-end workflow", "Architecture diagram", "Runnable setup"],
        advanced=["Decision records", "API examples", "Test fixtures", "Demo dataset"],
        skills=["Architecture", "Documentation", "Testing", *role_profile["requirements"][:2]],
        difficulty="Intermediate",
        complexity="2–3 weeks for a polished reference release",
        scores={"role_alignment": 8.6, "skill_gap_coverage": 8.8, "portfolio_value": 8.7, "technical_depth": 8.0, "uniqueness": 8.8, "recruiter_signal": 8.9, "feasibility": 9.5},
        role=role,
        recruiter_value="Lets a reviewer understand your engineering decisions quickly and gives the rest of your portfolio a quality benchmark.",
    ))
    candidates.append(_candidate(
        title=f"Open-Source Ready {noun} Toolkit",
        description=f"A reusable package or service extracted from a real {noun.lower()} problem, with examples and contribution guidance.",
        why=f"It creates a distinctive public artifact and strengthens the missing {biggest.lower()} signal through reuse, tests, and documentation.",
        gap=biggest,
        stack=_stack(role_profile, context, ("GitHub Actions", "Docker")),
        core=["Reusable core module", "Example application", "Validation and error handling", "Versioned documentation"],
        advanced=["Package publishing", "Compatibility matrix", "Contribution workflow", "Automated release notes"],
        skills=["API design", "Testing", "CI/CD", "Documentation", "Open-source workflow"],
        difficulty="Advanced",
        complexity="3–5 weeks for a credible public release",
        scores={"role_alignment": 8.5, "skill_gap_coverage": 9.0, "portfolio_value": 9.2, "technical_depth": 8.9, "uniqueness": 9.5, "recruiter_signal": 9.1, "feasibility": 7.8},
        role=role,
        recruiter_value="Signals that you can design for other developers, maintain compatibility, and communicate technical decisions publicly.",
    ))

    current_signals = _unique(gap["demonstrated"] + context["skills"] + context["github"]["languages"])
    for item in candidates:
        item["before"]["demonstrates"] = current_signals[:7] or ["The submitted profile foundation"]
        item["before"]["missing"] = _unique([item["portfolio_gap"], *gap["missing"][:3], "A complete public delivery story"])[:5]

    candidates.sort(key=lambda item: item["score"], reverse=True)
    for index, item in enumerate(candidates[:4], start=1):
        item["rank"] = index
    return candidates[:4]


def _recruiter_view(context: dict[str, Any], gap: dict[str, Any], projects: list[dict[str, Any]]) -> dict[str, str]:
    github = context["github"]
    best = github.get("best_repository") or {}
    best_name = best.get("name") if isinstance(best, dict) else ""
    return {
        "strongest_signal": (
            f"{best_name} is currently the strongest public repository signal."
            if best_name else
            f"Your clearest current signal is {', '.join(gap['demonstrated'][:3]) or 'the skills you listed'}."
        ),
        "biggest_weakness": f"{gap['biggest']['name']} is not yet visible enough for {context['target_role']}.",
        "missing_evidence": gap["biggest"]["evidence_to_add"],
        "technical_depth": f"The recommended top project adds {', '.join(projects[0]['skills_demonstrated'][:5])}.",
        "role_alignment": f"The project set is tuned to {context['target_role']} rather than a generic project list.",
        "project_credibility": "A recruiter can verify the claim through source code, tests, README evidence, and a live demo or screenshots.",
    }


def _fallback(context: dict[str, Any]) -> dict[str, Any]:
    role_key, role_profile = _role_profile(context["target_role"])
    gap = _role_gap(context, role_profile)
    projects = _build_candidates(context, role_key, role_profile, gap)
    best = projects[0] if projects else None
    return {
        "target_role": context["target_role"],
        "career_stage": _stage(context),
        "available_sources": {
            "profile": bool(context["profile"]["input"] or context["profile"]["analysis"]),
            "github": bool(context["github"]["username"] or context["github"]["repository_count"]),
            "resume": bool(context["resume"].get("score") or context["resume"].get("recommendations")),
        },
        "career_gap": {
            "demonstrated": gap["demonstrated"],
            "missing": gap["missing"],
            "role_requirements": gap["role_requirements"],
            "biggest": gap["biggest"],
        },
        "best_project": best,
        "projects": projects,
        "recruiter_view": _recruiter_view(context, gap, projects),
        "recruiter_disclaimer": "Recruiter perspective is an AI-generated estimate and does not represent an actual recruiter's opinion.",
        "scoring_method": {
            "Role Alignment": "20%",
            "Skill Gap Coverage": "20%",
            "Portfolio Value": "15%",
            "Technical Depth": "15%",
            "Uniqueness": "10%",
            "Recruiter Signal": "10%",
            "Feasibility": "10%",
        },
        "scoring_note": "Scores are deterministic and balance role fit, missing-signal coverage, technical depth, recruiter evidence, uniqueness, and feasibility. GitHub stars do not determine project quality.",
        "mode": "rule-based",
        "analysis_label": "Rule-based recommendation",
    }


def _cache_key(context: dict[str, Any]) -> str:
    payload = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def recommend_projects(raw_context: dict[str, Any]) -> dict[str, Any]:
    context = _normalise_context(raw_context)
    key = _cache_key(context)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    fallback = _fallback(context)
    result = await ai_service.analyze_projects(context, fallback)
    _CACHE[key] = (time.monotonic(), result)
    return result
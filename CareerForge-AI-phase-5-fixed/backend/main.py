import os
import io
import re
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from docx import Document
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from fastapi.responses import StreamingResponse

load_dotenv()
from services import ai_service, github_service
from services.github_service import GitHubAPIError
from services import project_service
from services import resume_service

app = FastAPI(title="CareerForge AI API", version="1.0.0")

origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5500")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin, "http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
class ProfileRequest(BaseModel):
    name: str = ""
    headline: str = ""
    about: str = ""
    skills: list[str] = []
    education: str = ""
    experience: str = ""
    projects: str = ""
    target_role: str = ""
    profile_url: str = ""


class ProjectRequest(BaseModel):
    target_role: str = ""
    skills: list[str] = Field(default_factory=list)
    github_score: float = 0
    resume_score: float = 0
    profile_score: float = 0
    profile: dict[str, Any] = Field(default_factory=dict)
    github: dict[str, Any] = Field(default_factory=dict)
    resume: dict[str, Any] = Field(default_factory=dict)


class ResumeImproveRequest(BaseModel):
    resume_text: str
    target_role: str = ""
    user_feedback: str = ""
    mode: str = ""


class ResumeAnalyzeRequest(BaseModel):
    resume_text: str
    target_role: str = ""


class ResumeEditValidateRequest(BaseModel):
    resume_text: str
    current_text: str = ""
    suggested_text: str


def score_profile(data: ProfileRequest):
    all_text = " ".join([
        data.name, data.headline, data.about, data.education,
        data.experience, data.projects, data.profile_url,
        " ".join(data.skills),
    ])
    target_words = set(re.findall(r"[a-z0-9+#.]+", data.target_role.lower()))
    profile_words = set(re.findall(r"[a-z0-9+#.]+", all_text.lower()))
    fields = {
        "name": bool(data.name.strip()),
        "headline": bool(data.headline.strip()),
        "about": bool(data.about.strip()),
        "skills": len(data.skills) >= 3,
        "education": bool(data.education.strip()),
        "experience": bool(data.experience.strip()),
        "projects": bool(data.projects.strip()),
        "target_role": bool(data.target_role.strip()),
        "profile_url": bool(data.profile_url.strip()),
    }
    completeness = round(sum(fields.values()) / len(fields) * 10, 1)

    bonuses = 0
    text = " ".join([data.headline, data.about, data.experience, data.projects]).lower()
    if re.search(r"\b\d+%|\b\d+\+|\b\d+\s*(users|projects|customers|requests)\b", text):
        bonuses += 0.6
    if len(data.about.split()) >= 50:
        bonuses += 0.4
    if len(data.skills) >= 6:
        bonuses += 0.4

    alignment = 3.0 if not target_words else round(
        min(10, 4 + 6 * len(target_words & profile_words) / len(target_words)), 1
    )
    readability = 4.0
    if len(data.headline.split()) <= 16 and data.headline.strip():
        readability += 1.5
    if 35 <= len(data.about.split()) <= 130:
        readability += 1.5
    if re.search(r"[.!?]", data.experience + data.projects):
        readability += 1.0
    score = round(min(10, (
        completeness * 0.27
        + (10 if fields["headline"] else 2) * 0.12
        + (8 if len(data.about.split()) >= 50 else 4) * 0.12
        + min(10, len(data.skills) * 1.5) * 0.12
        + (8 if fields["experience"] else 3) * 0.10
        + (9 if fields["projects"] else 2) * 0.10
        + alignment * 0.10
        + min(10, readability) * 0.07
        + bonuses
    )), 1)
    suggestions = []

    if not data.name:
        suggestions.append("Add your full name so the profile has a clear identity.")
    if not data.headline:
        suggestions.append("Add a role-focused headline that names your target role and strongest technologies.")
    if len(data.about.split()) < 50:
        suggestions.append("Expand the About section with your focus area, strongest skills, projects, and career direction.")
    if len(data.skills) < 5:
        suggestions.append("Add relevant technical and tooling skills you can actually demonstrate.")
    if not data.projects:
        suggestions.append("Add 2–3 strong projects with technologies, features, and measurable outcomes.")
    if not re.search(r"\b\d+%|\b\d+\+|\b\d+\s*(users|projects|customers|requests)\b", text):
        suggestions.append("Add measurable impact to experience/project bullets where truthful.")
    if not data.profile_url:
        suggestions.append("Add a public profile URL, such as LinkedIn or a portfolio, if you have one.")

    changes = []
    if not data.headline:
        changes.append({
            "section": "Headline",
            "current": "[headline is empty]",
            "improved": f"{data.target_role or 'Target role'} | "
                        f"{', '.join(data.skills[:3]) or 'Core skills'} | "
                        "Building practical, measurable solutions",
            "reason": "A focused headline helps a recruiter understand your direction in one scan.",
        })
    if len(data.about.split()) < 50:
        changes.append({
            "section": "About",
            "current": data.about.strip() or "[about section is empty]",
            "improved": (
                f"I am a {data.target_role or 'software professional'} focused on "
                f"{', '.join(data.skills[:4]) or 'building reliable products'}. "
                "I enjoy turning practical problems into clear, maintainable solutions. "
                "I am currently strengthening my portfolio through hands-on projects and "
                "looking for opportunities where I can contribute and keep growing."
            ),
            "reason": "This structure connects role, skills, motivation, and direction without overstating experience.",
        })
    if not data.projects:
        changes.append({
            "section": "Projects",
            "current": "[projects section is empty]",
            "improved": "Project name — technology | Built [what it does] to solve [problem]. "
                        "Implemented [feature] and measured [truthful outcome].",
            "reason": "Project evidence gives recruiters something concrete to evaluate.",
        })

    return {
        "score": score,
        "categories": {
            "profile_completeness": completeness,
            "headline": 10 if fields["headline"] else 2,
            "about": 8 if len(data.about.split()) >= 50 else 4,
            "skills": min(10, len(data.skills) * 1.5),
            "experience": 8 if fields["experience"] else 3,
            "projects": 9 if fields["projects"] else 2,
            "target_role_alignment": alignment,
            "recruiter_readability": round(min(10, readability), 1),
        },
        "strengths": [k.replace("_", " ").title() for k, v in fields.items() if v][:5] or ["A profile ready to improve"],
        "weaknesses": [k.replace("_", " ").title() for k, v in fields.items() if not v],
        "recommendations": suggestions[:7],
        "recruiter_assessment": (
            "AI-generated recruiter-style simulation: the profile has a usable foundation, "
            "but clarity, evidence of impact, and role alignment should be strengthened."
        ),
        "disclaimer": "AI-generated recruiter-style simulation — not a real recruiter's opinion.",
        "suggestions": changes,
        "mode": "rule-based",
        "analysis_label": "Rule-based analysis",
    }


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "ai_configured": ai_service.is_configured(),
        "analysis_mode": "gemini" if ai_service.is_configured() else "rule-based",
    }


@app.post("/api/analyze-profile")
async def analyze_profile(data: ProfileRequest):
    fallback = score_profile(data)
    return await ai_service.analyze_profile(data.dict(), fallback)


@app.get("/api/github/{username}")
async def analyze_github(username: str, target_role: str = ""):
    try:
        return await github_service.analyze_github(
            username,
            target_role=target_role.strip(),
            token=GITHUB_TOKEN,
        )
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/analyze-resume")
async def analyze_resume(file: UploadFile = File(...), target_role: str = Form("")):
    data = await file.read()
    if len(data) > resume_service.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Resume must be smaller than 8 MB.")
    if not data:
        raise HTTPException(400, "The uploaded resume is empty.")
    try:
        text = resume_service.extract_resume(file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not text.strip():
        raise HTTPException(
            400,
            "Could not extract readable text from this resume. Try an accessible PDF, DOCX, or TXT file.",
        )
    fallback = resume_service.analyze_resume_text(text, target_role.strip())
    return await ai_service.analyze_resume(
        {"original_text": text, "target_role": target_role.strip()},
        fallback,
    )


@app.post("/api/reanalyze-resume")
async def reanalyze_resume(data: ResumeAnalyzeRequest):
    text = data.resume_text.strip()
    if not text:
        raise HTTPException(400, "Resume text cannot be empty.")
    if len(text.encode("utf-8")) > resume_service.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Resume must be smaller than 8 MB.")
    fallback = resume_service.analyze_resume_text(text, data.target_role.strip())
    return await ai_service.analyze_resume(
        {"original_text": text, "target_role": data.target_role.strip()},
        fallback,
    )


@app.post("/api/improve-resume")
async def improve_resume(data: ResumeImproveRequest):
    text = data.resume_text.strip()
    if not text:
        raise HTTPException(400, "Resume text cannot be empty.")
    if len(text.encode("utf-8")) > resume_service.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Resume must be smaller than 8 MB.")
    target = data.target_role.strip()
    feedback = data.user_feedback.strip()
    fallback = resume_service.build_improvement_fallback(
        text, target, feedback, data.mode.strip()
    )
    return await ai_service.improve_resume(text, target, feedback, data.mode.strip(), fallback)


@app.post("/api/validate-resume-edit")
async def validate_resume_edit(data: ResumeEditValidateRequest):
    text = data.resume_text.strip()
    if not text:
        raise HTTPException(400, "Resume text cannot be empty.")
    errors = resume_service.validate_improvement(
        text, data.current_text, data.suggested_text
    )
    return {"valid": not errors, "errors": errors}


@app.post("/api/generate-projects")
async def generate_projects(data: ProjectRequest):
    """Backward-compatible route for the upgraded personalized recommendation engine."""
    return await project_service.recommend_projects(data.dict())


@app.post("/api/export-resume/pdf")
def export_pdf(data: ResumeImproveRequest):
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45)
    story = []
    for line in data.resume_text.splitlines():
        if line.strip():
            story.append(Paragraph(line.replace("&", "&amp;"), styles["BodyText"]))
            story.append(Spacer(1, 5))
    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=CareerForge_Resume.pdf"}
    )


@app.post("/api/export-resume/docx")
def export_docx(data: ResumeImproveRequest):
    doc = Document()
    for line in data.resume_text.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=CareerForge_Resume.docx"}
    )

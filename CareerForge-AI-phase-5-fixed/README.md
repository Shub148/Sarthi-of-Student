# CareerForge AI

A full-stack starter for an AI-powered career profile, GitHub, resume, and personalized portfolio project analyzer.

## Stack
- Frontend: HTML, CSS, JavaScript
- Backend: Python + FastAPI
- GitHub: public REST API
- AI: optional Gemini API (set GEMINI_API_KEY)
- Project intelligence: deterministic role-gap analysis with optional Gemini refinement
- Resume parsing: PDF + DOCX + TXT
- Resume export: PDF + DOCX

## Run

### 1. Backend
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload
```

### 2. Frontend
Open `frontend/index.html` in a browser, or serve the project:
```bash
python -m http.server 5500 -d frontend
```
Then visit http://localhost:5500

The frontend expects the API at http://127.0.0.1:8000.

## Project intelligence

The Project Suggestions page uses any available Profile, GitHub, and Resume analysis
alongside the target role and skills. It ranks 3–4 project blueprints against a
transparent score made from role alignment, gap coverage, portfolio value, technical
depth, uniqueness, recruiter signal, and feasibility.

The existing compatibility endpoint is:
```text
POST /api/generate-projects
```

Without Gemini, the endpoint remains fully usable in rule-based mode. It does not
use GitHub stars as a substitute for project quality.

## Phase 5 resume lab

The Resume Analyzer now provides content-based scoring across ATS-style compatibility,
content quality, role alignment, skills, experience, projects, achievements, structure,
keyword coverage, and readability. It detects available sections, compares evidence with
the target role, reviews bullets/projects/experience, and includes a clearly labeled
AI-generated recruiter-style simulation.

The Resume Improvement Lab keeps the original extracted text separate from a working
copy. Suggestions are generated for modes including ATS Optimize, Recruiter Optimize,
Target Role, One Page, Stronger Bullets, Project Focus, and Skills/keyword review.
Each suggestion can be accepted, edited, or rejected; accepted and edited changes are
re-analyzed from the updated working text. No suggestion is applied automatically.

The main resume endpoints are:

```text
POST /api/analyze-resume       multipart file + target_role
POST /api/reanalyze-resume     JSON resume_text + target_role
POST /api/improve-resume       JSON resume_text + target_role + user_feedback + mode
POST /api/validate-resume-edit JSON resume_text + current_text + suggested_text
```

## AI
AI is optional. Without an AI key, the app still provides deterministic GitHub scoring and resume/profile rule-based analysis.

Resume analysis reports `analysis_mode` as `gemini` only after a successful Gemini
response; provider failures and missing keys report `rule-based`. Improvement
suggestions are checked for meaningful differences and unsupported factual details
before they reach the UI.

For Gemini:
- Put `GEMINI_API_KEY=...` in `backend/.env`
- Restart FastAPI.

## Notes
- GitHub public API requests are real.
- Resume files are processed in memory and are not persisted by this starter.
- The resume export endpoints generate downloadable files.
- This is a strong MVP foundation; production deployment should add authentication, persistent database storage, rate limiting, and secure cloud file storage.

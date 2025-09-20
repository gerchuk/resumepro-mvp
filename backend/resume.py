from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os, json, re

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# ---------------- Heuristic parsing helpers (no-OpenAI fallback) ----------------
SECTION_HEADERS = {
    "experience": {"experience", "work experience", "professional experience", "employment history", "career history"},
    "education": {"education", "academic history", "academics"},
    "skills": {"skills", "technical skills", "key skills"},
    "certifications": {"certifications", "licenses", "licences", "certs"},
    "projects": {"projects", "selected projects"},
    "summary": {"summary", "professional summary", "profile"},
}

PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s\(\)]{7,}\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def detect_section(line: str) -> Optional[str]:
    t = normalize(line).lower().strip(": ")
    for key, names in SECTION_HEADERS.items():
        if t in names:
            return key
    if line.isupper() and len(line) <= 40:
        if "EDUCATION" in line:
            return "education"
        if "SKILL" in line:
            return "skills"
        if "CERT" in line or "LICENSE" in line or "LICENCE" in line:
            return "certifications"
        if "PROJECT" in line:
            return "projects"
        if "SUMMARY" in line or "PROFILE" in line:
            return "summary"
        if "EXPERIENCE" in line or "EMPLOY" in line or "CAREER" in line:
            return "experience"
    return None

def split_lines(text: str) -> List[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [l.rstrip() for l in text.split("\n")]

def extract_contacts(text: str) -> str:
    phones = set(PHONE_RE.findall(text))
    emails = set(EMAIL_RE.findall(text))
    parts = []
    if emails:
        parts.append(" / ".join(sorted(emails)))
    if phones:
        parts.append(" / ".join(sorted(phones)))
    return " | ".join(parts)

def collect_bullets(lines: List[str]) -> List[str]:
    out = []
    for l in lines:
        m = re.match(r"^\s*[-•*]\s+(.*)$", l)
        if m:
            out.append(normalize(m.group(1)))
    return out

def heuristic_parse(text: str) -> Dict[str, Any]:
    lines = [l for l in (x.strip() for x in split_lines(text)) if l]
    if not lines:
        return {"full_name": "", "contact_info": "", "summary": "", "work_experience": [], "education": [], "skills": [], "certifications": []}

    full_name = normalize(lines[0])
    contact_info = extract_contacts(text)

    current = None
    buckets: Dict[str, List[str]] = {"experience": [], "education": [], "skills": [], "certifications": [], "summary": [], "projects": []}
    for l in lines[1:]:
        sec = detect_section(l)
        if sec:
            current = sec
            continue
        if current:
            buckets[current].append(l)
        else:
            buckets["summary"].append(l)

    summary = normalize(" ".join([x for x in buckets["summary"] if not x.startswith(("-", "•", "*"))]))[:600]

    exp_bullets = collect_bullets(buckets["experience"])
    work_experience: List[Dict[str, Any]] = []
    if exp_bullets:
        work_experience.append({"job_title": "", "company": "", "start_date": "", "end_date": "", "achievements": exp_bullets})

    education_entries: List[Dict[str, str]] = []
    if buckets["education"]:
        chunk = []
        for l in buckets["education"]:
            if re.match(r"^\s*[-•*]\s+", l):
                chunk.append(normalize(re.sub(r"^\s*[-•*]\s+", "", l)))
            else:
                chunk.append(normalize(l))
        if chunk:
            education_entries.append({"institution": " / ".join(chunk)[:200], "degree": "", "year": ""})

    skills_set = set()
    for l in buckets["skills"]:
        if re.match(r"^\s*[-•*]\s+", l):
            skills_set.add(normalize(re.sub(r"^\s*[-•*]\s+", "", l)))
        else:
            if "," in l:
                for part in l.split(","):
                    part = normalize(part)
                    if part:
                        skills_set.add(part)
            else:
                skills_set.add(normalize(l))
    skills_list = [s for s in skills_set if s]
    certs = [normalize(re.sub(r"^\s*[-•*]\s+", "", l)) for l in buckets["certifications"]]

    return {"full_name": full_name, "contact_info": contact_info, "summary": summary, "work_experience": work_experience, "education": education_entries, "skills": skills_list, "certifications": certs}

# ---------------- Models ----------------
class ParseResult(BaseModel):
    parsed: Dict[str, Any]

class RewriteRequest(BaseModel):
    parsed: Dict[str, Any]
    job_title: Optional[str] = None
    company: Optional[str] = None
    job_description: Optional[str] = None
    tone: Optional[str] = "professional"
    seniority: Optional[str] = None  # e.g., "senior", "manager", etc.

class RewriteResponse(BaseModel):
    rewritten: Dict[str, Any]
    resume_text: str
    used_openai: bool

class CoverLetterRequest(BaseModel):
    parsed: Dict[str, Any]
    job_title: str
    company: Optional[str] = None
    job_description: Optional[str] = None
    tone: Optional[str] = "confident"
    max_words: Optional[int] = 250

class CoverLetterResponse(BaseModel):
    cover_letter: str
    used_openai: bool

# ---------------- Helpers ----------------
async def gpt_chat(messages: List[Dict[str, str]], temperature: float = 0.2) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None
    try:
        import httpx
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": OPENAI_MODEL, "messages": messages, "temperature": temperature}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(OPENAI_URL, json=payload, headers=headers)
            if r.status_code != 200:
                return None
            data = r.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None

def render_resume_text(parsed: Dict[str, Any]) -> str:
    lines = []
    name = parsed.get("full_name") or ""
    contact = parsed.get("contact_info") or ""
    if name: lines.append(name)
    if contact: lines.append(contact)
    if parsed.get("summary"):
        lines += ["", "SUMMARY", parsed["summary"]]
    if parsed.get("skills"):
        lines += ["", "SKILLS", ", ".join(parsed["skills"])]
    for edu in parsed.get("education", []):
        parts = [edu.get("degree"), edu.get("institution"), edu.get("year")]
        lines += ["", "EDUCATION", " — ".join([p for p in parts if p])]
    for exp in parsed.get("work_experience", []):
        header = " — ".join([x for x in [exp.get("job_title"), exp.get("company")] if x])
        if header:
            lines += ["", header]
        for a in exp.get("achievements", []):
            lines.append(f"• {a}")
    return "\n".join([l for l in lines if l is not None])

def local_rewrite(parsed: Dict[str, Any]) -> Dict[str, Any]:
    # Very basic: title-case name, trim long bullets, ensure bullets start with verb-y style.
    out = json.loads(json.dumps(parsed))  # deep copy
    if out.get("full_name"):
        out["full_name"] = " ".join([w.capitalize() for w in out["full_name"].split()])
    for exp in out.get("work_experience", []):
        new_ach = []
        for b in exp.get("achievements", []):
            bb = b.strip()
            bb = re.sub(r"^\s*(?:-|\*|•)\s*", "", bb)
            bb = bb[0].upper() + bb[1:] if bb else bb
            if len(bb) > 180:
                bb = bb[:177] + "..."
            new_ach.append(bb)
        exp["achievements"] = new_ach
    return out

# ---------------- Routes ----------------
@router.post("/parse", response_model=ParseResult)
async def parse_resume(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        text = raw.decode("latin-1", errors="ignore")

    # Try OpenAI first; fall back to heuristic
    if OPENAI_API_KEY:
        sys_prompt = (
            "Extract resume JSON with fields: full_name, contact_info, summary, "
            "work_experience (array of {job_title, company, start_date, end_date, achievements[]}), "
            "education, skills, certifications. Return ONLY JSON."
        )
        content = await gpt_chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            temperature=0.0
        )
        if content:
            try:
                return {"parsed": json.loads(content)}
            except Exception:
                m = re.search(r"\{[\s\S]*\}$", (content or "").strip())
                if m:
                    return {"parsed": json.loads(m.group(0))}
    # Fallback
    return {"parsed": heuristic_parse(text)}

@router.post("/rewrite", response_model=RewriteResponse)
async def rewrite_resume(body: RewriteRequest):
    sys_rules = (
        "You are ResumePro, an elite resume writer. Improve clarity, impact, and ATS keyword match. "
        "Rules: Do NOT invent facts. Keep bullets to <=2 lines each. Use strong, varied action verbs. "
        "Quantify only when the input provides a number or clear estimate. Return ONLY JSON with "
        "the same schema as the input: full_name, contact_info, summary, work_experience "
        "(array of {job_title, company, start_date, end_date, achievements[]}), education, skills, certifications. "
        "After that, also include a field resume_text that is a clean printable resume."
    )

    user_context = {
        "parsed": body.parsed,
        "target_role": body.job_title,
        "company": body.company,
        "job_description": body.job_description,
        "tone": body.tone,
        "seniority": body.seniority,
    }
    used_openai = False
    content = await gpt_chat(
        [{"role": "system", "content": sys_rules},
         {"role": "user", "content": json.dumps(user_context)}],
        temperature=0.2
    )
    if content:
        try:
            data = json.loads(content)
            rewritten = data
            if "resume_text" not in rewritten:
                rewritten["resume_text"] = render_resume_text(rewritten)
            used_openai = True
            return {"rewritten": rewritten, "resume_text": rewritten["resume_text"], "used_openai": used_openai}
        except Exception:
            pass

    # Fallback: local tidy-up
    rewritten = local_rewrite(body.parsed)
    resume_text = render_resume_text(rewritten)
    return {"rewritten": rewritten, "resume_text": resume_text, "used_openai": used_openai}

@router.post("/cover-letter", response_model=CoverLetterResponse)
async def cover_letter(body: CoverLetterRequest):
    sys_rules = (
        "You are ResumePro, an elite career coach. Write a concise, specific cover letter tailored "
        "to the job. Use a confident, warm, and professional tone. Avoid clichés. "
        "Use 2–4 short paragraphs; maximum word count as provided. "
        "Return ONLY the final letter as plain text, no JSON."
    )
    user_payload = {
        "candidate": body.parsed,
        "job_title": body.job_title,
        "company": body.company,
        "job_description": body.job_description,
        "tone": body.tone,
        "max_words": body.max_words,
    }
    used_openai = False
    content = await gpt_chat(
        [{"role": "system", "content": sys_rules},
         {"role": "user", "content": json.dumps(user_payload)}],
        temperature=0.5
    )
    if content:
        # trim to max words if model exceeds
        if body.max_words:
            words = content.split()
            if len(words) > body.max_words:
                content = " ".join(words[:body.max_words])
        used_openai = True
        return {"cover_letter": content.strip(), "used_openai": used_openai}

    # Fallback template
    name = (body.parsed.get("full_name") or "Candidate").title()
    contact = body.parsed.get("contact_info") or ""
    summary = body.parsed.get("summary") or ""
    role = body.job_title or "the role"
    company = body.company or "your company"

    templ = f"""Dear Hiring Manager,

I’m excited to apply for {role} at {company}. {summary[:180]}

In my experience, I’ve delivered results by:
- { (body.parsed.get('work_experience') or [{}])[0].get('achievements', ['—'])[0] if (body.parsed.get('work_experience') or []) else '—' }

I would welcome the chance to discuss how I can contribute. Thank you for your time.

Sincerely,
{name}
{contact}"""
    return {"cover_letter": templ.strip(), "used_openai": False}

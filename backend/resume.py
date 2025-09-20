from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os, json, re

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

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
    # also catch ALL CAPS headings
    if line.isupper() and len(line) <= 40:
        # heuristically map
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
    # keep visual bullets on their own lines
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
        return {
            "full_name": "",
            "contact_info": "",
            "summary": "",
            "work_experience": [],
            "education": [],
            "skills": [],
            "certifications": [],
        }

    # First line as name (common pattern)
    full_name = normalize(lines[0])

    # Contacts anywhere in the doc
    contact_info = extract_contacts(text)

    # Walk sections
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
            # preface lines before any section → often summary
            buckets["summary"].append(l)

    # Build structured fields
    summary = normalize(" ".join([x for x in buckets["summary"] if not x.startswith(("-", "•", "*"))]))[:600]

    # Experience: collect bullets only (simple but useful)
    exp_bullets = collect_bullets(buckets["experience"])
    work_experience: List[Dict[str, Any]] = []
    if exp_bullets:
        work_experience.append({
            "job_title": "",
            "company": "",
            "start_date": "",
            "end_date": "",
            "achievements": exp_bullets
        })

    # Education: lines condensed
    education_entries: List[Dict[str, str]] = []
    if buckets["education"]:
        # naive split by bullets or blank lines
        chunk = []
        for l in buckets["education"]:
            if re.match(r"^\s*[-•*]\s+", l):
                chunk.append(normalize(re.sub(r"^\s*[-•*]\s+", "", l)))
            else:
                chunk.append(normalize(l))
        if chunk:
            education_entries.append({"institution": " / ".join(chunk)[:200], "degree": "", "year": ""})

    # Skills: from bullets or comma-separated line
    skills_set = set()
    for l in buckets["skills"]:
        if re.match(r"^\s*[-•*]\s+", l):
            skills_set.add(normalize(re.sub(r"^\s*[-•*]\s+", "", l)))
        else:
            # split commas
            if "," in l:
                for part in l.split(","):
                    part = normalize(part)
                    if part:
                        skills_set.add(part)
            else:
                skills_set.add(normalize(l))
    skills_list = [s for s in skills_set if s]

    # Certs: as lines
    certs = [normalize(re.sub(r"^\s*[-•*]\s+", "", l)) for l in buckets["certifications"]]

    return {
        "full_name": full_name,
        "contact_info": contact_info,
        "summary": summary,
        "work_experience": work_experience,
        "education": education_entries,
        "skills": skills_list,
        "certifications": certs
    }

class ParseResult(BaseModel):
    parsed: Dict[str, Any]

@router.post("/parse", response_model=ParseResult)
async def parse_resume(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        text = raw.decode("latin-1", errors="ignore")

    # If OpenAI key exists, you can try it first — but fall back to heuristic
    if OPENAI_API_KEY:
        try:
            import httpx
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            system_prompt = (
                "Extract resume JSON with fields: full_name, contact_info, summary, "
                "work_experience (array of {job_title, company, start_date, end_date, achievements[]}), "
                "education, skills, certifications. Return ONLY JSON."
            )
            payload = {
                "model": "gpt-5",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.0
            }
            async with httpx.AsyncClient(timeout=25) as client:
                r = await client.post(OPENAI_URL, json=payload, headers=headers)
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"]
                    try:
                        parsed = json.loads(content)
                    except Exception:
                        m = re.search(r"\{[\s\S]*\}$", content.strip())
                        if not m:
                            raise ValueError("Model did not return JSON")
                        parsed = json.loads(m.group(0))
                    return {"parsed": parsed}
        except Exception:
            pass  # fall back below

    return {"parsed": heuristic_parse(text)}

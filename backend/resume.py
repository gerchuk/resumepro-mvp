from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os, json, re, tempfile, pathlib

router = APIRouter()

# Env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_URL     = "https://api.openai.com/v1/chat/completions"

# ------------------------------ TEXT EXTRACTION (.txt/.docx/.pdf) ------------------------------
def extract_text_from_upload(upload: UploadFile) -> str:
    """Extract readable text from txt/docx/pdf. Falls back to best-effort decode."""
    filename = (upload.filename or "").lower()
    suffix = pathlib.Path(filename).suffix

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".bin") as tmp:
        raw = upload.file.read()
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        if suffix == ".txt":
            for enc in ("utf-8", "latin-1"):
                try:
                    return raw.decode(enc, errors="ignore")
                except Exception:
                    pass
            return raw.decode("utf-8", errors="ignore")

        if suffix == ".docx":
            try:
                from docx import Document  # python-docx
                doc = Document(tmp_path)
                return "\n".join([p.text for p in doc.paragraphs if p.text and p.text.strip()])
            except Exception:
                pass  # fall through to best-effort

        if suffix == ".pdf":
            try:
                import pdfplumber
                parts: List[str] = []
                with pdfplumber.open(tmp_path) as pdf:
                    for page in pdf.pages:
                        t = page.extract_text() or ""
                        if t.strip():
                            parts.append(t)
                return "\n".join(parts)
            except Exception:
                pass  # fall through to best-effort

        # Unknown: best-effort as text
        for enc in ("utf-8", "latin-1"):
            try:
                return raw.decode(enc, errors="ignore")
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

# ------------------------------ HEURISTIC PARSER (clean & robust) ------------------------------
UPPER_HDRS = {
    "experience": {"experience","work experience","professional experience","employment history","career history"},
    "education": {"education","academic history","academics"},
    "skills": {"skills","technical skills","key skills"},
    "certifications": {"certifications","licenses","licences","certs"},
    "projects": {"projects","selected projects","notable projects"},
    "summary": {"summary","professional summary","profile","objective"},
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\-\s\(\)]{6,}\d")  # min 8 digits including separators

DEGREE_TOKENS = ("bsc","msc","mba","phd","ba","ma","b\.a\.","m\.a\.","bba","be","me","m\.sc\.","b\.sc\.")
UNIVERSITY_HINTS = ("university","institute","college","school","insead","oxford","harvard","stanford")

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _only_letters_and_space(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z \-'.]{1,80}", s or ""))

def _likely_name(line: str) -> bool:
    if not line: return False
    l = line.strip()
    if len(l) < 3 or len(l) > 80: return False
    if l.isupper() and len(l.split()) <= 4:  # many resumes have all-caps names
        return True
    if _only_letters_and_space(l) and len(l.split()) in (2,3,4):
        return True
    return False

def _first_nonempty_lines(text: str, n: int = 20) -> List[str]:
    out = []
    for ln in text.splitlines():
        if ln.strip():
            out.append(ln.strip())
        if len(out) >= n:
            break
    return out

def _detect_section(line: str) -> Optional[str]:
    t = _norm(line).lower().strip(" :")
    for key, names in UPPER_HDRS.items():
        if t in names: return key
    if line.isupper() and len(line) <= 40:
        if "EDUCATION" in line: return "education"
        if "SKILL" in line: return "skills"
        if "CERT" in line or "LICENSE" in line or "LICENCE" in line: return "certifications"
        if "PROJECT" in line: return "projects"
        if "SUMMARY" in line or "PROFILE" in line or "OBJECTIVE" in line: return "summary"
        if "EXPERIENCE" in line or "EMPLOY" in line or "CAREER" in line: return "experience"
    return None

def _collect_bullets(lines: List[str]) -> List[str]:
    out = []
    for l in lines:
        m = re.match(r"^\s*(?:[-•*]|•|\u2022)\s+(.*)$", l)
        if m:
            bb = _norm(m.group(1))
            if bb: out.append(bb)
    return out

def _extract_contacts_from_header(text: str) -> str:
    """Limit to the top of the document; drop years and year ranges from contact area."""
    header = "\n".join(_first_nonempty_lines(text, 20))
    # remove year ranges and standalone years to avoid polluting contact info
    header = re.sub(r"\b(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}\b", " ", header)
    header = re.sub(r"\b(?:19|20)\d{2}\b", " ", header)

    emails = set(EMAIL_RE.findall(header))
    phones = set()
    for m in PHONE_RE.findall(header):
        digits = re.sub(r"\D", "", m)
        if len(digits) >= 7 and "/" not in m:
            phones.add(_norm(m))

    parts = []
    if emails:
        parts.append(" / ".join(sorted(emails)))
    if phones:
        parts.append(" / ".join(sorted(phones)))
    return " | ".join(parts)

def _guess_name(text: str) -> str:
    for l in _first_nonempty_lines(text, 8):
        if _likely_name(l):
            return l.upper() if l.isupper() else " ".join(w.capitalize() for w in l.split())
    return _norm(_first_nonempty_lines(text, 1)[0] if _first_nonempty_lines(text,1) else "")

def _parse_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {"summary": [], "experience": [], "education": [], "skills": [], "certifications": [], "projects": []}
    current = None
    for raw in text.replace("\r\n","\n").replace("\r","\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():  # keep blank as separator inside current
            if current:
                sections[current].append("")
            continue
        sec = _detect_section(line)
        if sec:
            current = sec
            continue
        if current:
            sections[current].append(line)
        else:
            sections["summary"].append(line)
    return sections

def _parse_education(lines: List[str]) -> List[Dict[str,str]]:
    result = []
    buf = []
    for l in lines:
        if not l.strip():  # blank line signals break
            if buf:
                chunk = " ".join(_norm(x) for x in buf if x.strip())
                if chunk:
                    result.append({"institution": chunk[:200], "degree": "", "year": ""})
                buf = []
            continue
        buf.append(l)
    if buf:
        chunk = " ".join(_norm(x) for x in buf if x.strip())
        result.append({"institution": chunk[:200], "degree": "", "year": ""})

    # Try to enrich degree and year lightly
    for e in result:
        low = e["institution"].lower()
        if any(tok in low for tok in DEGREE_TOKENS):
            e["degree"] = ""
        m = re.search(r"\b(20|19)\d{2}\b", e["institution"])
        if m:
            e["year"] = m.group(0)
        if any(h in low for h in UNIVERSITY_HINTS) and not e.get("degree"):
            e["degree"] = ""
    return result

def _parse_skills(lines: List[str]) -> List[str]:
    skills = set()
    for l in lines:
        if not l.strip(): continue
        if re.match(r"^\s*(?:[-•*])\s+", l):
            val = re.sub(r"^\s*(?:[-•*])\s+", "", l).strip()
            if val: skills.add(_norm(val))
        else:
            parts = [p.strip() for p in re.split(r"[、;,/|]", l) if p.strip()]
            for p in parts:
                skills.add(_norm(p))
    return [s for s in skills if s]

def heuristic_parse(text: str) -> Dict[str, Any]:
    name = _guess_name(text)
    contact = _extract_contacts_from_header(text)
    sections = _parse_sections(text)

    # Summary: take first non-bullet paragraph from "summary" bucket
    summary_parts = []
    for l in sections["summary"]:
        if not l.strip(): 
            if summary_parts: break
            else: continue
        if re.match(r"^\s*[-•*]\s+", l):  # ignore bullets in summary
            continue
        summary_parts.append(_norm(l))
        if len(" ".join(summary_parts)) > 600: break
    summary = _norm(" ".join(summary_parts))[:600]

    # Experience: keep bullets if we find them
    exp_bullets = _collect_bullets(sections["experience"])
    work_experience: List[Dict[str, Any]] = []
    if exp_bullets:
        work_experience.append({"job_title":"", "company":"", "start_date":"", "end_date":"", "achievements":exp_bullets})

    education = _parse_education(sections["education"])
    skills = _parse_skills(sections["skills"])
    certs = [ _norm(re.sub(r"^\s*(?:[-•*])\s+","", l)) for l in sections["certifications"] if l.strip() ]

    return {
        "full_name": name,
        "contact_info": contact,
        "summary": summary,
        "work_experience": work_experience,
        "education": education,
        "skills": skills,
        "certifications": certs
    }

# ------------------------------ MODELS ------------------------------
class ParseResult(BaseModel):
    parsed: Dict[str, Any]

class RewriteRequest(BaseModel):
    parsed: Dict[str, Any]
    job_title: Optional[str] = None
    company: Optional[str] = None
    job_description: Optional[str] = None
    tone: Optional[str] = "professional"
    seniority: Optional[str] = None

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

# ------------------------------ OPENAI HELPERS ------------------------------
async def gpt_chat(messages: List[Dict[str, str]], temperature: float = 0.2) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None
    try:
        import httpx
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": OPENAI_MODEL, "messages": messages, "temperature": temperature}
        async with httpx.AsyncClient(timeout=45) as client:
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
        pretty = " — ".join([p for p in parts if p])
        if pretty:
            lines += ["", "EDUCATION", pretty]
    for exp in parsed.get("work_experience", []):
        header = " — ".join([x for x in [exp.get("job_title"), exp.get("company")] if x])
        if header:
            lines += ["", header]
        for a in exp.get("achievements", []):
            lines.append(f"• {a}")
    return "\n".join([l for l in lines if l is not None])

def local_rewrite(parsed: Dict[str, Any]) -> Dict[str, Any]:
    out = json.loads(json.dumps(parsed))  # deep copy
    if out.get("full_name"):
        out["full_name"] = " ".join([w.capitalize() for w in out["full_name"].split()])
    for exp in out.get("work_experience", []):
        new_ach = []
        for b in exp.get("achievements", []):
            bb = re.sub(r"^\s*(?:-|\*|•)\s*", "", b).strip()
            if bb:
                bb = bb[0].upper() + bb[1:]
            if len(bb) > 180:
                bb = bb[:177] + "..."
            new_ach.append(bb)
        exp["achievements"] = new_ach
    return out

# ------------------------------ ROUTES ------------------------------
@router.post("/parse", response_model=ParseResult)
async def parse_resume(file: UploadFile = File(...)):
    text = extract_text_from_upload(file)

    # Try OpenAI structured extraction first
    if OPENAI_API_KEY:
        sys_prompt = (
            "Extract resume JSON with fields: full_name, contact_info, summary, "
            "work_experience (array of {job_title, company, start_date, end_date, achievements[]}), "
            "education, skills, certifications. Return ONLY JSON."
        )
        content = await gpt_chat(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": text}],
            temperature=0.0
        )
        if content:
            try:
                return {"parsed": json.loads(content)}
            except Exception:
                # try to salvage trailing JSON
                m = re.search(r"\{[\s\S]*\}$", (content or "").strip())
                if m:
                    try:
                        return {"parsed": json.loads(m.group(0))}
                    except Exception:
                        pass

    # Fallback: robust local heuristic
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

    user_ctx = {
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
         {"role": "user", "content": json.dumps(user_ctx)}],
        temperature=0.2
    )
    if content:
        try:
            data = json.loads(content)
            if "resume_text" not in data:
                data["resume_text"] = render_resume_text(data)
            used_openai = True
            return {"rewritten": data, "resume_text": data["resume_text"], "used_openai": used_openai}
        except Exception:
            pass

    rewritten = local_rewrite(body.parsed)
    return {"rewritten": rewritten, "resume_text": render_resume_text(rewritten), "used_openai": used_openai}

@router.post("/cover-letter", response_model=CoverLetterResponse)
async def cover_letter(body: CoverLetterRequest):
    sys_rules = (
        "You are ResumePro, an elite career coach. Write a concise, specific cover letter tailored "
        "to the job. Use a confident, warm, and professional tone. Avoid clichés. "
        "Use 2–4 short paragraphs; maximum word count as provided. "
        "Return ONLY the final letter as plain text, no JSON."
    )
    payload = {
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
         {"role": "user", "content": json.dumps(payload)}],
        temperature=0.5
    )
    if content:
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



# BEGIN CHUNK_UTILS
MAX_TOK_TEXT = 12000  # coarse text limit per chunk (model-agnostic approximation)

def _split_for_llm(text: str, max_len: int = MAX_TOK_TEXT):
    """Split long resumes into manageable pieces at paragraph breaks."""
    text = text or ""
    if len(text) <= max_len:
        return [text]
    parts, buf, count = [], [], 0
    for para in text.split("\n\n"):
        if count + len(para) + 2 > max_len and buf:
            parts.append("\n\n".join(buf))
            buf, count = [], 0
        buf.append(para)
        count += len(para) + 2
    if buf:
        parts.append("\n\n".join(buf))
    return parts

def _fix_json_loose(s: str):
    """Attempt to salvage JSON if the model returns extra text."""
    s = (s or "").strip()
    m = re.search(r"\{[\s\S]*\}$", s)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    try:
        return json.loads(s)
    except Exception:
        return None
# END CHUNK_UTILS

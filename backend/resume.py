from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from typing import List, Dict, Any
import os, json, re

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

def heuristic_parse(text: str) -> Dict[str, Any]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    full_name = lines[0] if lines else ""
    summary = lines[1] if len(lines) > 1 else ""
    achievements = [l.lstrip("-•* ").strip() for l in lines[2:] if l.startswith(("-", "•", "*"))]

    work_experience: List[Dict[str, Any]] = []
    if achievements:
        work_experience.append({
            "job_title": "",
            "company": "",
            "start_date": "",
            "end_date": "",
            "achievements": achievements
        })

    return {
        "full_name": full_name,
        "contact_info": "",
        "summary": summary,
        "work_experience": work_experience,
        "education": [],
        "skills": [],
        "certifications": []
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

    # Try OpenAI first if a key exists; otherwise (or on any failure) use fallback
    if OPENAI_API_KEY:
        try:
            import httpx
            try:
                from app.prompts import RESUME_PARSER_PROMPT
                system_prompt = RESUME_PARSER_PROMPT
            except Exception:
                system_prompt = ("Extract resume JSON with fields: full_name, contact_info, summary, "
                                 "work_experience (array of {job_title, company, start_date, end_date, achievements[]}), "
                                 "education, skills, certifications. Return ONLY JSON.")
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
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
                    # safe JSON load
                    try:
                        parsed = json.loads(content)
                    except Exception:
                        m = re.search(r"\{[\s\S]*\}$", content.strip())
                        if not m:
                            raise ValueError("Model did not return JSON")
                        parsed = json.loads(m.group(0))
                    return {"parsed": parsed}
                # non-200 (e.g., 429) → fall back
        except Exception:
            pass

    # Fallback (no key or any error above)
    return {"parsed": heuristic_parse(text)}

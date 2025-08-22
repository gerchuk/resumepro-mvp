from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
import os, json, httpx
from app.prompts import RESUME_PARSER_PROMPT

router = APIRouter()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

class ParseResult(BaseModel):
    parsed: dict

@router.post('/parse', response_model=ParseResult)
async def parse_resume(file: UploadFile = File(...)):
    text = await file.read()
    text = text.decode('utf-8', errors='ignore')
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-5", 
        "messages": [
            {"role": "system", "content": RESUME_PARSER_PROMPT},
            {"role": "user", "content": text}
        ],
        "temperature": 0.0
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(OPENAI_URL, json=payload, headers=headers)
        if r.status_code != 200:
            raise HTTPException(status_code=500, detail="OpenAI error")
        data = r.json()
        parsed_text = data['choices'][0]['message']['content']
    parsed = json.loads(parsed_text)
    return {"parsed": parsed}
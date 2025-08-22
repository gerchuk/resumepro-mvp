from dotenv import load_dotenv
import os
load_dotenv()  # load variables from .env file
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from resume import router as resume_router
# (disabled) from routes.auth import router as auth_router

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# app.include_router(auth_router, prefix=\"/auth\")  # disabled (no routes/auth.py)
app.include_router(resume_router, prefix="/resume")

@app.get("/health")
def health():
    return {"status": "ok"}

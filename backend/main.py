import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from models import ActionRequest, ActionResponse
from llm_engine import run_pipeline

load_dotenv()

app = FastAPI(title="ClickSense Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/action", response_model=ActionResponse)
def get_action(request: ActionRequest):
    api_key = request.options.get("geminiKey")
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="GEMINI_API_KEY not set. Add it to backend/.env as GEMINI_API_KEY=your_key_here"
        )

    try:
        return run_pipeline(request, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

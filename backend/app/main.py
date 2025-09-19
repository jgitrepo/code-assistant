import os
import re
import time
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
QWEN3_MODEL = os.getenv("QWEN3_MODEL", "Qwen/Qwen2.5-Coder-7B-Instruct")
DEEPSEEK31_MODEL = os.getenv("DEEPSEEK31_MODEL", "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct")
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "http://127.0.0.1:5173")

if not HF_API_TOKEN:
    print("WARNING: HF_API_TOKEN not set. /api/infer and /api/explain will fail until configured.")

app = FastAPI(title="Code Assistant API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Diagnostics ----------
@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/__routes")
async def list_routes():
    return {"routes": sorted({getattr(r, "path", str(r)) for r in app.router.routes})}

@app.on_event("startup")
async def _print_startup_info():
    print(">>> main.py file:", __file__)
    try:
        paths = sorted({getattr(r, "path", str(r)) for r in app.router.routes})
        print(">>> Registered routes:", paths)
    except Exception as e:
        print(">>> Could not list routes:", e)

# -------- Simple in-memory TTL cache --------
class TTLCache:
    def __init__(self, ttl_seconds: int = 45, max_items: int = 200):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self.store: Dict[str, tuple[float, dict]] = {}

    def get(self, key: str) -> Optional[dict]:
        item = self.store.get(key)
        if not item:
            return None
        ts, value = item
        if time.time() - ts > self.ttl:
            self.store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: dict):
        if len(self.store) >= self.max_items:
            oldest_key = min(self.store, key=lambda k: self.store[k][0])
            self.store.pop(oldest_key, None)
        self.store[key] = (time.time(), value)

cache = TTLCache()

# --------- Pydantic models ----------
class ExplainRequest(BaseModel):
    code: str
    model: str = Field("qwen3", pattern=r"^(qwen3|deepseek-3\.1)$")

class AnalyzeRequest(BaseModel):
    code: str

class InferRequest(BaseModel):
    model: str = Field("qwen3", pattern=r"^(qwen3|deepseek-3\.1)$")
    prompt: str

# --------- Model selection ----------
def select_model_id(model_key: str) -> str:
    # Use Router-compatible repo IDs (these usually match HF model repos)
    return QWEN3_MODEL if model_key == "qwen3" else DEEPSEEK31_MODEL

# --------- HF Router (chat/completions) ----------
# Async version of your working requests-based function
async def hf_chat_completion(
    model: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> str:
    """
    Calls Hugging Face Router (OpenAI-compatible) /v1/chat/completions.
    Mirrors your previous synchronous implementation but uses httpx.AsyncClient.
    """
    if not HF_API_TOKEN:
        raise HTTPException(status_code=500, detail="HF_API_TOKEN not configured.")

    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            # (Optional) You can add a system prompt here to steer style
            # {"role": "system", "content": "You are a senior code reviewer."},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code in (429, 503):
            # brief immediate retry; no sleeping (respecting "no background wait" constraint)
            r = await client.post(url, headers=headers, json=payload)
        if r.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Hugging Face Router API error: {r.text}")

        data = r.json()
        try:
            # Non-streaming shape: choices[0].message.content
            return data["choices"][0]["message"]["content"]
        except Exception:
            raise HTTPException(status_code=500, detail="Unexpected response format from HF Router API")

# --------- Helpers for local analysis ----------
def simple_auto_format(code: str) -> str:
    lines = code.replace("\t", "    ").splitlines()
    return "\n".join(line.rstrip() for line in lines).strip() + "\n"

def find_duplicate_functions(code: str) -> List[tuple[str, str]]:
    pattern = re.compile(r"def\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*:\s*([\s\S]*?)(?=^def\s+|\Z)", re.M)
    matches = pattern.findall(code)
    bodies_map: Dict[str, str] = {}
    dups: List[tuple[str, str]] = []
    for name, body in matches:
        key = re.sub(r"\s+", "", body)
        if key in bodies_map and bodies_map[key] != name:
            dups.append((bodies_map[key], name))
        else:
            bodies_map[key] = name
    return dups

def lint_like_findings(code: str) -> List[str]:
    findings: List[str] = []
    if "\t" in code:
        findings.append("Use spaces instead of tabs (PEP 8).")
    if re.search(r"print\(.+?\)", code) and "logging" not in code:
        findings.append("Prefer `logging` over bare `print` for production code.")
    if re.search(r"except\s*:\s*pass", code):
        findings.append("Avoid bare `except: pass`; catch specific exceptions and handle them.")
    if re.search(r"==\s*None|None\s*==", code):
        findings.append("Use `is None` / `is not None` instead of `== None`.")
    if re.search(r"def\s+.+\([^)]*\):\s*\n\s*pass\b", code):
        findings.append("Stub functions detected; implement or document TODOs.")
    if any(len(ln) > 120 for ln in code.splitlines()):
        findings.append("Some lines exceed 120 characters; consider wrapping.")
    if re.search(r"\s+$", code, re.M):
        findings.append("Trailing whitespace found; remove for clean diffs.")
    return findings

# --------- Routes ----------
@app.post("/api/explain")
async def explain(req: ExplainRequest):
    cache_key = f"explain:{req.model}:{hash(req.code)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    model_repo = select_model_id(req.model)
    prompt = (
        "You are a senior code reviewer. Add detailed comments and best-practice signposts. "
        "Focus on naming, cohesion, error handling, typing, complexity, and DRY. "
        "Return concise markdown bullet points followed by a commented code block.\n\n"
        f"CODE:\n{req.code}"
    )
    text = await hf_chat_completion(model_repo, prompt, temperature=0.2, max_tokens=512)
    result = {"explanation": text}
    cache.set(cache_key, result)
    return result

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    formatted = simple_auto_format(req.code)
    findings = lint_like_findings(req.code)

    refactors = []
    for a, b in find_duplicate_functions(req.code):
        refactors.append({
            "symbol": f"{a} & {b}",
            "suggestion": f"Functions `{a}` and `{b}` have identical bodies. Extract a single helper and reuse."
        })

    if not refactors:
        refactors.append({
            "symbol": "General",
            "suggestion": "No duplicate functions detected. Consider extracting shared logic if future duplication appears."
        })

    return {"formatted": formatted, "findings": findings, "refactors": refactors}

@app.post("/api/infer")
async def infer(req: InferRequest):
    cache_key = f"infer:{req.model}:{hash(req.prompt)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    model_repo = select_model_id(req.model)
    text = await hf_chat_completion(model_repo, req.prompt, temperature=0.2, max_tokens=512)
    result = {"text": text}
    cache.set(cache_key, result)
    return result

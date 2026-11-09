"""Optional local live API (the static web demo does NOT depend on it).

    packages/engine/.venv/bin/uvicorn kinetra_engine.api:app --port 8000

POST /run   {idea, overrides?, template_id?, seed?, max_evals?, max_seconds?, mc_samples?, fix?}  -> run the pipeline live
GET  /scenarios                                                                                  -> prebuilt demo index
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import pipeline
from .base import Budget
from .templates import available

DEMO = Path(__file__).resolve().parents[4] / "apps/web/public/demo"

app = FastAPI(title="Kinetra engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class RunRequest(BaseModel):
    idea: str
    template_id: str | None = None
    overrides: dict[str, float] = Field(default_factory=dict)
    seed: int | None = None
    max_evals: int = Field(default=4000, ge=100, le=100000)
    max_seconds: float = Field(default=20.0, gt=0, le=300)
    mc_samples: int = Field(default=60, ge=10, le=2000)
    fix: bool = False


@app.get("/health")
def health() -> dict:
    return {"ok": True, "templates": available()}


@app.get("/scenarios")
def scenarios() -> dict:
    p = DEMO / "index.json"
    if not p.exists():
        raise HTTPException(404, "no demo bundle built; run packages/engine/scripts/build_*_bundle.py")
    return json.loads(p.read_text())


@app.post("/run")
def run(req: RunRequest) -> dict:
    try:
        r = pipeline.run(req.idea, req.template_id, req.overrides or None, req.seed,
                         Budget(max_evals=req.max_evals, max_seconds=req.max_seconds, mc_samples=req.mc_samples), fix=req.fix, use_cache=True)
    except pipeline.UnsupportedIdea as e:
        raise HTTPException(422, str(e))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    d = r.to_dict()
    d["headline"] = pipeline.headline(r.verdict)
    return d

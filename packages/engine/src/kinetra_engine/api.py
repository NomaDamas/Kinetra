"""Optional local live API (the static web demo does NOT depend on it).

    packages/engine/.venv/bin/uvicorn kinetra_engine.api:app --port 8000

POST /run       {idea, overrides?, template_id?, seed?, max_evals?, max_seconds?, mc_samples?, fix?}  -> run the pipeline live
GET  /scenarios                                                                                      -> prebuilt demo index
POST /simulate  {template, params|variant, overrides, seed, rescale_throttle?, ...}  -> ONE real MuJoCo rollout (unpaced), result + Trajectory
WS   /ws/sim    start|stop|restart messages -> real MuJoCo stepping streamed as frames (+ live CMA-ES search); see docs/live-mode.md
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import mujoco
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import live, pipeline
from .base import Budget
from .templates import available

DEMO = Path(__file__).resolve().parents[4] / "apps/web/public/demo"

app = FastAPI(title="Kinetra engine", version="0.1.0")
# Local dev ports only (vite 5173/4173, API itself). The websocket handler checks the Origin header against the same patterns.
LOCAL_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
app.add_middleware(CORSMiddleware, allow_origin_regex=LOCAL_ORIGIN_RE, allow_methods=["*"], allow_headers=["*"])


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
    return {"ok": True, "templates": available(), "mujoco_version": mujoco.__version__, "live": live.health_info()}


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


# --------------------------------------------------------------------------- live simulation
@app.post("/simulate")
def simulate(req: live.SimRequest) -> dict:
    """One real MuJoCo rollout, run to completion unpaced. Same code path as the websocket stepper (frames are bit-identical)."""
    try:
        return live.simulate_sync(req)
    except live.LiveError as e:
        raise HTTPException(e.status, str(e))


@app.websocket("/ws/sim")
async def ws_sim(ws: WebSocket) -> None:
    import re
    origin = ws.headers.get("origin")
    if origin is not None and not re.match(LOCAL_ORIGIN_RE, origin):
        await ws.close(code=1008)
        return
    await ws.accept()
    task: asyncio.Task | None = None
    last: live.SimRequest | None = None
    run_id = 0

    async def send_err(msg: str) -> None:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": msg}))
        except Exception:
            pass

    async def runner(req: live.SimRequest, rid: int) -> None:
        try:
            await live.stream(ws, req, rid)
        except asyncio.CancelledError:
            raise
        except live.LiveError as e:
            await send_err(str(e))
        except Exception as e:  # report, never fake a result
            await send_err(f"{type(e).__name__}: {e}")

    async def cancel() -> bool:
        nonlocal task
        was = task is not None and not task.done()
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            task = None
        return was

    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                await send_err("message is not JSON")
                continue
            kind = msg.get("type") if isinstance(msg, dict) else None
            if kind in ("start", "restart"):
                await cancel()
                if kind == "start":
                    try:
                        last = live.SimRequest(**{k: v for k, v in msg.items() if k != "type"})
                    except Exception as e:
                        await send_err(f"bad start message: {e}")
                        continue
                elif last is None:
                    await send_err("restart before any start")
                    continue
                run_id += 1
                task = asyncio.create_task(runner(last, run_id))
            elif kind == "stop":
                if await cancel():
                    await ws.send_text(json.dumps({"type": "stopped"}))
            else:
                await send_err(f"unknown message type {kind!r}")
    except WebSocketDisconnect:
        pass
    finally:
        await cancel()

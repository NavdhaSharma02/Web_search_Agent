import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .agent import Agent
from .config import Settings
from .memory import Memory
from .providers import Providers

STATIC = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value.strip()


def create_app(settings=None, providers=None):
    settings = settings or Settings.load()
    memory = Memory(settings.database)
    # Single-process, single-user app; reject overlapping turns instead of queueing.
    busy = set()
    gate = asyncio.Semaphore(4)

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(follow_redirects=False) as client:
            app.state.agent = Agent(memory, providers or Providers(settings, client))
            yield

    app = FastAPI(title="RecallSearch", version="1.0.0", lifespan=lifespan)
    app.state.memory = memory

    @app.middleware("http")
    async def security(request: Request, call_next):
        # JSON endpoints plus a same-origin guard mitigate drive-by localhost writes.
        if request.method in {"POST", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin writes are disabled"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response

    def require(cid):
        if not memory.get(str(cid)):
            raise HTTPException(404, "Conversation not found")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "configured": bool(settings.openai_key and settings.tavily_key), "model": settings.model}

    @app.get("/api/conversations")
    def conversations():
        return memory.conversations()

    @app.post("/api/conversations", status_code=201)
    def create():
        return memory.create()

    @app.get("/api/conversations/{cid}/messages")
    def messages(cid: UUID):
        require(cid)
        # Full history is persisted; UI shows the latest 200 messages.
        return memory.messages(str(cid))

    @app.delete("/api/conversations/{cid}", status_code=204)
    async def delete(cid: UUID):
        require(cid)
        if str(cid) in busy:
            raise HTTPException(409, "Wait for the active reply before deleting")
        memory.delete(str(cid))

    @app.post("/api/conversations/{cid}/messages")
    async def chat(cid: UUID, body: ChatRequest):
        require(cid)
        key = str(cid)
        if key in busy or gate.locked():
            raise HTTPException(409, "A reply is in progress. Please wait and retry.")
        busy.add(key)
        try:
            async with gate:
                return await app.state.agent.answer(key, body.message)
        finally:
            busy.discard(key)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()

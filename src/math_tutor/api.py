"""FastAPI endpoints for structured analysis and in-memory tutoring sessions."""

import sqlite3
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import Annotated, Callable, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from .agent import MathTutor, TutorError
from .analysis import ProblemAnalysis
from .images import MAX_IMAGE_BYTES, MIME_TYPES
from .settings import Settings
from .logging import logger, configure_logging, remove_handlers, RequestLoggingMiddleware

Mode = Literal["hint", "solve", "check", "read"]
from .education import Grade


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grade: Grade | None = None


class AnalyzeRequest(SessionRequest):
    text: str = Field(default="", max_length=20_000)
    image_data_url: str | None = Field(default=None, max_length=14 * 1024 * 1024)

    @model_validator(mode="after")
    def validate_input(self):
        if not self.text.strip() and self.image_data_url is None:
            raise ValueError("请提供 text 或 image_data_url。")
        if self.image_data_url is not None and not self.image_data_url.startswith("data:"):
            raise ValueError("image_data_url 只接受 base64 图片，不接受文件路径或远程 URL。")
        return self


class MessageRequest(AnalyzeRequest):
    # Grade is inherited for schema reuse, but cannot be changed mid-session.
    mode: Mode = "hint"

    @model_validator(mode="after")
    def fixed_grade(self):
        if self.grade is not None:
            raise ValueError("请在创建会话时设置 grade。")
        return self


class SessionResponse(BaseModel):
    session_id: UUID
    turn_count: int


class MessageResponse(SessionResponse):
    answer: str


class BodyLimitMiddleware:
    """Bound actual bytes, including chunked bodies, before multipart parsing."""
    def __init__(self, app, limit=14 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.limit:
                return await JSONResponse(status_code=413, content={"detail": "请求体超过 14 MiB。"})(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


@dataclass
class SessionEntry:
    tutor: MathTutor
    lock: RLock = field(default_factory=RLock)
    closed: bool = False


def create_app(settings: Settings | None = None, *, tutor_factory: Callable[[Settings], MathTutor] | None = None) -> FastAPI:
    sessions: dict[UUID, SessionEntry] = {}
    store_lock = RLock()
    config: Settings | None = settings
    factory = tutor_factory or (lambda configured: MathTutor(settings=configured))

    @asynccontextmanager
    async def lifespan(app):
        nonlocal config
        config = settings if settings is not None else Settings()
        handlers = configure_logging(config)
        try:
            from .mistakes.database import Database
            from .mistakes.storage import AssetStorage
            from .mistakes.service import MistakeService
            from .mistakes.models import utc_now
            database = Database(config.database_path)
            await run_in_threadpool(database.migrate)
            storage = AssetStorage(config.asset_dir)
            await run_in_threadpool(storage.sweep_orphans, database, utc_now())
            app.state.mistake_settings = config
            app.state.mistake_service = MistakeService(database, storage, config, factory)
            from .learning.service import LearningService
            app.state.learning_service = LearningService(database)
            if config.enable_local_identity:
                logger.bind(event="identity.local_mode").warning("Local test identity enabled; production authentication is required for deployment")
            logger.bind(event="service.start", model=config.model, max_sessions=config.service_max_sessions).info("Math Tutor API started")
            yield
        finally:
            for entry in list(sessions.values()):
                await run_in_threadpool(close_entry, entry)
            sessions.clear()
            logger.bind(event="service.stop").info("Math Tutor API stopped")
            remove_handlers(handlers)

    app = FastAPI(title="Math Tutor API", version="0.1.0", lifespan=lifespan)
    from .mistakes.router import router as mistake_router
    from .mistakes.review_router import router as review_router
    from .learning.router import router as learning_router
    app.include_router(learning_router)
    app.include_router(review_router)
    app.include_router(mistake_router)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_unavailable(request, exc):
        logger.bind(event='database.unavailable').error('Database operation unavailable')
        return JSONResponse(status_code=503,content={'detail':'数据服务暂时不可用，请稍后重试。'},headers={'Retry-After':'60'})

    @app.exception_handler(TutorError)
    async def model_error(request, exc):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def input_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": "输入或图片无效，请检查格式、大小及题目内容。"})

    def make_tutor(grade):
        assert config is not None, "Application lifespan must be started."
        values = config.model_dump()
        if grade is not None:
            values["grade"] = grade
        try:
            return factory(Settings.model_validate(values))
        except ValueError:
            logger.bind(event="service.configuration_error").error("Missing or invalid model configuration")
            raise HTTPException(503, "模型配置缺失或无效，请检查服务端配置。") from None

    def analyze(text, image, grade):
        with make_tutor(grade) as tutor:
            return tutor.analyze_problem(text, image=image)

    async def upload_data(image: UploadFile):
        try:
            if image.content_type not in MIME_TYPES:
                raise HTTPException(415, "仅支持 PNG、JPEG 或 WebP。")
            raw = await image.read(MAX_IMAGE_BYTES + 1)
            if len(raw) > MAX_IMAGE_BYTES:
                raise HTTPException(413, "图片超过 10 MiB。")
            return f"data:{image.content_type};base64," + base64.b64encode(raw).decode("ascii")
        finally:
            await image.close()

    def find_entry(session_id):
        with store_lock:
            entry = sessions.get(session_id)
        if entry is None:
            raise HTTPException(404, "会话不存在或已关闭。")
        return entry

    def close_entry(entry):
        with entry.lock:
            entry.closed = True
            entry.tutor.close()

    def send_message(session_id, text, image, mode):
        entry = find_entry(session_id)
        with entry.lock:
            if entry.closed:
                raise HTTPException(404, "会话已关闭。")
            if entry.tutor.turn_count >= entry.tutor.max_turns:
                raise HTTPException(409, "会话已达到轮数上限，请重置或创建新会话。")
            answer = entry.tutor.chat(text, image=image, mode=mode)
            return MessageResponse(session_id=session_id, answer=answer, turn_count=entry.tutor.turn_count)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/v1/analyze", response_model=ProblemAnalysis)
    def analyze_json(body: AnalyzeRequest):
        return analyze(body.text, body.image_data_url, body.grade)

    @app.post("/v1/analyze/image", response_model=ProblemAnalysis)
    async def analyze_upload(
        image: Annotated[UploadFile, File()],
        text: Annotated[str, Form(max_length=20_000)] = "",
        grade: Annotated[int | None, Form(ge=1, le=12)] = None,
    ):
        data_url = await upload_data(image)
        return await run_in_threadpool(analyze, text, data_url, grade)

    @app.post("/v1/sessions", response_model=SessionResponse, status_code=201)
    def create_session(body: SessionRequest):
        with store_lock:
            assert config is not None
            if len(sessions) >= config.service_max_sessions:
                raise HTTPException(503, "会话容量已满，请关闭不用的会话。")
            session_id = uuid4()
            sessions[session_id] = SessionEntry(make_tutor(body.grade))
        return SessionResponse(session_id=session_id, turn_count=0)

    @app.post("/v1/sessions/{session_id}/messages", response_model=MessageResponse)
    def message_json(session_id: UUID, body: MessageRequest):
        return send_message(session_id, body.text, body.image_data_url, body.mode)

    @app.post("/v1/sessions/{session_id}/messages/image", response_model=MessageResponse)
    async def message_upload(
        session_id: UUID,
        image: Annotated[UploadFile, File()],
        text: Annotated[str, Form(max_length=20_000)] = "",
        mode: Annotated[Mode, Form()] = "hint",
    ):
        data_url = await upload_data(image)
        return await run_in_threadpool(send_message, session_id, text, data_url, mode)

    @app.post("/v1/sessions/{session_id}/reset", response_model=SessionResponse)
    def reset_session(session_id: UUID):
        entry = find_entry(session_id)
        with entry.lock:
            if entry.closed:
                raise HTTPException(404, "会话已关闭。")
            entry.tutor.reset()
            return SessionResponse(session_id=session_id, turn_count=0)

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    def delete_session(session_id: UUID):
        entry = find_entry(session_id)
        close_entry(entry)
        with store_lock:
            sessions.pop(session_id, None)

    return app


app = create_app()

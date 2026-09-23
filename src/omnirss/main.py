"""OmniRSS 微核心主應用程式與生命週期入口 (Main Application & Lifespan Entry).

This module configures the FastAPI application, lifespan database/scheduler management,
security headers, RFC 7807 error middleware, and domain router mounts.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import uvicorn
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from omnirss.api.routers import (
    assets_router,
    auth_router,
    articles_router,
    backup_router,
    edge_router,
    feeds_router,
    plugins_router,
    rules_router,
)
from omnirss.core.database import get_db_manager
from omnirss.core.scheduler import OmniScheduler
from omnirss.core.security import PasswordHasher, TokenManager, get_security_headers

logger = logging.getLogger("omnirss.app")

_SCHEDULER: OmniScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """應用程式 Lifespan 生命週期管理器 (Application Lifespan Manager)."""
    global _SCHEDULER
    logger.info("Initializing OmniRSS storage foundation...")
    db_mgr = get_db_manager()
    await db_mgr.initialize()

    # 自動檢查預設管理員帳號
    async with db_mgr.get_connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) as cnt FROM users")
        row = await cur.fetchone()
        if not row or row["cnt"] == 0:
            logger.info("No users found. Creating default administrator account...")
            pwd_hash = PasswordHasher.hash_password("admin123456")
            api_key = TokenManager.generate_api_key()
            await conn.execute(
                """
                INSERT INTO users (username, password_hash, is_admin, api_key, settings_json)
                VALUES ('admin', ?, 1, ?, '{}')
                """,
                (pwd_hash, api_key),
            )
            await conn.commit()
            logger.info("Default admin created: username='admin', password='admin123456'")

    # 啟動非同步排程器
    logger.info("Starting background task scheduler...")
    _SCHEDULER = OmniScheduler(db_manager=db_mgr)
    _SCHEDULER.start()

    yield

    # 關機階段：優雅停止排程器並刷盤 SQLite WAL
    if _SCHEDULER:
        logger.info("Stopping background scheduler...")
        _SCHEDULER.shutdown(wait=False)

    logger.info("Executing SQLite WAL checkpoint (TRUNCATE)...")
    async with db_mgr.get_connection() as conn:
        try:
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception as e:
            logger.warning(f"WAL checkpoint warning on shutdown: {e}")
    logger.info("OmniRSS shutdown sequence completed.")


app = FastAPI(
    title="OmniRSS REST API",
    version="1.0.0",
    description="Microkernel RSS reader API with Anti-SSRF gateway and pluggable 4-slot ecosystem.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 跨來源資源共用設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_and_error_middleware(request: Request, call_next):
    """安全標頭注入與 RFC 7807 例外中介軟體 (Security Headers & RFC 7807 Middleware)."""
    try:
        response: Response = await call_next(request)
        # 注入 6 大安全防禦標頭
        for k, v in get_security_headers().items():
            response.headers[k] = v
        return response
    except Exception as exc:
        logger.exception(f"Unhandled server exception on {request.url.path}: {exc}")
        rfc7807_payload = {
            "type": "https://omnirss.dev/errors/internal-error",
            "title": "Internal Server Error",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "detail": str(exc),
            "instance": request.url.path,
        }
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=rfc7807_payload,
            headers=get_security_headers(),
        )


# 健康檢查端點
@app.get("/api/health", tags=["System"])
async def health_check() -> dict:
    """系統健康狀態健檢 (System Health Check)."""
    return {
        "status": "healthy",
        "service": "OmniRSS",
        "version": "1.0.0",
    }


# 掛載領域路由控制器
app.include_router(auth_router)
app.include_router(feeds_router)
app.include_router(articles_router)
app.include_router(rules_router)
app.include_router(plugins_router)
app.include_router(edge_router)
app.include_router(backup_router)
app.include_router(assets_router)


if __name__ == "__main__":
    uvicorn.run("omnirss.main:app", host="0.0.0.0", port=8000, reload=True)

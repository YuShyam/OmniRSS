"""FastAPI 依賴注入與安全鑑權 (FastAPI Dependencies & Authentication).

This module provides reusable FastAPI dependencies for database connections,
JWT Bearer token resolution, admin role checks, and constant-time X-API-Key authentication.
"""

from typing import AsyncGenerator, Optional
import aiosqlite
from fastapi import Cookie, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from omnirss.core.database import DatabaseManager, get_db_manager
from omnirss.core.security import TokenManager

security_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """資料庫連線依賴注入 (Database session dependency injection).

    :yield: aiosqlite 連線實例
    """
    db_mgr = get_db_manager()
    async with db_mgr.get_connection() as conn:
        yield conn


async def get_write_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """寫入交易資料庫連線依賴注入 (Exclusive write transaction dependency injection).

    :yield: aiosqlite 連線實例
    """
    db_mgr = get_db_manager()
    async with db_mgr.write_transaction() as conn:
        yield conn



async def get_current_user(
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    session_token: Optional[str] = Cookie(default=None, alias="session_token"),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """解析並驗證當前登入用戶 (Resolve and authenticate current user via JWT).

    :param auth_header: Authorization: Bearer 標頭
    :param session_token: session_token Cookie
    :param conn: 非同步資料庫連線
    :return: 使用者資料列字典
    :raises HTTPException: 401 認證失敗
    """
    token = None
    if auth_header and auth_header.credentials:
        token = auth_header.credentials
    elif session_token:
        token = session_token

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = TokenManager.decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    cursor = await conn.execute(
        "SELECT id, username, password_hash, is_admin, api_key, settings_json, created_at FROM users WHERE id = ?",
        (user_id,),
    )
    user_row = await cursor.fetchone()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return dict(user_row)


async def get_current_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    """驗證當前用戶是否具備超級管理員權限 (Ensure current user has admin privileges).

    :param user: 當前已認證用戶
    :return: 管理員用戶資料列字典
    :raises HTTPException: 403 權限不足
    """
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super administrator privileges required",
        )
    return user


async def verify_api_key(
    x_api_key: Optional[str] = Header(default=None),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """透過 X-API-Key 標頭常數時間驗證用戶 (Constant-time authentication via X-API-Key).

    :param x_api_key: 外部請求附帶之 X-API-Key 標頭
    :param conn: 非同步資料庫連線
    :return: 匹配之用戶資料列字典
    :raises HTTPException: 401 鑑權失敗
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required 'X-API-Key' header",
        )

    cursor = await conn.execute(
        "SELECT id, username, is_admin, api_key, settings_json FROM users"
    )
    all_users = await cursor.fetchall()

    for u in all_users:
        user_key = u["api_key"]
        # 使用常數時間字串比對防範計時攻擊 (Constant-time comparison)
        if TokenManager.verify_api_key(x_api_key, user_key):
            return dict(u)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid X-API-Key provided",
    )

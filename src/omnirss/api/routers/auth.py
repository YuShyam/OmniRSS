"""身分認證與用戶路由控制器 (Authentication & User Profile Router).

This module handles user login, logout, setup, profile retrieval, and API key regeneration.
"""

import json
from datetime import timedelta
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response, status

from omnirss.api.dependencies import get_current_user, get_db
from omnirss.api.schemas import LoginRequest, TokenResponse, UserDTO, UserSetupRequest
from omnirss.core.security import PasswordHasher, TokenManager

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/setup", response_model=UserDTO)
async def setup_initial_admin(
    req: UserSetupRequest,
    conn: aiosqlite.Connection = Depends(get_db),
) -> UserDTO:
    """首次啟動建立系統管理員 (Initial Admin Setup)."""
    cursor = await conn.execute("SELECT COUNT(*) as count FROM users")
    row = await cursor.fetchone()
    if row and row["count"] > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System already initialized with existing users",
        )

    pwd_hash = PasswordHasher.hash_password(req.password)
    api_key = TokenManager.generate_api_key()

    cur = await conn.execute(
        """
        INSERT INTO users (username, password_hash, is_admin, api_key, settings_json)
        VALUES (?, ?, 1, ?, '{}')
        """,
        (req.username, pwd_hash, api_key),
    )
    await conn.commit()
    user_id = cur.lastrowid

    from datetime import datetime, timezone

    return UserDTO(
        id=user_id,
        username=req.username,
        is_admin=True,
        api_key=api_key,
        settings={},
        created_at=datetime.now(timezone.utc),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    response: Response,
    conn: aiosqlite.Connection = Depends(get_db),
) -> TokenResponse:
    """使用者登入並核發 Access Token (User Login)."""
    cursor = await conn.execute(
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (req.username,),
    )
    user = await cursor.fetchone()
    if not user or not PasswordHasher.verify_password(
        user["password_hash"], req.password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    expires_delta = timedelta(days=7)
    token = TokenManager.create_access_token(
        data={"sub": str(user["id"]), "username": user["username"]},
        expires_delta=expires_delta,
    )

    # 設定 HTTP-Only 安全 Session Cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # 在本機或反向代理 HTTPS 下運作
        max_age=int(expires_delta.total_seconds()),
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds()),
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    """使用者登出並清除 Session Cookie (User Logout)."""
    response.delete_cookie("session_token")
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserDTO)
async def get_me(user: dict = Depends(get_current_user)) -> UserDTO:
    """取得當前已認證用戶資料 (Get Current User Profile)."""
    settings = {}
    try:
        settings = json.loads(user.get("settings_json") or "{}")
    except Exception:
        pass

    return UserDTO(
        id=user["id"],
        username=user["username"],
        is_admin=bool(user["is_admin"]),
        api_key=user["api_key"],
        settings=settings,
        created_at=user["created_at"],
    )


@router.post("/regenerate-key", response_model=dict)
async def regenerate_api_key(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """重新生成專屬 API Key (Regenerate User API Key)."""
    new_key = TokenManager.generate_api_key()
    await conn.execute(
        "UPDATE users SET api_key = ? WHERE id = ?",
        (new_key, user["id"]),
    )
    await conn.commit()
    return {"api_key": new_key, "message": "API Key successfully rotated"}

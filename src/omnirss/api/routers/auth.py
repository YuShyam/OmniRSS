"""身分認證與用戶路由控制器 (Authentication & User Profile Router).

This module handles user login, logout, setup, profile retrieval, and API key regeneration.
"""

import json
from datetime import timedelta
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response, status

from omnirss.api.dependencies import get_current_user, get_db, get_write_db
from omnirss.api.schemas import (
    LoginRequest,
    TokenResponse,
    UserDTO,
    UserSettingsDTO,
    UserSettingsUpdateRequest,
    UserSetupRequest,
)
from omnirss.core.security import PasswordHasher, TokenManager

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
user_router = APIRouter(prefix="/api/user", tags=["User"])



@router.post("/setup", response_model=UserDTO)
async def setup_initial_admin(
    req: UserSetupRequest,
    conn: aiosqlite.Connection = Depends(get_write_db),
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

    # 種植 QuiteRSS 經典 5 組標籤
    await conn.execute(
        """
        INSERT OR IGNORE INTO tags (user_id, name, color_hex, sort_order)
        VALUES 
            (?, '重要', '#ef4444', 1),
            (?, '工作', '#f97316', 2),
            (?, '個人', '#10b981', 3),
            (?, '待讀', '#3b82f6', 4),
            (?, '稍後閱讀', '#8b5cf6', 5)
        """,
        (user_id, user_id, user_id, user_id, user_id),
    )
    await conn.commit()

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
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """重新生成專屬 API Key (Regenerate User API Key)."""
    new_key = TokenManager.generate_api_key()
    await conn.execute(
        "UPDATE users SET api_key = ? WHERE id = ?",
        (new_key, user["id"]),
    )
    await conn.commit()
    return {"api_key": new_key, "message": "API Key successfully rotated"}


@router.get("/settings", response_model=UserSettingsDTO)
async def get_user_settings(
    user: dict = Depends(get_current_user),
) -> UserSettingsDTO:
    """取得當前使用者偏好設定 (Get Current User Settings)."""
    settings: dict = {}
    try:
        settings = json.loads(user.get("settings_json") or "{}")
    except Exception:
        settings = {}
    return UserSettingsDTO(settings=settings)


@router.put("/settings", response_model=UserSettingsDTO)
async def update_user_settings(
    req: UserSettingsUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> UserSettingsDTO:
    """更新當前使用者偏好設定 (Update Current User Settings)."""
    existing: dict = {}
    try:
        existing = json.loads(user.get("settings_json") or "{}")
    except Exception:
        existing = {}

    existing.update(req.settings)
    updated_json = json.dumps(existing, ensure_ascii=False)

    await conn.execute(
        "UPDATE users SET settings_json = ? WHERE id = ?",
        (updated_json, user["id"]),
    )
    await conn.commit()
    return UserSettingsDTO(settings=existing)


# Register identical handlers on user_router for /api/user/settings
user_router.add_api_route("/settings", get_user_settings, methods=["GET"], response_model=UserSettingsDTO)
user_router.add_api_route("/settings", update_user_settings, methods=["PUT"], response_model=UserSettingsDTO)



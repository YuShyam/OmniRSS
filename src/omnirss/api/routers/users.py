"""使用者管理與個人安全路由控制器 (User Management & Security Router).

This module provides endpoints for:
1. Individual user password change (/api/user/password).
2. Administrator user management CRUD (/api/users).
"""

from datetime import datetime, timezone
from typing import Optional
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from omnirss.api.dependencies import (
    get_current_admin,
    get_current_user,
    get_db,
    get_write_db,
)
from omnirss.api.schemas import (
    ChangePasswordRequest,
    UserAdminUpdateRequest,
    UserCreateRequest,
    UserListItemDTO,
)
from omnirss.core.security import PasswordHasher, TokenManager

router = APIRouter(tags=["Users & Security"])


# =============================================================================
# 1. 個人帳號安全端點 (Individual User Security)
# =============================================================================

@router.put("/api/user/password", response_model=dict)
async def change_my_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """使用者修改自身密碼 (Change Current User Password)."""
    # 1. 驗證目前舊密碼
    if not PasswordHasher.verify_password(current_user["password_hash"], req.old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password",
        )

    # 2. 雜湊新密碼
    new_hash = PasswordHasher.hash_password(req.new_password)

    # 3. 更新資料庫
    await conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (new_hash, current_user["id"]),
    )
    await conn.commit()

    return {"message": "Password changed successfully"}


# =============================================================================
# 2. 管理員使用者管理端點 (Admin User Management CRUD)
# =============================================================================

@router.get("/api/users", response_model=list[UserListItemDTO])
async def list_all_users(
    admin: dict = Depends(get_current_admin),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[UserListItemDTO]:
    """管理員取得全站使用者清單 (Admin: List All Users)."""
    cursor = await conn.execute(
        """
        SELECT 
            u.id, 
            u.username, 
            u.is_admin, 
            u.api_key, 
            u.created_at,
            (SELECT COUNT(*) FROM user_feeds uf WHERE uf.user_id = u.id) as feed_count,
            (SELECT COALESCE(SUM(uf.unread_count), 0) FROM user_feeds uf WHERE uf.user_id = u.id) as unread_count
        FROM users u
        ORDER BY u.id ASC
        """
    )
    rows = await cursor.fetchall()
    results: list[UserListItemDTO] = []
    for r in rows:
        results.append(
            UserListItemDTO(
                id=r["id"],
                username=r["username"],
                is_admin=bool(r["is_admin"]),
                api_key=r["api_key"] or "",
                created_at=r["created_at"] if isinstance(r["created_at"], datetime) else datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00")),
                feed_count=int(r["feed_count"] or 0),
                unread_count=int(r["unread_count"] or 0),
            )
        )
    return results


@router.post("/api/users", response_model=UserListItemDTO, status_code=status.HTTP_201_CREATED)
async def create_new_user(
    req: UserCreateRequest,
    admin: dict = Depends(get_current_admin),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> UserListItemDTO:
    """管理員建立新使用者 (Admin: Create New User)."""
    # 1. 檢查使用者名稱是否重複
    cursor = await conn.execute(
        "SELECT id FROM users WHERE username = ?",
        (req.username.strip(),),
    )
    if await cursor.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{req.username}' already exists",
        )

    # 2. 密碼雜湊與 API Key 生成
    pwd_hash = PasswordHasher.hash_password(req.password)
    api_key = TokenManager.generate_api_key()
    now = datetime.now(timezone.utc)

    # 3. 寫入 users 表
    cur = await conn.execute(
        """
        INSERT INTO users (username, password_hash, is_admin, api_key, settings_json, created_at)
        VALUES (?, ?, ?, ?, '{}', ?)
        """,
        (req.username.strip(), pwd_hash, 1 if req.is_admin else 0, api_key, now),
    )
    user_id = cur.lastrowid

    # 4. 為新使用者種植 QuiteRSS 經典 5 組標籤
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

    return UserListItemDTO(
        id=user_id,
        username=req.username.strip(),
        is_admin=req.is_admin,
        api_key=api_key,
        created_at=now,
        feed_count=0,
        unread_count=0,
    )


@router.put("/api/users/{user_id}", response_model=UserListItemDTO)
async def update_user(
    user_id: int,
    req: UserAdminUpdateRequest,
    admin: dict = Depends(get_current_admin),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> UserListItemDTO:
    """管理員更新指定使用者角色或重設密碼 (Admin: Update User)."""
    # 1. 查詢目標使用者
    cursor = await conn.execute(
        """
        SELECT 
            u.id, 
            u.username, 
            u.is_admin, 
            u.api_key, 
            u.created_at,
            (SELECT COUNT(*) FROM user_feeds uf WHERE uf.user_id = u.id) as feed_count,
            (SELECT COALESCE(SUM(uf.unread_count), 0) FROM user_feeds uf WHERE uf.user_id = u.id) as unread_count
        FROM users u
        WHERE u.id = ?
        """,
        (user_id,),
    )
    user_row = await cursor.fetchone()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    # 2. 處理角色變更
    is_admin_val = bool(user_row["is_admin"])
    if req.is_admin is not None:
        if user_id == admin["id"] and not req.is_admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot revoke your own administrator privileges",
            )
        is_admin_val = req.is_admin
        await conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (1 if is_admin_val else 0, user_id),
        )

    # 3. 處理密碼重設
    if req.new_password:
        pwd_hash = PasswordHasher.hash_password(req.new_password)
        await conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (pwd_hash, user_id),
        )

    await conn.commit()

    created_at_val = user_row["created_at"]
    if not isinstance(created_at_val, datetime):
        created_at_val = datetime.fromisoformat(str(created_at_val).replace("Z", "+00:00"))

    return UserListItemDTO(
        id=user_id,
        username=user_row["username"],
        is_admin=is_admin_val,
        api_key=user_row["api_key"] or "",
        created_at=created_at_val,
        feed_count=int(user_row["feed_count"] or 0),
        unread_count=int(user_row["unread_count"] or 0),
    )


@router.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: dict = Depends(get_current_admin),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> None:
    """管理員刪除使用者 (Admin: Delete User & Cascade Clean)."""
    # 1. 防呆自刪
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own administrator account",
        )

    # 2. 檢查使用者是否存在
    cursor = await conn.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not await cursor.fetchone():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    # 3. 級聯清理關聯資料
    await conn.execute("DELETE FROM user_article_states WHERE user_id = ?", (user_id,))
    await conn.execute(
        "DELETE FROM article_tags WHERE tag_id IN (SELECT id FROM tags WHERE user_id = ?)",
        (user_id,),
    )
    await conn.execute("DELETE FROM tags WHERE user_id = ?", (user_id,))
    await conn.execute("DELETE FROM user_feeds WHERE user_id = ?", (user_id,))
    await conn.execute("DELETE FROM categories WHERE user_id = ?", (user_id,))
    await conn.execute("DELETE FROM user_rules WHERE user_id = ?", (user_id,))
    await conn.execute("DELETE FROM user_plugin_configs WHERE user_id = ?", (user_id,))
    await conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    await conn.commit()


# =============================================================================
# 3. 系統資安與稽核日誌端點 (System Audit & Security Logs)
# =============================================================================

@router.get("/api/system/logs", response_model=dict)
async def get_system_logs(
    category: Optional[str] = "all",
    admin: dict = Depends(get_current_admin),
) -> dict:
    """管理員取得系統稽核與資安日誌 (Admin: Get System Audit Logs)."""
    import os
    from pathlib import Path
    
    logs_dir = Path("logs")
    log_files = sorted(logs_dir.glob("*.log"), key=os.path.getmtime, reverse=True) if logs_dir.exists() else []
    
    entries = []
    # 讀取最新的 log 檔案內容
    target_files = log_files[:2] if log_files else []
    
    for log_file in target_files:
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    
                    # 分析日誌類型 (僅呈現在意事件，過濾無用 DEBUG 雜訊)
                    is_security = "[SECURITY" in line_str or "[AUDIT]" in line_str or "login" in line_str.lower()
                    is_error = "ERROR" in line_str or "CRITICAL" in line_str
                    is_warning = "WARNING" in line_str or "WARN" in line_str
                    
                    if category == "security" and not is_security:
                        continue
                    elif category == "error" and not (is_error or is_warning):
                        continue
                        
                    # 去味與結構化整理
                    level = "ALERT" if "[SECURITY" in line_str else ("ERROR" if is_error else ("WARNING" if is_warning else "INFO"))
                    
                    entries.append({
                        "raw": line_str,
                        "level": level,
                        "is_security": is_security,
                    })
                    if len(entries) >= 100:
                        break
        except Exception as exc:
            pass

    return {
        "total": len(entries),
        "category": category,
        "logs": entries,
    }


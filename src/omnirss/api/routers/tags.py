"""標籤與標記路由控制器 (Tags & Labels Router - QuiteRSS Alignment).

This module provides CRUD endpoints for custom tags/labels, unread count tracking,
and single/batch article tag binding operations.
"""

from typing import Any
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from omnirss.api.dependencies import get_current_user, get_db, get_write_db
from omnirss.api.schemas import (
    ArticleTagBindingRequest,
    ArticleTagToggleRequest,
    BatchArticleTagRequest,
    TagCreateRequest,
    TagDTO,
    TagUpdateRequest,
)

router = APIRouter(prefix="/api/tags", tags=["Tags"])


@router.get("", response_model=list[TagDTO])
async def list_tags(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[TagDTO]:
    """獲取當前使用者的所有標籤清單與未讀統計 (List all tags with counts)."""
    user_id = user["id"]
    sql = """
        SELECT t.id, t.name, t.color_hex, t.sort_order, t.created_at,
               COUNT(DISTINCT CASE WHEN a.id IS NOT NULL THEN at.article_id ELSE NULL END) as article_count,
               COUNT(DISTINCT CASE WHEN a.id IS NOT NULL AND COALESCE(uas.is_read, 0) = 0 THEN at.article_id ELSE NULL END) as unread_count
        FROM tags t
        LEFT JOIN article_tags at ON t.id = at.tag_id
        LEFT JOIN articles_hot a ON at.article_id = a.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = t.user_id
        WHERE t.user_id = ?
        GROUP BY t.id, t.name, t.color_hex, t.sort_order, t.created_at
        ORDER BY t.sort_order ASC, t.id ASC
    """
    cur = await conn.execute(sql, (user_id,))
    rows = await cur.fetchall()

    if not rows:
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
        cur = await conn.execute(sql, (user_id,))
        rows = await cur.fetchall()

    result = []
    for r in rows:
        result.append(
            TagDTO(
                id=r["id"],
                name=r["name"],
                color_hex=r["color_hex"],
                sort_order=r["sort_order"],
                article_count=r["article_count"],
                unread_count=r["unread_count"],
                created_at=r["created_at"],
            )
        )
    return result


@router.post("", response_model=TagDTO, status_code=status.HTTP_201_CREATED)
async def create_tag(
    req: TagCreateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> TagDTO:
    """建立自訂標籤 (Create custom tag)."""
    user_id = user["id"]
    clean_name = req.name.strip()
    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tag name cannot be empty",
        )

    # 檢查是否重複名稱
    cur = await conn.execute(
        "SELECT id FROM tags WHERE user_id = ? AND name = ?",
        (user_id, clean_name),
    )
    if await cur.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tag '{clean_name}' already exists",
        )

    cur = await conn.execute(
        "INSERT INTO tags (user_id, name, color_hex, sort_order) VALUES (?, ?, ?, ?)",
        (user_id, clean_name, req.color_hex, req.sort_order),
    )
    await conn.commit()
    tag_id = cur.lastrowid

    return TagDTO(
        id=tag_id,
        name=clean_name,
        color_hex=req.color_hex,
        sort_order=req.sort_order,
        article_count=0,
        unread_count=0,
    )


@router.put("/{tag_id}", response_model=TagDTO)
async def update_tag(
    tag_id: int,
    req: TagUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> TagDTO:
    """更新標籤屬性 (Update tag)."""
    user_id = user["id"]
    cur = await conn.execute(
        "SELECT id, name, color_hex, sort_order FROM tags WHERE id = ? AND user_id = ?",
        (tag_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    new_name = req.name.strip() if req.name is not None else row["name"]
    new_color = req.color_hex if req.color_hex is not None else row["color_hex"]
    new_sort = req.sort_order if req.sort_order is not None else row["sort_order"]

    await conn.execute(
        "UPDATE tags SET name = ?, color_hex = ?, sort_order = ? WHERE id = ? AND user_id = ?",
        (new_name, new_color, new_sort, tag_id, user_id),
    )
    await conn.commit()

    return TagDTO(
        id=tag_id,
        name=new_name,
        color_hex=new_color,
        sort_order=new_sort,
    )


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> None:
    """刪除標籤 (Delete tag)."""
    user_id = user["id"]
    cur = await conn.execute(
        "DELETE FROM tags WHERE id = ? AND user_id = ?",
        (tag_id, user_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )
    await conn.commit()


@router.post("/articles/{article_id}/toggle", response_model=dict[str, Any])
async def toggle_article_tag(
    article_id: int,
    req: ArticleTagToggleRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """為單一文章切換/貼上/移除標籤 (Toggle/Add/Remove Tag for single article)."""
    user_id = user["id"]
    tag_id = req.tag_id

    # 驗證標籤存在且屬於當前使用者
    cur = await conn.execute(
        "SELECT id, name, color_hex FROM tags WHERE id = ? AND user_id = ?",
        (tag_id, user_id),
    )
    tag_row = await cur.fetchone()
    if not tag_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    # 檢查是否已存在關聯
    chk = await conn.execute(
        "SELECT 1 FROM article_tags WHERE article_id = ? AND tag_id = ?",
        (article_id, tag_id),
    )
    exists = bool(await chk.fetchone())

    is_tagged = False
    if req.action == "remove" or (req.action == "toggle" and exists):
        await conn.execute(
            "DELETE FROM article_tags WHERE article_id = ? AND tag_id = ?",
            (article_id, tag_id),
        )
        is_tagged = False
    else:
        await conn.execute(
            "INSERT OR IGNORE INTO article_tags (article_id, tag_id) VALUES (?, ?)",
            (article_id, tag_id),
        )
        is_tagged = True

    await conn.commit()

    # 獲取文章當前所有標籤
    cur = await conn.execute(
        """
        SELECT t.id, t.name, t.color_hex
        FROM tags t
        JOIN article_tags at ON t.id = at.tag_id
        WHERE at.article_id = ? AND t.user_id = ?
        ORDER BY t.sort_order ASC, t.id ASC
        """,
        (article_id, user_id),
    )
    tags = [dict(r) for r in await cur.fetchall()]

    return {
        "article_id": article_id,
        "tag_id": tag_id,
        "is_tagged": is_tagged,
        "tags": tags,
    }


@router.post("/articles/{article_id}/bind", response_model=dict[str, Any])
async def bind_article_tags(
    article_id: int,
    req: ArticleTagBindingRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """覆寫單一文章之所有標籤 (Bind full tags list for article)."""
    user_id = user["id"]

    # 刪除原有標籤
    await conn.execute(
        """
        DELETE FROM article_tags
        WHERE article_id = ?
          AND tag_id IN (SELECT id FROM tags WHERE user_id = ?)
        """,
        (article_id, user_id),
    )

    if req.tag_ids:
        # 僅插入合法屬於該用戶的標籤
        for tid in req.tag_ids:
            await conn.execute(
                """
                INSERT OR IGNORE INTO article_tags (article_id, tag_id)
                SELECT ?, id FROM tags WHERE id = ? AND user_id = ?
                """,
                (article_id, tid, user_id),
            )

    await conn.commit()

    cur = await conn.execute(
        """
        SELECT t.id, t.name, t.color_hex
        FROM tags t
        JOIN article_tags at ON t.id = at.tag_id
        WHERE at.article_id = ? AND t.user_id = ?
        ORDER BY t.sort_order ASC, t.id ASC
        """,
        (article_id, user_id),
    )
    tags = [dict(r) for r in await cur.fetchall()]

    return {"article_id": article_id, "tags": tags}


@router.post("/articles/batch", response_model=dict[str, Any])
async def batch_article_tags(
    req: BatchArticleTagRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """批次文章標籤操作 (Batch tag assignment)."""
    user_id = user["id"]
    tag_id = req.tag_id
    article_ids = req.article_ids

    # 驗證標籤
    cur = await conn.execute(
        "SELECT id FROM tags WHERE id = ? AND user_id = ?",
        (tag_id, user_id),
    )
    if not await cur.fetchone():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    modified_count = 0
    if req.action == "add":
        for aid in article_ids:
            cur = await conn.execute(
                "INSERT OR IGNORE INTO article_tags (article_id, tag_id) VALUES (?, ?)",
                (aid, tag_id),
            )
            if cur.rowcount > 0:
                modified_count += 1
    elif req.action == "remove":
        for aid in article_ids:
            cur = await conn.execute(
                "DELETE FROM article_tags WHERE article_id = ? AND tag_id = ?",
                (aid, tag_id),
            )
            if cur.rowcount > 0:
                modified_count += 1

    await conn.commit()
    return {
        "tag_id": tag_id,
        "action": req.action,
        "affected_articles": len(article_ids),
        "modified_count": modified_count,
    }

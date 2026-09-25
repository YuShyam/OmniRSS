"""標籤與標記 API 單元測試 (Tags API Tests - QuiteRSS Alignment)."""

import pytest
from httpx import ASGITransport, AsyncClient
from omnirss.main import app
from omnirss.core.database import DatabaseManager, set_global_db_manager


@pytest.mark.asyncio
async def test_tags_crud_and_article_binding(tmp_path):
    # Setup isolated test database
    test_db = tmp_path / "tags_test.db"
    db_mgr = DatabaseManager(test_db)
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Setup admin user and login
        setup_res = await client.post(
            "/api/auth/setup",
            json={"username": "tagadmin", "password": "password123"},
        )
        assert setup_res.status_code == 200

        login_res = await client.post(
            "/api/auth/login",
            json={"username": "tagadmin", "password": "password123"},
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. List default seeded tags (5 QuiteRSS labels)
        list_res = await client.get("/api/tags", headers=headers)
        assert list_res.status_code == 200
        tags = list_res.json()
        assert len(tags) == 5
        tag_names = [t["name"] for t in tags]
        assert "重要" in tag_names
        assert "工作" in tag_names
        assert "個人" in tag_names
        assert "待讀" in tag_names
        assert "稍後閱讀" in tag_names
        # Empty seeded tags must have 0 counts
        for t in tags:
            assert t["article_count"] == 0
            assert t["unread_count"] == 0

        # 3. Create a new custom tag
        create_res = await client.post(
            "/api/tags",
            headers=headers,
            json={"name": "科技新知", "color_hex": "#06b6d4", "sort_order": 6},
        )
        assert create_res.status_code == 201
        new_tag = create_res.json()
        assert new_tag["name"] == "科技新知"
        assert new_tag["color_hex"] == "#06b6d4"
        tag_id = new_tag["id"]

        # 4. Update tag
        update_res = await client.put(
            f"/api/tags/{tag_id}",
            headers=headers,
            json={"name": "頂尖科技", "color_hex": "#0ea5e9"},
        )
        assert update_res.status_code == 200
        assert update_res.json()["name"] == "頂尖科技"

        # 5. Add a feed & article to test tag binding
        async with db_mgr.write_transaction() as conn:
            f_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url) VALUES ('Test Feed', 'https://example.com/rss.xml')"
            )
            feed_id = f_cur.lastrowid
            # Get user id
            u_cur = await conn.execute("SELECT id FROM users WHERE username = 'tagadmin'")
            u_row = await u_cur.fetchone()
            user_id = u_row["id"]

            await conn.execute(
                "INSERT INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, 'Test Feed')",
                (user_id, feed_id),
            )

            cur = await conn.execute(
                """
                INSERT INTO articles_hot (feed_id, entry_hash, title, url, snippet, published_at)
                VALUES (?, 'testhash001', 'AI 技術革命', 'https://example.com/1', 'AI 概要', datetime('now'))
                """,
                (feed_id,),
            )
            article_id = cur.lastrowid
            await conn.commit()

        # 6. Toggle tag on article
        toggle_res = await client.post(
            f"/api/tags/articles/{article_id}/toggle",
            headers=headers,
            json={"tag_id": tag_id, "action": "add"},
        )
        assert toggle_res.status_code == 200
        assert toggle_res.json()["is_tagged"] is True
        assert len(toggle_res.json()["tags"]) == 1
        assert toggle_res.json()["tags"][0]["name"] == "頂尖科技"

        # 7. Verify tag article_count and unread_count updated in list_tags
        list_after_tag = await client.get("/api/tags", headers=headers)
        assert list_after_tag.status_code == 200
        tag_map = {t["id"]: t for t in list_after_tag.json()}
        assert tag_map[tag_id]["article_count"] == 1
        assert tag_map[tag_id]["unread_count"] == 1

        # Query articles by tag
        filter_res = await client.get(f"/api/articles?tag_id={tag_id}", headers=headers)
        assert filter_res.status_code == 200
        art_items = filter_res.json()["items"]
        assert len(art_items) == 1
        assert art_items[0]["id"] == article_id
        assert len(art_items[0]["tags"]) == 1
        assert art_items[0]["tags"][0]["name"] == "頂尖科技"

        # 8. Delete tag
        del_res = await client.delete(f"/api/tags/{tag_id}", headers=headers)
        assert del_res.status_code == 204

"""API 路由模組匯出 (API Routers Package)."""

from omnirss.api.routers.auth import router as auth_router, user_router
from omnirss.api.routers.feeds import router as feeds_router
from omnirss.api.routers.articles import router as articles_router
from omnirss.api.routers.rules import router as rules_router
from omnirss.api.routers.plugins import router as plugins_router
from omnirss.api.routers.edge import router as edge_router
from omnirss.api.routers.backup import router as backup_router
from omnirss.api.routers.assets import router as assets_router
from omnirss.api.routers.tags import router as tags_router

__all__ = [
    "auth_router",
    "user_router",
    "feeds_router",
    "articles_router",
    "rules_router",
    "plugins_router",
    "edge_router",
    "backup_router",
    "assets_router",
    "tags_router",
]


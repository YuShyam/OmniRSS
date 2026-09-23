"""測試組態與隔離環境 (Pytest Fixtures and Test Setup).

Provides isolated temporary SQLite database, temporary image vault, and mock plugin directories.
"""

from pathlib import Path
import tempfile
from typing import AsyncGenerator, Generator
import aiosqlite
import pytest
import pytest_asyncio
from omnirss.core.database import init_db_sync


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """建立隔離之暫存 SQLite 資料庫 (Create isolated temporary SQLite database)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = Path(f.name)
    try:
        init_db_sync(tmp_path)
        yield tmp_path
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@pytest_asyncio.fixture
async def async_db_conn(temp_db_path: Path) -> AsyncGenerator[aiosqlite.Connection, None]:
    """提供非同步資料庫連線 (Provide async SQLite connection)."""
    conn = await aiosqlite.connect(str(temp_db_path))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode = WAL;")
    await conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """建立暫存測試目錄 (Create temporary directory)."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)

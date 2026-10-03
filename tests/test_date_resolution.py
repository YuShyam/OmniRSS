"""收錄起始時間解析與動態滾動視窗單元測試 (Date Resolution Unit Tests).

Tests 3-tier hierarchy and dynamic relative date resolution:
- 30days, 7days, today, all, custom ISO dates
- Hierarchy overrides: Feed Force > Global Force > Category Force > General Inheritance
"""

from datetime import datetime, timezone, timedelta
from omnirss.core.scheduler import resolve_effective_min_publish_date


def test_resolve_dynamic_tokens():
    """測試動態相對時間代碼計算 (Test dynamic relative tokens)."""
    now = datetime.now(timezone.utc)

    # 1. 30 天滾動視窗
    dt_30d = resolve_effective_min_publish_date(
        feed_min_date="30days",
        feed_force_min=False,
        cat_min_date=None,
        cat_force_min=False,
        global_min_date=None,
        global_force_min=False,
    )
    assert dt_30d is not None
    # 差距應約為 30 天 (容許 5 秒誤差)
    diff = (now - dt_30d).total_seconds()
    assert abs(diff - 30 * 86400) < 5

    # 2. 7 天滾動視窗
    dt_7d = resolve_effective_min_publish_date(
        feed_min_date="7days",
        feed_force_min=False,
        cat_min_date=None,
        cat_force_min=False,
        global_min_date=None,
        global_force_min=False,
    )
    assert dt_7d is not None
    diff_7 = (now - dt_7d).total_seconds()
    assert abs(diff_7 - 7 * 86400) < 5

    # 3. 今天
    dt_today = resolve_effective_min_publish_date(
        feed_min_date="today",
        feed_force_min=False,
        cat_min_date=None,
        cat_force_min=False,
        global_min_date=None,
        global_force_min=False,
    )
    assert dt_today is not None
    assert dt_today.hour == 0 and dt_today.minute == 0 and dt_today.second == 0

    # 4. 全部收錄 (all / 1970-01-01 / None / default) -> None
    for token in ["all", "default", None, "1970-01-01 00:00:00", ""]:
        res = resolve_effective_min_publish_date(
            feed_min_date=token,
            feed_force_min=False,
            cat_min_date=None,
            cat_force_min=False,
            global_min_date=None,
            global_force_min=False,
        )
        assert res is None


def test_resolve_hierarchy_overrides():
    """測試三層繼承與強制優先順序 (Test 3-tier hierarchy & force flags)."""
    # 1. 一般繼承：來源 > 分類 > 全域
    dt_inherit = resolve_effective_min_publish_date(
        feed_min_date="7days",
        feed_force_min=False,
        cat_min_date="30days",
        cat_force_min=False,
        global_min_date="90days",
        global_force_min=False,
    )
    # 來源自訂優先 (7days)
    now = datetime.now(timezone.utc)
    diff = (now - dt_inherit).total_seconds()
    assert abs(diff - 7 * 86400) < 5

    # 2. 分類強制覆蓋 (無全域強制、無來源強制)
    dt_cat_force = resolve_effective_min_publish_date(
        feed_min_date="7days",
        feed_force_min=False,
        cat_min_date="30days",
        cat_force_min=True,
        global_min_date="90days",
        global_force_min=False,
    )
    diff_cat = (now - dt_cat_force).total_seconds()
    assert abs(diff_cat - 30 * 86400) < 5

    # 3. 全域強制覆蓋 (大於分類強制)
    dt_global_force = resolve_effective_min_publish_date(
        feed_min_date="7days",
        feed_force_min=False,
        cat_min_date="30days",
        cat_force_min=True,
        global_min_date="90days",
        global_force_min=True,
    )
    diff_glob = (now - dt_global_force).total_seconds()
    assert abs(diff_glob - 90 * 86400) < 5

    # 4. 來源最高特許 (即使全域與分類都強制，來源勾選強制特許依然穿透最高優先)
    dt_feed_force = resolve_effective_min_publish_date(
        feed_min_date="7days",
        feed_force_min=True,
        cat_min_date="30days",
        cat_force_min=True,
        global_min_date="90days",
        global_force_min=True,
    )
    diff_feed = (now - dt_feed_force).total_seconds()
    assert abs(diff_feed - 7 * 86400) < 5

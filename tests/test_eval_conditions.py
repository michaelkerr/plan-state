"""Tests for condition streaks: consecutive days, not consecutive runs."""

import pytest


LOC = "Testville,US"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DISPATCH_DB", db_path)
    from dispatch.store import init_db, connect
    init_db(db_path)
    with connect() as c:
        yield c


def _item(conn, sustained_days, value=85, operator="<="):
    from dispatch.store import insert_item, derive_conditions
    tdef = {"type": "condition", "rules": [{
        "metric": "daily_high", "operator": operator,
        "value": value, "sustained_days": sustained_days,
    }]}
    item_id = insert_item(conn, "lawn", "Overseed", tdef)
    derive_conditions(conn, item_id, tdef)
    conn.commit()
    return item_id


def _weather(conn, day, high, low=50):
    from dispatch.store import new_id, now_iso
    conn.execute(
        "INSERT INTO weather_log (id, location, weather_date, recorded_at, temp_high, temp_low) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (new_id(), LOC, day, now_iso(), high, low),
    )
    conn.commit()


def _cache(conn, item_id):
    row = conn.execute(
        "SELECT consecutive_days, is_met, current_value FROM conditions_cache WHERE item_id=?",
        (item_id,),
    ).fetchone()
    return dict(row)


def test_hourly_runs_do_not_advance_the_streak(conn):
    from dispatch.eval import evaluate_conditions
    item_id = _item(conn, sustained_days=3)
    _weather(conn, "2026-09-20", 80)
    for _ in range(24):
        evaluate_conditions(conn, LOC, "2026-09-20")
    assert _cache(conn, item_id) == {"consecutive_days": 1, "is_met": 0, "current_value": 80}


def test_three_consecutive_days_meet_the_rule(conn):
    from dispatch.eval import evaluate_conditions
    item_id = _item(conn, sustained_days=3)
    for day, high in (("2026-09-18", 84), ("2026-09-19", 82), ("2026-09-20", 80)):
        _weather(conn, day, high)
        evaluate_conditions(conn, LOC, day)
    assert _cache(conn, item_id)["consecutive_days"] == 3
    assert _cache(conn, item_id)["is_met"] == 1


def test_a_miss_resets_the_streak(conn):
    from dispatch.eval import evaluate_conditions
    item_id = _item(conn, sustained_days=2)
    _weather(conn, "2026-09-18", 80)
    _weather(conn, "2026-09-19", 90)
    _weather(conn, "2026-09-20", 80)
    evaluate_conditions(conn, LOC, "2026-09-20")
    assert _cache(conn, item_id)["consecutive_days"] == 1
    assert _cache(conn, item_id)["is_met"] == 0


def test_a_missing_day_ends_the_streak(conn):
    from dispatch.eval import evaluate_conditions
    item_id = _item(conn, sustained_days=2)
    _weather(conn, "2026-09-18", 80)
    _weather(conn, "2026-09-20", 80)
    evaluate_conditions(conn, LOC, "2026-09-20")
    assert _cache(conn, item_id)["consecutive_days"] == 1


def test_no_weather_today_skips(conn):
    from dispatch.eval import evaluate_conditions
    _item(conn, sustained_days=1)
    _weather(conn, "2026-09-19", 80)
    assert evaluate_conditions(conn, LOC, "2026-09-20") == {"skipped": "no weather data for today"}


def test_streak_fires_trigger_end_to_end(conn):
    from dispatch.eval import evaluate_conditions, evaluate_triggers
    from dispatch.store import get_item
    item_id = _item(conn, sustained_days=2)
    _weather(conn, "2026-09-19", 80)
    evaluate_conditions(conn, LOC, "2026-09-19")
    evaluate_triggers(conn, "2026-09-19")
    assert get_item(conn, item_id)["status"] == "watching"
    _weather(conn, "2026-09-20", 80)
    evaluate_conditions(conn, LOC, "2026-09-20")
    evaluate_triggers(conn, "2026-09-20")
    assert get_item(conn, item_id)["status"] == "due"

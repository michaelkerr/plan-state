#!/usr/bin/env python3
"""Test derive_daily_range: daily high/low derived from the 3-hourly forecast."""

from datetime import datetime, timezone

import pytest

import sync_pipeline


CDT_OFFSET = -18000  # UTC-5 (Murfreesboro in summer)


def utc_epoch(iso):
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())


def make_forecast(entries, tz_offset=CDT_OFFSET):
    """entries: list of (utc_iso, temp, temp_min, temp_max)"""
    return {
        "city": {"timezone": tz_offset},
        "list": [
            {
                "dt": utc_epoch(iso),
                "main": {"temp": t, "temp_min": tmin, "temp_max": tmax},
            }
            for iso, t, tmin, tmax in entries
        ],
    }


# A 6 AM local (11:00 UTC) run on July 3. Forecast covers the rest of the
# local day plus entries that belong to July 2 and July 4 local time.
NOW_UTC = datetime(2026, 7, 3, 11, 0, 0)

FORECAST = make_forecast([
    # 2026-07-03 00:00 UTC == July 2, 7 PM local -> previous local day
    ("2026-07-03 00:00:00", 88.4, 88.4, 88.4),
    # July 3 local entries
    ("2026-07-03 12:00:00", 75.4, 75.4, 75.4),   # 7 AM local
    ("2026-07-03 15:00:00", 88.7, 88.7, 88.7),   # 10 AM local
    ("2026-07-03 18:00:00", 95.1, 95.1, 95.1),   # 1 PM local
    ("2026-07-03 21:00:00", 96.7, 96.2, 97.1),   # 4 PM local (peak)
    ("2026-07-04 00:00:00", 88.8, 88.8, 88.8),   # 7 PM local, still July 3
    # 2026-07-04 06:00 UTC == July 4, 1 AM local -> next local day
    ("2026-07-04 06:00:00", 73.3, 73.3, 73.3),
])


class TestDeriveDailyRange:
    def test_high_comes_from_afternoon_forecast(self):
        high, low = sync_pipeline.derive_daily_range(72.0, FORECAST, NOW_UTC)
        assert high == 97.1  # 4 PM peak temp_max, not the 6 AM current reading

    def test_low_blends_current_morning_reading(self):
        high, low = sync_pipeline.derive_daily_range(72.0, FORECAST, NOW_UTC)
        assert low == 72.0  # current 6 AM reading is below all remaining forecast temps

    def test_current_above_forecast_sets_high(self):
        high, low = sync_pipeline.derive_daily_range(99.0, FORECAST, NOW_UTC)
        assert high == 99.0

    def test_forecast_low_below_current(self):
        # evening-ish current reading; forecast morning entry is the low
        high, low = sync_pipeline.derive_daily_range(90.0, FORECAST, NOW_UTC)
        assert low == 75.4

    def test_next_local_day_entries_excluded(self):
        # the 73.3 entry is July 4 local; it must not drag July 3's low down
        high, low = sync_pipeline.derive_daily_range(80.0, FORECAST, NOW_UTC)
        assert low == 75.4
        assert low != 73.3

    def test_previous_local_day_entries_excluded(self):
        # without the UTC->local shift, the 00:00 UTC entry (88.4) would count;
        # with a colder day it would inflate the high
        cold_day = make_forecast([
            ("2026-07-03 00:00:00", 88.4, 88.4, 88.4),  # July 2 local evening
            ("2026-07-03 15:00:00", 60.0, 60.0, 60.0),
            ("2026-07-03 18:00:00", 65.0, 65.0, 65.0),
        ])
        high, low = sync_pipeline.derive_daily_range(55.0, cold_day, NOW_UTC)
        assert high == 65.0

    def test_no_entries_for_today_falls_back_to_current(self):
        tomorrow_only = make_forecast([
            ("2026-07-04 12:00:00", 80.0, 80.0, 80.0),
        ])
        high, low = sync_pipeline.derive_daily_range(71.5, tomorrow_only, NOW_UTC)
        assert high == 71.5
        assert low == 71.5

    def test_empty_forecast_falls_back_to_current(self):
        high, low = sync_pipeline.derive_daily_range(71.5, {"list": []}, NOW_UTC)
        assert (high, low) == (71.5, 71.5)

    def test_missing_forecast_falls_back_to_current(self):
        high, low = sync_pipeline.derive_daily_range(71.5, None, NOW_UTC)
        assert (high, low) == (71.5, 71.5)

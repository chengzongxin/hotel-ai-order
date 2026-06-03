from datetime import datetime

from graph.expected_time import (
    infer_expected_start_time_from_message,
    looks_like_expected_start_time,
    merge_expected_start_time,
    parse_expected_time_to_range,
)


def test_looks_like_accepts_clock_and_yesterday():
    assert looks_like_expected_start_time("09:30")
    assert looks_like_expected_start_time("昨天")
    assert looks_like_expected_start_time("昨")
    assert not looks_like_expected_start_time("1208")


def test_merge_day_and_clock():
    assert merge_expected_start_time("昨天", "09:30") == "昨天 09:30"
    assert merge_expected_start_time("09:30", "昨天") == "昨天 09:30"


def test_infer_short_replies():
    assert infer_expected_start_time_from_message("09:30") == "09:30"
    assert infer_expected_start_time_from_message("昨") == "昨天"
    assert infer_expected_start_time_from_message("1208") is None


def test_parse_yesterday_at_930():
    fixed_now = datetime(2026, 6, 3, 10, 0, 0)
    start, end = parse_expected_time_to_range("昨天 09:30", now=fixed_now)
    assert start == "2026-06-02 09:30:00"
    assert end == "2026-06-02 11:30:00"


def test_parse_tomorrow_morning():
    fixed_now = datetime(2026, 6, 3, 10, 0, 0)
    start, end = parse_expected_time_to_range("明天上午", now=fixed_now)
    assert start == "2026-06-04 08:00:00"
    assert end == "2026-06-04 12:00:00"

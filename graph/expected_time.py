"""期待开工时间的识别、合并与接口字段转换。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_TIME_COLON = re.compile(r"(?<!\d)(\d{1,2})[:：](\d{2})(?!\d)")
_TIME_ZH = re.compile(r"(?<!\d)(\d{1,2})\s*点\s*(\d{1,2})?\s*分?")
_TIME_HALF = re.compile(r"(?<!\d)(\d{1,2})\s*点半")
_DATE_MD = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?")

_DAY_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("大后天", 3),
    ("后天", 2),
    ("明天", 1),
    ("今天", 0),
    ("昨日", -1),
    ("昨天", -1),
    ("前天", -2),
)

_PERIOD_RANGES: tuple[tuple[str, int, int], ...] = (
    ("上午", 8, 12),
    ("中午", 11, 13),
    ("下午", 13, 18),
    ("晚上", 18, 22),
    ("夜间", 18, 22),
)

_LOOKS_LIKE_KEYWORDS = (
    "今天",
    "明天",
    "后天",
    "昨天",
    "前天",
    "上午",
    "中午",
    "下午",
    "晚上",
    "下周",
    "本周",
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
    "星期",
    "月",
    "日",
    "号",
    "点",
    "昨",
)


def normalize_expected_start_time_text(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in {"昨", "昨日"}:
        return "昨天"
    return text


def _contains_day_hint(text: str) -> bool:
    if any(keyword in text for keyword in ("今天", "明天", "后天", "昨天", "前天", "昨", "月", "日", "号")):
        return True
    return bool(_DATE_MD.search(text))


def _contains_clock_time(text: str) -> bool:
    return bool(_TIME_COLON.search(text) or _TIME_ZH.search(text) or _TIME_HALF.search(text) or "点" in text)


def looks_like_expected_start_time(value: str | None) -> bool:
    if not value:
        return False
    text = normalize_expected_start_time_text(value) or ""
    if any(keyword in text for keyword in _LOOKS_LIKE_KEYWORDS):
        return True
    if _DATE_MD.search(text):
        return True
    if _contains_clock_time(text):
        return True
    return False


def looks_like_room_number_only(text: str) -> bool:
    """避免把纯房号误判为时间。"""
    stripped = text.strip()
    if not stripped:
        return False
    if re.fullmatch(r"\d{2,5}", stripped):
        return True
    return bool(re.fullmatch(r"\d{2,5}\s*(?:房间|房|号)?", stripped))


def merge_expected_start_time(existing: str | None, new: str | None) -> str | None:
    existing_norm = normalize_expected_start_time_text(existing)
    new_norm = normalize_expected_start_time_text(new)
    if not new_norm:
        return existing_norm
    if not existing_norm:
        return new_norm

    if _contains_clock_time(new_norm) and not _contains_day_hint(new_norm) and _contains_day_hint(existing_norm):
        return f"{existing_norm} {new_norm}"
    if _contains_day_hint(new_norm) and not _contains_clock_time(new_norm) and _contains_clock_time(existing_norm):
        return f"{new_norm} {existing_norm}"
    return new_norm


def infer_expected_start_time_from_message(text: str) -> str | None:
    """短回复兜底：用户只补充“09:30”“昨天”等时，不依赖 LLM 也能识别。"""
    stripped = text.strip()
    if not stripped or looks_like_room_number_only(stripped):
        return None

    normalized = normalize_expected_start_time_text(stripped)
    if normalized and looks_like_expected_start_time(normalized):
        return normalized
    return None


def _apply_day_offset(base: datetime, text: str) -> datetime:
    if "昨" in text and "昨天" not in text and "昨日" not in text:
        text = f"昨天{text}"
    for keyword, offset in _DAY_KEYWORDS:
        if keyword in text:
            return base + timedelta(days=offset)
    return base


def _apply_calendar_date(base: datetime, text: str) -> datetime:
    match = _DATE_MD.search(text)
    if not match:
        return base
    month = int(match.group(1))
    day = int(match.group(2))
    year = base.year
    candidate = datetime(year, month, day)
    if candidate.date() < base.date() and month < base.month:
        candidate = datetime(year + 1, month, day)
    return candidate.replace(
        hour=base.hour,
        minute=base.minute,
        second=base.second,
        microsecond=base.microsecond,
    )


def _extract_clock_time(text: str) -> tuple[int, int] | None:
    match = _TIME_COLON.search(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute

    match = _TIME_HALF.search(text)
    if match:
        hour = int(match.group(1))
        if 0 <= hour <= 23:
            return hour, 30

    match = _TIME_ZH.search(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    return None


def parse_expected_time_to_range(value: object, now: datetime | None = None) -> tuple[str, str]:
    """把口语时间转换成 App 下单接口使用的起止时间。"""
    text = normalize_expected_start_time_text(str(value).strip() if value is not None else "") or ""
    base = now or datetime.now()

    base = _apply_day_offset(base, text)
    base = _apply_calendar_date(base, text)

    clock = _extract_clock_time(text)
    if clock:
        hour, minute = clock
        start = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + timedelta(hours=2)
        if end.date() != start.date():
            end = start.replace(hour=23, minute=59, second=59, microsecond=0)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

    start_hour, end_hour = 0, 23
    for keyword, period_start, period_end in _PERIOD_RANGES:
        if keyword in text:
            start_hour, end_hour = period_start, period_end
            break

    start = base.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end = base.replace(
        hour=end_hour,
        minute=59 if end_hour == 23 else 0,
        second=59 if end_hour == 23 else 0,
        microsecond=0,
    )
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

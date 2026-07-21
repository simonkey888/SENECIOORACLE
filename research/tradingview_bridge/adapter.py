"""Offline adapter for non-authoritative TradingView research context.

The adapter accepts JSON exported by a local CLI/MCP process.  It has no CDP,
network, TradingView Desktop, SENEX runtime, manifest, or raw-chain write path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .provenance import build_provenance

SCHEMA_VERSION = "senex-tradingview-context-v1"
SOURCE = "tradingview_desktop_unofficial"
CAPTURE_TYPES = frozenset({"ohlcv", "quote", "indicator", "pine", "screenshot"})
RESEARCH_OUTPUT_ROOT = Path("research/tradingview_context")
FORBIDDEN_OUTPUT_ROOTS = (
    Path("results/h011_v3/raw_chain_v1"),
    Path("results/v3/raw"),
    Path("results/v3/state"),
    Path("results/v3/scans"),
)
PROTECTED_SENEX_FIELDS = (
    "record_status",
    "invariants",
    "scan_status",
    "manifest",
    "committed_snapshot",
)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA64_RE = re.compile(r"^[0-9a-f]{64}$")


class BridgeValidationError(ValueError):
    """The exported research envelope is malformed or unverifiable."""


class BridgeSecurityError(RuntimeError):
    """The requested operation violates the local-only isolation contract."""


@dataclass(frozen=True)
class ValidationResult:
    envelope: dict[str, Any]
    capture_age_seconds: float
    stale: bool
    symbol_mismatch: bool
    timeframe_mismatch: bool
    timestamp_mismatch: bool
    accepted: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["warnings"] = list(self.warnings)
        return value


def _parse_time(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BridgeValidationError(f"{field} must be a non-empty ISO-8601 string")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BridgeValidationError(f"{field} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise BridgeValidationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _assert_json_safe(value: Any, *, path: str = "payload") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BridgeValidationError(f"{path} contains NaN or Infinity")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BridgeValidationError(f"{path} contains a non-string key")
            _assert_json_safe(item, path=f"{path}.{key}")
        return
    raise BridgeValidationError(f"{path} contains unsupported type {type(value).__name__}")


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BridgeValidationError("payload is not canonical JSON") from exc


def payload_sha256(payload: Mapping[str, Any]) -> str:
    _assert_json_safe(payload)
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeValidationError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise BridgeValidationError(f"{field} contains NaN or Infinity")
    return number


def _validate_ohlcv(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    bars = payload.get("bars")
    if not isinstance(bars, list) or not bars:
        raise BridgeValidationError("OHLCV payload must contain a non-empty bars list")

    normalized: list[dict[str, Any]] = []
    previous_timestamp: datetime | None = None
    for index, raw_bar in enumerate(bars):
        if not isinstance(raw_bar, dict):
            raise BridgeValidationError(f"bars[{index}] must be an object")
        required = ("timestamp", "open", "high", "low", "close", "volume")
        missing = [field for field in required if field not in raw_bar]
        if missing:
            raise BridgeValidationError(f"bars[{index}] missing fields: {missing}")

        timestamp = _parse_time(raw_bar["timestamp"], field=f"bars[{index}].timestamp")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise BridgeValidationError("OHLCV timestamps must be strictly increasing")
        previous_timestamp = timestamp

        open_price = _number(raw_bar["open"], field=f"bars[{index}].open")
        high = _number(raw_bar["high"], field=f"bars[{index}].high")
        low = _number(raw_bar["low"], field=f"bars[{index}].low")
        close = _number(raw_bar["close"], field=f"bars[{index}].close")
        volume = _number(raw_bar["volume"], field=f"bars[{index}].volume")
        if volume < 0:
            raise BridgeValidationError(f"bars[{index}].volume cannot be negative")
        if high < max(open_price, low, close):
            raise BridgeValidationError(f"bars[{index}].high is inconsistent")
        if low > min(open_price, high, close):
            raise BridgeValidationError(f"bars[{index}].low is inconsistent")

        normalized.append(
            {
                **copy.deepcopy(raw_bar),
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return normalized


def _load_allowlist() -> dict[str, Any]:
    path = Path(__file__).with_name("allowlist.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeSecurityError("read-only tool allowlist is unavailable") from exc
    if not isinstance(data.get("allowed_read_tools"), list):
        raise BridgeSecurityError("allowlist is malformed")
    return data


def validate_tool_name(tool_name: str) -> str:
    """Accept only an exact read operation from the code-enforced allowlist."""

    if not isinstance(tool_name, str) or not tool_name.strip():
        raise BridgeSecurityError("tool name is required")
    tool = tool_name.strip()
    policy = _load_allowlist()
    allowed = frozenset(policy["allowed_read_tools"])
    blocked = frozenset(policy.get("blocked_tools", []))
    blocked_prefixes = tuple(policy.get("blocked_prefixes", []))
    if tool in blocked or tool.startswith(blocked_prefixes):
        raise BridgeSecurityError(f"mutation-capable TradingView tool rejected: {tool}")
    if tool not in allowed:
        raise BridgeSecurityError(f"TradingView tool is not allowlisted: {tool}")
    return tool


def validate_envelope(
    envelope: Mapping[str, Any],
    *,
    expected_symbol: str | None = None,
    expected_timeframe: str | None = None,
    expected_window_start: str | None = None,
    expected_window_end: str | None = None,
    stale_after_seconds: int = 900,
    now: datetime | None = None,
) -> ValidationResult:
    """Validate an offline TradingView export and classify its research fitness."""

    if not isinstance(envelope, Mapping):
        raise BridgeValidationError("envelope must be an object")
    value = copy.deepcopy(dict(envelope))
    required = (
        "schema_version",
        "source",
        "authoritative",
        "symbol",
        "timeframe",
        "captured_at",
        "tradingview_app_version",
        "tradingview_mcp_commit",
        "capture_type",
        "payload",
        "payload_sha256",
    )
    missing = [field for field in required if field not in value]
    if missing:
        raise BridgeValidationError(f"envelope missing fields: {missing}")
    if value["schema_version"] != SCHEMA_VERSION:
        raise BridgeValidationError("unsupported schema_version")
    if value["source"] != SOURCE:
        raise BridgeValidationError("unsupported source")
    if value["authoritative"] is not False:
        raise BridgeSecurityError("authoritative TradingView context is forbidden")
    if not isinstance(value["symbol"], str) or not value["symbol"].strip():
        raise BridgeValidationError("symbol is required")
    if not isinstance(value["timeframe"], str) or not value["timeframe"].strip():
        raise BridgeValidationError("timeframe is required")
    if not isinstance(value["tradingview_app_version"], str) or not value["tradingview_app_version"].strip():
        raise BridgeValidationError("tradingview_app_version is required")
    if not isinstance(value["tradingview_mcp_commit"], str) or not _SHA40_RE.fullmatch(value["tradingview_mcp_commit"]):
        raise BridgeValidationError("tradingview_mcp_commit must be an exact lowercase 40-hex SHA")
    if value["capture_type"] not in CAPTURE_TYPES:
        raise BridgeValidationError("unsupported capture_type")
    if not isinstance(value["payload"], dict):
        raise BridgeValidationError("payload must be an object")
    _assert_json_safe(value["payload"])
    if not isinstance(value["payload_sha256"], str) or not _SHA64_RE.fullmatch(value["payload_sha256"]):
        raise BridgeValidationError("payload_sha256 must be lowercase 64-hex")
    computed_hash = payload_sha256(value["payload"])
    if computed_hash != value["payload_sha256"]:
        raise BridgeValidationError("payload_sha256 mismatch")

    captured_at = _parse_time(value["captured_at"], field="captured_at")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    age = max(0.0, (current - captured_at).total_seconds())
    stale = age > stale_after_seconds

    if value["capture_type"] == "ohlcv":
        value["payload"]["bars"] = _validate_ohlcv(value["payload"])

    symbol_mismatch = expected_symbol is not None and value["symbol"] != expected_symbol
    timeframe_mismatch = expected_timeframe is not None and value["timeframe"] != str(expected_timeframe)
    timestamp_mismatch = False
    if expected_window_start is not None or expected_window_end is not None:
        if expected_window_start is None or expected_window_end is None:
            raise BridgeValidationError("both expected window timestamps are required")
        start = _parse_time(expected_window_start, field="expected_window_start")
        end = _parse_time(expected_window_end, field="expected_window_end")
        if end <= start:
            raise BridgeValidationError("expected window end must be after start")
        if value["capture_type"] == "ohlcv":
            bars = value["payload"]["bars"]
            first = _parse_time(bars[0]["timestamp"], field="first bar timestamp")
            last = _parse_time(bars[-1]["timestamp"], field="last bar timestamp")
            timestamp_mismatch = first > end or last < start
        else:
            timestamp_mismatch = not (start <= captured_at <= end)

    warnings: list[str] = []
    if stale:
        warnings.append("stale_capture")
    if symbol_mismatch:
        warnings.append("symbol_mismatch")
    if timeframe_mismatch:
        warnings.append("timeframe_mismatch")
    if timestamp_mismatch:
        warnings.append("timestamp_mismatch")
    accepted = not (stale or symbol_mismatch or timeframe_mismatch or timestamp_mismatch)

    value["symbol"] = value["symbol"].strip()
    value["timeframe"] = value["timeframe"].strip()
    value["captured_at"] = captured_at.isoformat().replace("+00:00", "Z")
    return ValidationResult(
        envelope=value,
        capture_age_seconds=age,
        stale=stale,
        symbol_mismatch=symbol_mismatch,
        timeframe_mismatch=timeframe_mismatch,
        timestamp_mismatch=timestamp_mismatch,
        accepted=accepted,
        warnings=tuple(warnings),
    )


def compute_window_context(
    validated: ValidationResult,
    *,
    market_window_start: str,
    market_window_end: str,
) -> dict[str, Any]:
    """Compute descriptive, non-authoritative metrics for one 300-second window."""

    if validated.envelope["capture_type"] != "ohlcv":
        raise BridgeValidationError("window context requires an OHLCV capture")
    start = _parse_time(market_window_start, field="market_window_start")
    end = _parse_time(market_window_end, field="market_window_end")
    if (end - start).total_seconds() != 300:
        raise BridgeValidationError("H-011 research window must be exactly 300 seconds")

    bars = validated.envelope["payload"]["bars"]
    selected = [
        bar
        for bar in bars
        if start <= _parse_time(bar["timestamp"], field="bar timestamp") <= end
    ]
    if not selected:
        raise BridgeValidationError("OHLCV capture does not overlap the H-011 window")

    first = selected[0]
    last = selected[-1]
    high = max(bar["high"] for bar in selected)
    low = min(bar["low"] for bar in selected)
    open_price = first["open"]
    close = last["close"]
    total_volume = sum(bar["volume"] for bar in selected)
    window_return = None if open_price == 0 else (close / open_price) - 1.0

    squared_returns: list[float] = []
    previous_close: float | None = None
    for bar in selected:
        current_close = bar["close"]
        if previous_close is not None and previous_close > 0 and current_close > 0:
            squared_returns.append(math.log(current_close / previous_close) ** 2)
        previous_close = current_close
    realized_proxy = math.sqrt(sum(squared_returns)) if squared_returns else 0.0

    movements = [
        abs(bar["high"] - bar["low"]) if bar["open"] == 0
        else abs(bar["high"] - bar["low"]) / abs(bar["open"])
        for bar in selected
    ]
    first_time = _parse_time(first["timestamp"], field="tradingview_first_bar")
    last_time = _parse_time(last["timestamp"], field="tradingview_last_bar")

    return {
        "authoritative": False,
        "research_only": True,
        "symbol": validated.envelope["symbol"],
        "timeframe": validated.envelope["timeframe"],
        "market_window_start": start.isoformat().replace("+00:00", "Z"),
        "market_window_end": end.isoformat().replace("+00:00", "Z"),
        "tradingview_first_bar": first_time.isoformat().replace("+00:00", "Z"),
        "tradingview_last_bar": last_time.isoformat().replace("+00:00", "Z"),
        "timestamp_delta": {
            "first_bar_minus_window_start_seconds": (first_time - start).total_seconds(),
            "last_bar_minus_window_end_seconds": (last_time - end).total_seconds(),
        },
        "ohlc": {"open": open_price, "high": high, "low": low, "close": close},
        "range": high - low,
        "return": window_return,
        "realized_volatility_proxy": realized_proxy,
        "volume": total_volume,
        "maximum_bar_movement": max(movements),
        "bar_count": len(selected),
    }


def _is_relative_to(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_path(output_path: str | Path, *, repo_root: str | Path) -> Path:
    root = Path(repo_root).resolve()
    research_root = (root / RESEARCH_OUTPUT_ROOT).resolve()
    candidate = Path(output_path)
    candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()

    for forbidden in FORBIDDEN_OUTPUT_ROOTS:
        if _is_relative_to(candidate, (root / forbidden).resolve()):
            raise BridgeSecurityError(f"authoritative/runtime output path rejected: {forbidden}")
    if not _is_relative_to(candidate, research_root):
        raise BridgeSecurityError("TradingView context may only be written under research/tradingview_context")
    if candidate.exists() and candidate.is_symlink():
        raise BridgeSecurityError("symlink output targets are forbidden")
    return candidate


def safe_import_context(
    envelope: Mapping[str, Any],
    *,
    output_path: str | Path,
    repo_root: str | Path,
    **validation_kwargs: Any,
) -> dict[str, Any]:
    """Validate and write a canonical research record under the isolated root."""

    validation = validate_envelope(envelope, **validation_kwargs)
    if not validation.accepted:
        raise BridgeValidationError(
            "capture is not automatically acceptable: " + ", ".join(validation.warnings)
        )
    target = validate_output_path(output_path, repo_root=repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "classification": {
            "local_only": True,
            "optional": True,
            "research_only": True,
            "authoritative": False,
            "production_dependency": False,
            "northflank_dependency": False,
            "raw_chain_input": False,
            "resolution_source": False,
        },
        "provenance": build_provenance(validation.envelope).to_dict(),
        "validation": validation.to_dict(),
        "envelope": validation.envelope,
    }
    encoded = json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    target.write_text(encoded, encoding="utf-8")
    return record


def associate_research_context(
    senex_record: Mapping[str, Any],
    validation: ValidationResult,
    *,
    scan_id: str | None = None,
    condition_id: str | None = None,
) -> dict[str, Any]:
    """Return a copy with a research-only attachment and protected fields intact."""

    if not validation.accepted:
        raise BridgeValidationError("unaccepted TradingView context cannot be associated")
    before = copy.deepcopy(dict(senex_record))
    after = copy.deepcopy(before)
    attachment = {
        "classification": "NON_AUTHORITATIVE_RESEARCH_CONTEXT",
        "scan_id": scan_id,
        "condition_id": condition_id,
        "symbol": validation.envelope["symbol"],
        "timeframe": validation.envelope["timeframe"],
        "captured_at": validation.envelope["captured_at"],
        "capture_type": validation.envelope["capture_type"],
        "payload_sha256": validation.envelope["payload_sha256"],
        "provenance": build_provenance(validation.envelope).to_dict(),
    }
    after.setdefault("research_context", {})["tradingview"] = attachment

    for field in PROTECTED_SENEX_FIELDS:
        if before.get(field) != after.get(field):
            raise BridgeSecurityError(f"protected SENEX field changed: {field}")
    return after

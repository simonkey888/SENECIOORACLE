# Local usage guide

This guide describes a manual, read-only research workflow. It is not a SENEX
runtime or deployment procedure.

## Preconditions

- TradingView Desktop installed locally.
- A valid TradingView subscription for the data/features being viewed.
- Node.js available only in the separate upstream-tool directory.
- Upstream repository pinned to:
  `55534aab8c11f24655b7d8d4de82e6bece14c8b4`.
- CDP bound only to loopback, normally `127.0.0.1:9222`.

Never expose the CDP debug port to LAN, VPN peers, containers, a public
interface, or the internet. Do not request or store TradingView credentials in
SENEX.

## 1. Install the external optional tool

Outside the SENEX repository:

```bash
git clone https://github.com/tradesdontlie/tradingview-mcp.git
cd tradingview-mcp
git checkout 55534aab8c11f24655b7d8d4de82e6bece14c8b4
npm install
```

Review the upstream README, license, security guidance, disclaimer, and current
TradingView Terms of Use before running it.

## 2. Launch TradingView Desktop with loopback CDP

Use the upstream platform-specific launcher or a local application invocation
with:

```text
--remote-debugging-address=127.0.0.1
--remote-debugging-port=9222
```

Verify locally that the listener is bound to loopback only. Stop immediately if
it is bound to `0.0.0.0`, a LAN address, or an externally reachable interface.

## 3. Use only the SENEX read allowlist

The operator must request only these logical operations:

```text
chart_get_state
quote_get
data_get_ohlcv
data_get_study_values
data_get_pine_lines
data_get_pine_labels
data_get_pine_tables
data_get_pine_boxes
capture_screenshot
replay_status
```

Before accepting exported content, run `validate_tool_name()` against the exact
logical tool name. UI mutation, alert mutation, Pine writes, watchlist writes,
replay trading, symbol/timeframe automation, drawing mutations, and indicator
mutations are denied.

## 4. Export JSON

Convert the local CLI/MCP output into the envelope defined by `schema.json`.
Keep the original symbol, timeframe, capture timestamp, TradingView Desktop
version, exact upstream commit, and capture type.

Calculate the payload hash with the SENEX adapter:

```python
from research.tradingview_bridge import payload_sha256

envelope["payload_sha256"] = payload_sha256(envelope["payload"])
```

Do not label TradingView data as authoritative.

## 5. Validate and import

```python
from datetime import datetime, timezone
from research.tradingview_bridge import safe_import_context

record = safe_import_context(
    envelope,
    repo_root=".",
    output_path="research/tradingview_context/example.json",
    expected_symbol="BINANCE:BTCUSDT",
    expected_timeframe="5",
    expected_window_start="2026-07-21T12:00:00Z",
    expected_window_end="2026-07-21T12:05:00Z",
    now=datetime.now(timezone.utc),
)
```

The adapter rejects authority escalation, invalid hashes, malformed OHLCV,
NaN/Infinity, stale captures, mismatched symbol/timeframe/window, mutation tool
names, and output paths outside the research root.

## 6. Human review

Review the imported provenance, warnings, timestamps, symbol, timeframe,
payload hash, screenshot association, and descriptive metrics. Context may
support research notes or visual comparison only.

It must not modify:

```text
record_status
market identity
resolution outcome
invariant PASS/FAIL
scan_status
manifest chain
raw_chain_v1
shadow execution eligibility
```

## 7. Live-validation record

When the local app and account are unavailable, record:

```text
LIVE_TRADINGVIEW_VALIDATION=NOT_EXECUTED
```

Do not substitute mocked connectivity for a live validation claim. Offline
schema, security, path-isolation, provenance, and architecture tests remain
valid independently.

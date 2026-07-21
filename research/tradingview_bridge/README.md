# SENEX Phase III-A — TradingView Research Bridge

This package is an optional, local-only adapter for importing JSON exported by
a separately installed TradingView Desktop MCP/CLI tool. It is deliberately
outside the SENEX runtime and authority boundary.

## Permanent classification

```text
LOCAL_ONLY=true
OPTIONAL=true
RESEARCH_ONLY=true
AUTHORITATIVE=false
PRODUCTION_DEPENDENCY=false
NORTHFLANK_DEPENDENCY=false
RAW_CHAIN_INPUT=false
RESOLUTION_SOURCE=false
```

TradingView context cannot determine or modify market identity, resolution,
`record_status`, invariant results, `scan_status`, manifests, the committed
snapshot, raw-chain continuity, or shadow-execution eligibility.

## Upstream inspected

```text
repository=https://github.com/tradesdontlie/tradingview-mcp
commit=55534aab8c11f24655b7d8d4de82e6bece14c8b4
package_version=1.0.0
license=MIT with additional TradingView/terms and trademark notice
runtime=Node.js ES modules
production_dependencies=@modelcontextprotocol/sdk ^1.12.1; chrome-remote-interface ^0.33.2
```

The upstream tool connects to a locally running TradingView Desktop process by
Chrome DevTools Protocol. It relies on undocumented internal application
structures and may break after TradingView updates. It requires an installed
application and a valid subscription and must not be used to bypass a paywall,
access control, subscription restriction, or TradingView Terms of Use.

No upstream source code is vendored here. SENEX contains only a small Python
adapter, a JSON contract, a deny-by-default read allowlist, synthetic fixtures,
tests, and documentation.

## Authority boundary

The adapter consumes previously exported JSON. It does not:

- launch TradingView Desktop;
- connect to CDP;
- open a network port;
- authenticate to TradingView;
- install Node.js or the upstream MCP package;
- write to the SENEX results tree;
- modify `raw_chain_v1`;
- participate in production startup, scanning, replay, resolution, or deploy.

Allowed output root:

```text
research/tradingview_context/
```

Explicitly rejected output roots:

```text
results/h011_v3/raw_chain_v1
results/v3/raw
results/v3/state
results/v3/scans
```

## Envelope

```json
{
  "schema_version": "senex-tradingview-context-v1",
  "source": "tradingview_desktop_unofficial",
  "authoritative": false,
  "symbol": "BINANCE:BTCUSDT",
  "timeframe": "5",
  "captured_at": "2026-07-21T12:05:00Z",
  "tradingview_app_version": "unknown",
  "tradingview_mcp_commit": "55534aab8c11f24655b7d8d4de82e6bece14c8b4",
  "capture_type": "ohlcv",
  "payload": {},
  "payload_sha256": "64-lowercase-hex"
}
```

The SHA-256 is calculated from canonical JSON for `payload`: UTF-8, sorted
keys, no insignificant whitespace, and no NaN or Infinity.

## Code-enforced read allowlist

Only exact names in `allowlist.json` are accepted. Unknown tools and all
mutation-capable families are rejected. The initial allowlist is:

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

This policy is not merely an agent instruction. `validate_tool_name()` loads
and enforces the deny-by-default policy in code.

## Research functions

`validate_envelope()` validates identity, schema, authority, provenance,
payload integrity, finite numeric values, OHLCV structure, age, symbol,
timeframe, and optional expected-window overlap.

`compute_window_context()` relates one exact 300-second H-011 window to TradingView
bars and returns descriptive, non-authoritative values:

- first and last bar timestamps;
- timestamp deltas;
- OHLC and range;
- return;
- realized-volatility proxy;
- volume;
- maximum bar movement.

`safe_import_context()` writes only under `research/tradingview_context/` after
successful validation and mismatch checks.

`associate_research_context()` attaches provenance metadata to a copy of a
SENEX record while proving protected authoritative fields remain unchanged.

## Screenshot and Pine research

Screenshots may be associated with `scan_id`, `condition_id`, symbol,
timeframe, capture timestamp, and payload hash. They remain complementary
human-review evidence and never resolution evidence.

Pine output may be used to visualize historical H-011 windows, signals,
rejections, volatility, and window boundaries. The bridge does not set, save,
or publish Pine source and does not mutate drawings, indicators, alerts,
watchlists, chart identity, or replay trades.

## Testing

Offline tests use synthetic fixtures only:

```bash
python -m pytest research/tradingview_bridge/tests -q
```

The Phase III-A workflow additionally runs the existing H-011 and global
suites. It does not install TradingView Desktop, Node.js, the MCP server, or a
real CDP endpoint.

## Live validation status

```text
LIVE_TRADINGVIEW_VALIDATION=NOT_EXECUTED
```

This status is expected when TradingView Desktop, a valid account, or a local
graphical session is unavailable. It does not weaken schema, allowlist, path,
provenance, or architecture-isolation tests.

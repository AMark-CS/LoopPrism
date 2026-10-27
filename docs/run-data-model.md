# Run / step / span data model

Status: accepted design, partially implemented (see "Implementation status").

## Goals

- Group captured activity into **runs** an agent developer recognises (one task, goal to outcome).
- Keep enough data per span to **replay** a run later (full inputs and outputs, not previews).
- Stay interoperable with OpenTelemetry (W3C trace and span IDs, `traceparent`).
- Say how much to trust a grouping (`correlation_source`).

## Vocabulary

```
Session   a conversation or long-lived client connection   (many runs)
  Run     one agent task, user goal to final outcome        (the `traces` table)
    Span  one atomic operation, nested via parent_span_id
          kinds: agent.step, llm.call, mcp.tool.call, mcp.list, ...
```

A **step** is not a table. It is a span of kind `agent.step`: one loop iteration whose
children are the `llm.call` and the `mcp.tool.call` spans it triggered. Nesting gives
loop detection and cost attribution the LLM-to-tool link directly instead of inferring it.

## Schema

### Runs (`traces`)

| Column | Meaning |
|---|---|
| `session_id` | Conversation/session this run belongs to. `conversation_id` is kept as a deprecated alias. |
| `status` | `running`, `succeeded`, `failed`, `abandoned` |
| `ended_at` | Set when the run is closed |
| `outcome` | Free-form label, used by evals later |
| `correlation_source` | `explicit`, `session`, `heuristic` |

### Spans (`spans`)

| Column | Meaning |
|---|---|
| `seq` | Ordinal within the run, assigned at insert. Ordering must not depend on timestamps. |
| `kind` | Span kind (`agent.step`, `llm.call`, `mcp.tool.call`, ...). Mirrors `span_type` for now. |
| `step_index` | Which loop iteration, when known |
| `model`, `tokens_in`, `tokens_out`, `tokens_cached`, `cost_usd`, `finish_reason` | LLM spans |
| `error_type` | Machine-readable error class |

### Payloads (planned)

A separate table keyed by `(span_id, role)` with `role` in `input` / `output`, content
compressed and hashed. Keeps hot span rows small and dedupes repeated prompts. Redaction
runs before anything is written. Per-tool size caps and a per-server opt-out apply.

### IDs (planned)

W3C format: 32-hex trace ID, 16-hex span ID, instead of `uuid4`.

## Correlation ladder

The proxy tries these in order and records the first that succeeds in `correlation_source`.

1. **Explicit.** W3C `traceparent` header, or `params._meta.traceparent` in the MCP request
   body. Set by the SDK or an OTel-instrumented client. The only path that can link an LLM
   `tool_use` ID to the matching MCP call. `X-LoopPrism-Trace-Id` stays as a fallback.
2. **Session.** `Mcp-Session-Id` header plus `clientInfo` from `initialize`. Groups calls
   into a session but does not split it into runs.
3. **Heuristic.** Within a session, start a new run after a configurable idle gap
   (default 30s) or on re-`initialize`. Marked `heuristic`.

### Implementation notes

- A valid W3C `traceparent` (header first, then `params._meta`) becomes the run id. The
  caller's span id is stored in the span's attributes as `remote_parent_span_id`, **not** in
  `parent_span_id`: that span lives in the caller's tracer, and the dashboard drops spans whose
  parent is not in the run.
- `Mcp-Session-Id` is issued per server, so the same agent talking to two servers gets two
  session runs unless it sends `traceparent`. Sessionless traffic is grouped by client address
  plus user-agent across servers, which merges two agents sharing both. Both are approximations;
  `correlation_source` records which one was used.
- `initialize` has no session header (the server assigns one in its response). The proxy binds
  the issued id to the run that carried `initialize`, so follow-up calls stay in it.
- The idle gap defaults to 30s: `LOOPPRISM_RUN_IDLE_SECONDS`, or `run_idle_seconds` under
  `[proxy]` in `config.toml`. Run state is in memory and is lost on proxy restart.

## Run lifecycle

The SDK sends an explicit run end with an outcome. Otherwise a run is closed after an idle
timeout and marked `abandoned`; abandoned runs are themselves a reliability signal.
`finalize_trace` currently runs after every span; it should only refresh summary stats,
while closing a run is a separate operation.

## Implementation status

- [x] Additive migration of the columns above (existing databases upgrade in place)
- [x] `seq` assigned per run; `get_trace` orders by it
- [x] `attributes_json` merge fixed (was concatenating two JSON objects into invalid JSON)
- [x] `create_trace` accepts `session_id`, `correlation_source`
- [ ] Run close / idle timeout / `abandoned`
- [x] Correlation ladder in the proxy (`trace/correlation.py`)
- [ ] Payload table and redaction
- [ ] W3C IDs
- [ ] `agent.step` and `llm.call` spans via SDK / OTel ingest

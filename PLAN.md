# job-scout — Pipeline, Alerts, and Interview Prep — Implementation Plan

## Problem Statement

Job-scout today is stateless. Every chat session starts fresh: searches go straight to the screen, there is no memory of which jobs the user has acted on, no way to revisit a query later, and no support for the natural "prep me for this interview" follow-up. Users have to track applications in a spreadsheet, re-type the same searches, and leave the tool to prepare for interviews.

This plan adds three persistence-and-AI features that turn job-scout into a small job-hunting workspace, accessed primarily through plain-English chat: an application pipeline, saved/named alerts, and on-demand interview prep — all without breaking the existing 6-tool agent surface.

## User Story

As a job-seeker using job-scout in chat mode, when I find a promising listing, I want to track its status, re-run my search later to see only new postings, and ask the agent to prep me for the interview — so that job-scout is the single tool I use end-to-end, not just a search box.

## Design Spec

### Feature 1 — Application Pipeline

A locally-persisted tracker for jobs the user is acting on, keyed primarily by URL. Statuses: `interested`, `applied`, `phone_screen`, `interviewing`, `offer`, `rejected`.

**Interaction model (chat-first):**
- "track job 2 as applied" -> `track_job(index=2, status="applied")`
- "show my pipeline" -> `show_pipeline()`
- "update Stripe to interviewing" -> `update_status(identifier="Stripe", status="interviewing")`
- "drop job 3 from my pipeline" -> `remove_from_pipeline(identifier="3")`

**Cross-cutting effect:** any time `search_jobs` (or any other tool that calls `render_table`) renders results, listings whose URL matches a pipeline entry get a status tag inline in the Title column (e.g. `Senior MLE [applied]`). This is the only cross-feature coupling; no new column is added so existing screen widths stay intact.

**State:**
- Persisted: `~/.job-scout/pipeline.json` (indented JSON array)
- In-memory: read on each tool call (file is small, single-user, simpler than caching)

**Edge cases:**
- Same URL tracked twice -> overwrites status, refreshes `date_tracked`
- Tracking a listing with no URL -> reject with friendly error (URL is the primary key)
- `update_status` by partial match that matches multiple entries -> return the matches and ask the user to disambiguate by index
- Empty pipeline + `show_pipeline()` -> "No tracked jobs yet. Try: 'track job 1 as applied'"
- Pipeline file is malformed JSON -> log a warning, treat as empty, do NOT delete (user may be hand-editing)

### Feature 2 — Job Alerts

Named, re-runnable searches that on each run report only listings unseen in prior runs.

**Interaction model:**
- "save this as my ml-remote alert" -> `save_alert(name="ml-remote")` captures the most recent search params from `ChatState`
- "save this search" -> `save_alert()` auto-names from the query, e.g. `"ml-engineer-remote"` (slugified)
- "check my alerts" -> `run_alerts()` runs each, prints a header per alert plus a Rich table of new listings only
- "list alerts" / "delete ml-remote"

**State:**
- Persisted: `~/.job-scout/alerts.json` (indented JSON array)
- `seen_urls` lives as a list in JSON (not a set; not JSON-serializable) and is converted to/from `set` only at use-time
- Capped at 5000 URLs per alert; oldest entries dropped (FIFO) on overflow to keep file small

**CLI shortcut:** `python3 main.py --alerts` runs the same `run_alerts()` logic outside chat. AI provider not required for this path (alerts are pure search + URL-set diffing). Mutually exclusive with `--chat` and with `QUERY`.

**Edge cases:**
- `save_alert` called with no prior search this session -> return "Run a search first, then I can save it as an alert."
- `save_alert(name=X)` where X already exists -> overwrite policy: update the existing alert's query/filters, preserve `seen_urls` and `created_at`. Return message states "Updated existing alert 'X'."
- `run_alerts()` with no alerts -> "No alerts saved. Try: 'save this as my <name> alert'"
- An alert returns 0 new listings -> print "<name>: no new listings since <last_run>." instead of an empty table
- A source errors during an alert run -> existing `run_pipeline` already swallows per-source errors; we don't mark the alert as failed
- Auto-name collision -> append `-2`, `-3`, ...

### Feature 3 — Interview Prep

One LLM call that generates structured prep notes for a single listing.

**Interaction model:**
- "prep me for the interview at job 3" -> `prep_interview(index=3)`

**Output is one plain-text string** rendered by the tool to the console, with these sections:
1. Behavioral questions (3)
2. Technical / role-specific questions (3-5)
3. Questions to ask the interviewer (2)
4. Key things to emphasize (1 short paragraph)
5. Footer: "Note: generated from listing metadata only; the full JD at <url> may reveal more."

**Edge cases:**
- Index out of range -> "Result #N does not exist (have M)."
- No AI key -> the chat REPL is already gated on `detect_provider()`; the tool can assume `state.llm` is set. We still wrap the LLM call in `try/except` and return a friendly error if it fails at runtime.
- Listing with sparse metadata (no location or no type) -> still call the LLM but pass placeholder text "(unspecified)"; the prompt is told to handle this.

## Wireframe / Interaction Spec

### Chat — track and show pipeline

```
you> track job 2 as applied
Tracked #2 — Senior ML Engineer @ Stripe — status: applied

you> show my pipeline
                     My Pipeline (4 tracked)
 +----------------------------------------------------------+
 | APPLIED (2)                                              |
 |   1.  Stripe         Senior ML Engineer       2026-05-10 |
 |   2.  Anthropic      Research Engineer        2026-05-09 |
 | INTERESTED (1)                                           |
 |   3.  Cohere         MLE, Infra               2026-05-11 |
 | PHONE_SCREEN (1)                                         |
 |   4.  OpenAI         Member of Tech Staff     2026-05-08 |
 +----------------------------------------------------------+
 Tip: "update job 3 to phone_screen" or "drop job 4".
```

### Chat — pipeline status tag in search results

```
you> search ml engineer remote
                     job-scout results for "ml engineer remote"
 +---+------------------------------------------+-----------+--------+
 | # | Title                                    | Company   | ...    |
 +---+------------------------------------------+-----------+--------+
 | 1 | Senior ML Engineer  [applied]            | Stripe    | ...    |
 | 2 | Staff MLE  [interested]                  | Cohere    | ...    |
 | 3 | ML Platform Engineer                     | Datadog   | ...    |
 +---+------------------------------------------+-----------+--------+
```

Tag style: dim gray, square brackets, inserted after the title, ASCII-only so it never breaks the existing BiDi-sanitization pass in `_safe_cell`.

### Chat — save and run alerts

```
you> save this as my ml-remote alert
Saved alert "ml-remote" (query: "ml engineer", location: "remote", limit: 50).

you> check my alerts
ml-remote: 3 new listings since 2026-05-09
                          new listings for "ml engineer" (remote)
 +---+---------------------+-------------+--------------+----------+
 | # | Title               | Company     | Location     | Source   |
 +---+---------------------+-------------+--------------+----------+
 | 1 | Senior MLE          | Replicate   | Remote       | remotive |
 | 2 | MLE, Inference      | Modal       | Remote (US)  | remoteok |
 | 3 | Applied Scientist   | Anthropic   | Remote       | jobspy   |
 +---+---------------------+-------------+--------------+----------+

research-internships: no new listings since 2026-05-11.
```

After `run_alerts()`, `state.results` is left set to the LAST alert's new listings so the user can immediately say "track job 1 as applied" or "open job 2".

### CLI — `--alerts`

```
$ python3 main.py --alerts
ml-remote: 3 new listings since 2026-05-09
[ ...table... ]
research-internships: no new listings since 2026-05-11.
```

`--alerts` is mutually exclusive with `QUERY`, `--chat`, and all search-modifying flags. It prints to stdout and exits 0 even if zero new listings — having zero is a normal outcome.

### Chat — interview prep

```
you> prep me for the interview at job 3
Interview prep — ML Platform Engineer @ Datadog

Behavioral
  - Tell me about a time you owned an ML system end-to-end in production.
  - Describe a tradeoff you made between model quality and latency.
  - How do you onboard onto an unfamiliar ML codebase?

Technical
  - Walk through how you'd design a feature store for a recommendation system.
  - How would you debug a sudden 30% drop in model offline AUC?
  - Compare batch vs streaming inference for a real-time use case.
  - What's your approach to model versioning and rollback?

Ask the interviewer
  - What does the on-call rotation look like for ML platform engineers?
  - How is success measured for this role in the first six months?

Emphasize
  Lean into production ownership and observability for ML systems —
  the title signals platform/infra over pure modeling.

Note: generated from listing metadata only; the full JD at
https://... may reveal more.
```

## Technical Approach

### New module layout

```
job-scout/
+- tracker/
|  +- __init__.py         # empty, just makes it a package
|  +- pipeline.py         # load/save pipeline.json, status helpers, status-by-URL lookup
|  +- alerts.py           # load/save alerts.json, run_alerts logic
+- ai/
|  +- interview.py        # generate_prep(listing, llm) -> str   [NEW]
|  +- tools.py            # ChatState additions + 9 new tools    [MODIFIED]
|  +- agent.py            # /help text update                    [MODIFIED]
+- output/
|  +- table.py            # accept optional pipeline status map  [MODIFIED]
+- main.py                # add --alerts CLI shortcut             [MODIFIED]
+- PLAN.md
```

No new pip dependencies. Stdlib only: `json`, `pathlib`, `datetime`, `re`.

### `tracker/pipeline.py`

```python
# Public API
DATA_DIR: Path = Path.home() / ".job-scout"
PIPELINE_PATH: Path = DATA_DIR / "pipeline.json"

VALID_STATUSES: tuple[str, ...] = (
    "interested", "applied", "phone_screen",
    "interviewing", "offer", "rejected",
)

def load_pipeline() -> list[dict]: ...
def save_pipeline(entries: list[dict]) -> None: ...
def upsert(entry: dict) -> None: ...   # match by URL, replace; else append
def remove_by_url(url: str) -> bool: ...
def find_matches(identifier: str, entries: list[dict]) -> list[int]: ...
    # identifier may be int-string (1-based index into entries) or substring
    # of company or title (case-insensitive) — returns matching indices.
def status_by_url(entries: list[dict] | None = None) -> dict[str, str]: ...
    # convenience for the table renderer; loads if entries not passed
```

**Pipeline entry schema (JSON):**

```json
{
  "title": "Senior ML Engineer",
  "company": "Stripe",
  "url": "https://stripe.com/jobs/123",
  "source": "jobspy",
  "location": "Remote (US)",
  "job_type": "full-time",
  "status": "applied",
  "date_tracked": "2026-05-10T14:22:11+00:00"
}
```

Times are ISO 8601 UTC. URL is the primary key.

### `tracker/alerts.py`

```python
ALERTS_PATH: Path = DATA_DIR / "alerts.json"
SEEN_URL_CAP: int = 5000

def load_alerts() -> list[dict]: ...
def save_alerts(alerts: list[dict]) -> None: ...
def upsert_alert(alert: dict) -> None: ...   # match by name
def delete_alert(name: str) -> bool: ...
def slugify(text: str) -> str: ...
def run_all_alerts(console: Console) -> list[tuple[dict, list[JobListing]]]: ...
    # Runs every alert, returns (alert, new_listings) tuples.
    # Mutates alerts in place (updates last_run, seen_urls) and saves.
    # Renders headers and tables itself (so it works in chat + CLI).
    # No AI provider needed.
```

**Alert entry schema (JSON):**

```json
{
  "name": "ml-remote",
  "query": "ml engineer",
  "job_type": "any",
  "location": "remote",
  "limit": 50,
  "sources": null,
  "created_at": "2026-05-09T10:00:00+00:00",
  "last_run": "2026-05-11T08:00:00+00:00",
  "seen_urls": ["https://...", "https://..."]
}
```

`sources` is null = use full registry; otherwise list of source `.name` values.

### `ai/interview.py`

```python
def generate_prep(listing: JobListing, llm: Any) -> str: ...
```

Single function. Calls `llm.invoke([SystemMessage, HumanMessage])`. Returns a printable string. No retries (the agent will surface failures).

**System prompt:**

```
You are an interview-prep coach for software/ML candidates. Given a job
listing's metadata, produce a structured prep brief.

Output EXACTLY these sections, in this order, using these literal headers:

Behavioral
  - <question 1>
  - <question 2>
  - <question 3>

Technical
  - <question 1>
  - <question 2>
  - <question 3>
  - <question 4>   (optional)
  - <question 5>   (optional, only if clearly distinct)

Ask the interviewer
  - <question 1>
  - <question 2>

Emphasize
  <one short paragraph, 1-3 sentences>

Rules:
- Questions must be specific to the role and company context, never generic
  filler like "Tell me about yourself".
- If a field is "(unspecified)", still produce useful questions by leaning on
  the other fields.
- Do not invent details about the company beyond what's implied by the title
  and listing type.
- No preamble, no closing remark, no markdown headers (#), no code fences.
```

**Human prompt:**

```
Listing:
Title: {title}
Company: {company}
Location: {location}
Type: {job_type}
```

After receiving the LLM response, the tool prepends a one-line header (`Interview prep — {title} @ {company}`) and appends the URL footer. Total output is one string; no Rich markup beyond the header line.

### `ChatState` additions

In `ai/tools.py`, add to `ChatState`:

```python
last_job_type: str | None = None
last_location: str | None = None
last_sources: list[str] | None = None
last_limit: int = DEFAULT_LIMIT
```

`search_jobs` sets all four on each call. `save_alert` reads them.

Also extend `ChatState.summary()` so the agent sees "last filters: type=internship, location=remote".

### Pipeline status tags in the results table

`output/table.py::render_table` gets a new optional parameter:

```python
def render_table(
    listings: list[JobListing],
    query: str,
    show_match: bool = False,
    pipeline_status: dict[str, str] | None = None,
) -> None: ...
```

When `pipeline_status` is provided and `listing.url` is a key, the Title cell renders as `<title> <tag>` where `<tag>` is `"[applied]"`, `"[interested]"`, etc. — appended as a separate dim-styled run via `Text.append`, so it survives the existing BiDi-sanitizer.

All existing call sites stay unchanged — the new arg is optional and defaults to `None`. We do NOT change them. Pipeline tagging is opted-into by the chat tools (`search_jobs`, `filter_results`, `match_resume`, `show_pipeline`) by passing `pipeline.status_by_url()`. The non-chat CLI search path stays untagged, which is fine — pipeline is a chat-mode feature.

### `main.py` `--alerts` flag

Add a single new flag:

```python
@click.option(
    "--alerts",
    "run_alerts_flag",
    is_flag=True,
    default=False,
    help="Run all saved alerts and exit.",
)
```

In `cli()`, very early (before `_maybe_run_setup` so we don't prompt for AI keys):

```python
if run_alerts_flag:
    conflicts = []  # collect QUERY, --chat, --type != any, etc.
    if conflicts:
        raise click.UsageError("--alerts is mutually exclusive with: " + ", ".join(conflicts))
    from tracker.alerts import run_all_alerts
    run_all_alerts(console)
    return
```

### New agent tools (Pydantic args + return contract)

The spec headline says "3 new tools" referring to *features*; the body lists 4 pipeline + 4 alert + 1 interview = **9 tools**. We implement all 9. All return `str` (LangChain contract). All print Rich output themselves where appropriate and return a short status string the LLM can summarize.

**1. `track_job(index, status)`**

```python
class TrackJobArgs(BaseModel):
    index: int = Field(..., description="1-based index in current search results.")
    status: Literal["interested","applied","phone_screen","interviewing","offer","rejected"] = Field(
        "interested", description="Application status."
    )
```

Behavior: validates index against `state.results`, requires `listing.url`, upserts into pipeline, returns:
- success: `Tracked #{index} — {title} @ {company} — status: {status}`
- no URL: `Result #{index} has no URL; cannot track without one.`
- bad index: `Result #{index} does not exist (have {len}).`

**2. `update_status(identifier, status)`**

```python
class UpdateStatusArgs(BaseModel):
    identifier: str = Field(..., description="Pipeline index (as a string) OR substring of company/title.")
    status: Literal["interested","applied","phone_screen","interviewing","offer","rejected"]
```

Behavior:
- If `identifier` parses as an int between 1 and len(pipeline) -> update that pipeline entry
- Else fuzzy-match against company AND title (case-insensitive substring)
- 0 matches -> `No pipeline entry matches '{identifier}'.`
- 1 match -> update and return `Updated {company} — {title} -> {status}.`
- >=2 matches -> list them as numbered options and return `Multiple matches; reply with the pipeline index.`

**3. `show_pipeline()`**

```python
class ShowPipelineArgs(BaseModel):
    pass
```

Behavior: loads pipeline, renders a Rich grouped table (by status, in the canonical order), prints to console, returns `"{N} tracked job(s)."` or `"No tracked jobs yet."` if empty.

**4. `remove_from_pipeline(identifier)`**

```python
class RemoveFromPipelineArgs(BaseModel):
    identifier: str = Field(..., description="Pipeline index (as a string) OR substring of company/title.")
```

Same matching rules as `update_status`. Returns `Removed {company} — {title} from pipeline.` or the multi-match prompt.

**5. `save_alert(name=None)`**

```python
class SaveAlertArgs(BaseModel):
    name: str | None = Field(None, description="Optional alert name; auto-generated from query if omitted.")
```

Behavior:
- Requires `state.last_query`; otherwise `Run a search first, then I can save it as an alert.`
- If `name` is None, slugify `last_query` (+ "-remote" suffix if location was "remote"); collision -> append `-2`, `-3`, ...
- Captures query, job_type, location, limit, sources from `ChatState.last_*` fields
- `created_at` / `last_run` = now (UTC)
- `seen_urls` initially = URLs of current `state.results` (so the FIRST `run_alerts` shows only listings new since save-time, not the entire result set again)
- Returns: `Saved alert "{name}" (query: "{q}", location: "{loc}", limit: {n}).`

**6. `run_alerts()`**

```python
class RunAlertsArgs(BaseModel):
    pass
```

Behavior: delegates to `tracker.alerts.run_all_alerts(state.console)`. After completion, sets `state.results` = last alert's new listings (if any) and `state.last_query` accordingly, so follow-up tools (`open_job`, `track_job`) just work. Returns `"Ran {N} alerts; {M} new listings across all."`

**7. `list_alerts()`**

```python
class ListAlertsArgs(BaseModel):
    pass
```

Behavior: loads alerts, renders a Rich table (name, query, location, last_run, seen_urls count). Returns `"{N} saved alert(s)."`

**8. `delete_alert(name)`**

```python
class DeleteAlertArgs(BaseModel):
    name: str = Field(..., description="Exact alert name to delete.")
```

Returns `Deleted alert "{name}".` or `No alert named '{name}'.`

**9. `prep_interview(index)`**

```python
class PrepInterviewArgs(BaseModel):
    index: int = Field(..., description="1-based index in current search results.")
```

Behavior: validates index, calls `ai.interview.generate_prep(listing, state.llm)`, prints the result to console, returns `"Generated prep for #{index} — {title} @ {company}."`

### Data flow / lifecycle

- `~/.job-scout/` directory: created lazily inside `pipeline.save_pipeline` and `alerts.save_alerts` via `DATA_DIR.mkdir(parents=True, exist_ok=True)`. Never created by load functions.
- File writes use a temp-file + atomic rename pattern to avoid partial writes corrupting state on crash:
  ```
  tmp = path.with_suffix(".json.tmp")
  tmp.write_text(json.dumps(data, indent=2))
  tmp.replace(path)
  ```
- Load functions return `[]` on `FileNotFoundError` or `json.JSONDecodeError`; the latter also logs a single Rich warning so a corrupted file isn't silently overwritten on the next save (until the user explicitly performs a write op that would replace it — that's acceptable, the warning is the only obligation).

## Implementation Steps

Each step is independently runnable / verifiable.

1. **Create `tracker/` package** with empty `__init__.py`.
2. **Implement `tracker/pipeline.py`** — constants, atomic load/save, `upsert`, `remove_by_url`, `find_matches`, `status_by_url`. Add a `if __name__ == "__main__"` smoke check that round-trips one entry.
3. **Implement `tracker/alerts.py`** — load/save, `upsert_alert`, `delete_alert`, `slugify`, `run_all_alerts` (calls `search.pipeline.run_pipeline`, diffs URLs, renders, mutates, saves).
4. **Extend `output/table.py::render_table`** — add optional `pipeline_status` parameter; if a listing's URL matches, append a dim `[status]` tag to the Title cell via `Text.append`. Existing callers unchanged.
5. **Extend `ChatState`** in `ai/tools.py` — add the 4 new `last_*` fields with defaults; update `summary()`.
6. **Wire `search_jobs` to capture filters** — at the end of `search_jobs`, set `state.last_job_type`, `state.last_location`, `state.last_sources` (always `None` for v1 — chat tool always queries the full registry), `state.last_limit`. Pass `pipeline.status_by_url()` to `render_table`.
7. **Wire `filter_results` and `match_resume`** — both call `render_table` with `pipeline_status` so tags persist across filter/score operations.
8. **Implement `ai/interview.py`** — single `generate_prep` function with the system+human prompts above. Defensive `try/except` around `llm.invoke`.
9. **Add the 9 new tool functions to `build_tools`** in `ai/tools.py` — `track_job`, `update_status`, `show_pipeline`, `remove_from_pipeline`, `save_alert`, `run_alerts`, `list_alerts`, `delete_alert`, `prep_interview`. Each gets a Pydantic args class and a `StructuredTool.from_function` registration.
10. **Update `_HELP_TEXT`** in `ai/agent.py` — add bullets for pipeline, alerts, interview prep capabilities. No new `/commands` are added — everything is natural-language driven.
11. **Add `--alerts` flag** to `main.py::cli` — early-exit branch that bypasses `_maybe_run_setup`'s AI prompts. Validate mutual exclusion with `QUERY`, `--chat`, and any search-modifying flag.
12. **Manual smoke test** — run through each interaction in the wireframe section. Verify `~/.job-scout/pipeline.json` and `~/.job-scout/alerts.json` are created, are valid JSON, and survive a chat-mode restart.
13. **Existing-behavior regression check** — run a plain `python3 main.py "ml engineer"` (no chat, no alerts) and confirm output is identical to pre-change behavior.

## Edge Cases and Error Handling

| Scenario | Handling |
|---|---|
| `track_job` with invalid index | `Result #N does not exist (have M).` |
| `track_job` on listing with no URL | `Result #N has no URL; cannot track without one.` |
| `track_job` re-tracking same URL | `upsert` overwrites status, refreshes `date_tracked`. Return `Updated tracking for {title} -> {status}.` |
| `update_status` / `remove_from_pipeline` with no matches | `No pipeline entry matches '{identifier}'.` |
| `update_status` / `remove_from_pipeline` with >=2 matches | List the matches as numbered options; tell user to reply with the pipeline index. |
| `update_status` with invalid status string | Pydantic `Literal` rejects at tool-call time; LangChain surfaces a tool-error the agent retries. |
| `show_pipeline` when empty | `"No tracked jobs yet. Try: 'track job 1 as applied'"` printed via Rich; tool returns same text. |
| `save_alert` with no prior search | `"Run a search first, then I can save it as an alert."` |
| `save_alert` with duplicate explicit name | Overwrite policy: update query/filters, preserve `seen_urls` and `created_at`. Inform user. |
| `save_alert` with duplicate auto-name | Append `-2`, `-3`, ... until unique. |
| `run_alerts` with no alerts saved | `"No alerts saved. Try: 'save this as my <name> alert'."` |
| `run_alerts` — one alert returns 0 new | Print `"{name}: no new listings since {last_run}."`, no table. |
| `run_alerts` — `seen_urls` exceeds 5000 after merge | FIFO-trim oldest URLs to cap (preserves recency). |
| `delete_alert(name)` not found | `"No alert named '{name}'."` |
| `prep_interview` with bad index | `Result #N does not exist (have M).` |
| `prep_interview` with LLM exception | `"Could not generate prep: {ExceptionType}."` |
| `prep_interview` with sparse metadata | Substitute `"(unspecified)"`; the prompt is instructed to handle this. |
| `~/.job-scout/*.json` malformed | Log a single Rich `[yellow]Warning:[/yellow]`, treat as empty in memory, do NOT delete until a normal write replaces it. |
| `~/.job-scout/` doesn't exist | Created lazily on first save; load functions tolerate absence. |
| Concurrent writes (rare) | Atomic temp-file + rename. Last writer wins (acceptable for single-user CLI). |
| `--alerts` in a non-TTY pipe | Works fine; Rich auto-degrades. Exits 0 even with zero new listings. |
| `--alerts` with no alerts saved | Print `"No alerts saved."` and exit 0. |

## Performance Considerations

- Pipeline / alerts files are small (typical <= a few KB, worst case <= 1 MB at 5000 URLs * 200 chars * N alerts). Whole-file read/write on every op is fine; no caching needed.
- `status_by_url()` builds a dict each call — O(pipeline size), called once per `render_table`. Negligible.
- `run_alerts` runs the existing `run_pipeline` sequentially per alert. With N alerts and ~3s per alert, this is acceptable for chat. Per-source threading already exists inside `run_pipeline`; alert-level parallelism is not needed at v1.
- `prep_interview` adds 1 LLM call (typically 1-2 seconds). Acceptable; runs only on explicit user request.
- No new persistent connections, no new background tasks, no daemon processes.

## Testing Requirements

No test framework in the repo today. Per repo convention, this plan does NOT add pytest as a dep. Verification is via manual smoke tests, which the code-engineer must run before opening the PR:

1. **Pipeline round-trip:** `track_job(1, "applied")` -> restart chat -> `show_pipeline` shows it.
2. **Pipeline tag in results:** Track a listing, search again, confirm `[applied]` tag appears on the matching row.
3. **Pipeline disambiguation:** Track two listings from companies sharing a substring; `update_status("eng", "applied")` returns the multi-match prompt.
4. **Pipeline remove:** Track then remove; `show_pipeline` reflects the removal.
5. **Alert save/run/list/delete:** Save an alert, run it (0 new because just saved), search again with overlapping results, run alerts (only new listings appear).
6. **Alert auto-name collision:** Save two alerts without names from the same query -> second is named `<slug>-2`.
7. **Alert overwrite by name:** Save with same explicit name twice -> second updates the existing, preserves `seen_urls`.
8. **Interview prep:** Search, then `prep me for job 1` -> output has all 4 sections and URL footer.
9. **`--alerts` CLI:** With alerts saved, `python3 main.py --alerts` runs them without prompting for AI keys; without alerts, prints "No alerts saved." and exits 0.
10. **Backward compat:** Run a plain `python3 main.py "ml engineer"`; output table layout, column widths, and existing flags work unchanged.
11. **Malformed JSON resilience:** Manually corrupt `~/.job-scout/pipeline.json`; the next chat session warns but does not crash, and the next `track_job` succeeds and rewrites the file.

## Accessibility and Platform Conventions

- All output is plain text + Rich. No emoji (existing convention).
- Status tags are square-bracketed ASCII so they're screen-reader-friendly and survive `_safe_cell`'s BiDi stripping.
- File paths use `pathlib.Path.home()` so they work on macOS / Linux / Windows.
- Atomic temp-file + rename works on all three platforms (`Path.replace`).
- No new keyboard shortcuts (chat is text-only).
- Rich tables already adapt to terminal width; no changes needed.

## Out of Scope

- **No new pip deps.** No background daemons / cron / launchd — `--alerts` must be run manually or scheduled by the user externally.
- **No notifications** (email, desktop, system tray) on new alert hits.
- **No URL scraping** in `prep_interview`. Metadata only.
- **No multi-user / shared pipeline.** Single-user, local-only.
- **No status history.** `track_job` overwrites the status; we don't keep the prior state.
- **No reminders / SLAs** (e.g. "follow up if no response in 7 days").
- **No analytics dashboard** for pipeline (e.g. funnel conversion rates).
- **No CSV export of the pipeline.** The existing `export_csv` only covers `state.results`; pipeline-export is a future ask.
- **No editing of alert filters after save.** To change an alert, delete and re-save.

## Open Questions

| Question | Recommended Default |
|---|---|
| Should pipeline tags also appear in the non-chat CLI search output? | **No** — pipeline is a chat-mode feature; tagging in batch CLI adds noise. Easy to revisit. |
| Should `track_job` accept a status alias like "applied" vs "Applied"? | Pydantic `Literal` enforces lowercase. The LLM will normalize NL input ("I applied") to the right token. Don't add an alias layer. |
| Should `run_alerts` re-score against the resume? | **No** — alerts are about *new* listings only; scoring adds latency and an AI dependency. User can run "match resume" after if desired. |
| Should `--alerts` accept a name filter (e.g. `--alerts ml-remote`)? | Out of scope for v1. Defer until a user asks. |
| Should `seen_urls` cap be configurable? | Hardcode 5000 for now. If hit in practice we make it an env var. |
| Should `save_alert` warn when `last_query` returned 0 listings? | **Yes** — surface `"Heads up: that search returned 0 listings — alert saved anyway."` so the user can decide. |
| Should pipeline entries store `posted_date` and `salary_range`? | **No** — those are listing-time facts; pipeline tracks *user state*. Keep the schema lean. URL is the join key back to a fresh search if needed. |

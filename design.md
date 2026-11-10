# RecallSearch design

## Goals and boundaries

RecallSearch combines web evidence with persistent, timestamped conversation context. Its only model-callable external tool is `web_search`. Memory is read automatically by application code, not exposed as a tool. OpenAI provides inference; Tavily provides search. There are no embeddings, external memory stores, page-fetch requests, or background model jobs.

The intended environment is one user, one local FastAPI process, and one SQLite database. Multiple conversations are supported; multiple authenticated users are not. Bounded work and inspectable evidence take priority over autonomous research depth.

## Architecture and responsibilities

| Component | Responsibility |
| --- | --- |
| `main.py` | API validation, application lifespan, shared HTTP client, conversation admission, concurrency cap, static files, security headers. |
| `config.py` | Environment and `.env` configuration. |
| `memory.py` | SQLite schema, parameterized writes, UTC timestamps, conversation isolation, bounded lexical retrieval. |
| `providers.py` | Fixed provider endpoints, authentication, timeouts, response validation, search filtering, safe error translation. |
| `agent.py` | Context assembly, exactly one tool definition, bounded orchestration, citation and memory-reference validation, result persistence. |
| `static/` | Same-origin chat UI, responsive layout, safe text rendering, citations, source and remembered-context panels. |
| `tests/` | Temporary databases, deterministic provider responses, HTTP transport substitution, API integration tests. |

The browser calls only the local server. API keys stay server-side. A shared asynchronous HTTPX client reuses connections and closes at shutdown. Provider URLs are fixed to avoid arbitrary network destinations. No agent framework, Node build pipeline, or provider SDK is required.

## Agent decisions and search workflow

1. Validate a conversation UUID and nonblank message of at most 4,000 characters. Return 404 for a missing conversation and 409 for overlapping work.
2. Retrieve memory **before** appending the new query. Persist the user message and server-assigned timestamp before making paid requests.
3. Build a system instruction and JSON data message distinguishing `USER_MEMORY`, `PAST_ASSISTANT`, `WEB_EVIDENCE`, current query, query timestamp, and current UTC time.
4. Supply one strict function definition, `web_search(query)`, with automatic tool choice and parallel calls disabled. The model can answer directly, clarify, or search. Instructions require web evidence for external factual answers unless sufficient recent evidence is supplied.
5. Validate the tool name, count, call ID, JSON arguments, and query length (1–500 characters). Unsupported actions never execute.
6. POST the self-contained query to Tavily `/search`: basic depth, five requested results, no generated answer, no raw page content. Remove results with unsafe URLs, empty snippets, duplicate URLs, or scores below 0.35. Assign turn-local IDs (`S1`, etc.) and retrieval timestamps.
7. If no usable evidence remains, return a rephrasing/failure response without a synthesis call. Otherwise return evidence as a function result and make one final model request **without tools**. This enforces at most one search and two model calls.
8. Parse JSON with `answer` and `memory_ids`. Reject missing/invalid answer text and unknown citation IDs. After search, replace uncited synthesis with an insufficient-evidence response. Persist cited evidence, filtered user-memory references, search query, mode, warnings, and measured latency.
9. Return the persisted assistant message. The UI turns validated `[S1]` markers into source links and renders remembered statements separately.

Direct replies support greetings, user-text transformations, clarification, and questions about prior user statements. This policy is prompt-directed: the server cannot prove that a direct response contains no unsupported external facts. Citation membership checks cannot establish that a snippet entails a claim. These are explicit accuracy limits.

### Evidence reuse

At most five cited sources from retrieved messages are supplied if their age is between zero and 300 seconds. Sources retain original retrieval times, receive new turn-local IDs, and are deduplicated by URL. The model decides whether their relevance and freshness suffice.

A new search replaces reusable evidence. Reuse is labeled `cached_search` in metadata and “reused recent evidence” in the UI. There is no cross-conversation cache. Five-minute freshness is a budget choice, not a guarantee for rapidly changing topics.

## Memory storage and retrieval

SQLite uses WAL mode, foreign keys, a five-second busy timeout, and short per-operation transactions/connections.

### Schema

- `conversations`: UUID primary key, title, creation time, update time. The first user message supplies a title of up to 60 characters.
- `messages`: integer primary key, conversation foreign key with cascading deletion, role, full content, creation time, JSON metadata. An index on `(conversation_id, id)` supports history reads.
- Assistant metadata stores cited evidence: title, URL, snippet, optional publication date, retrieval time, search query, and citation ID. These evidence records are the stored relevant web facts; there is no separately generated fact summary that could introduce additional hallucinations.
- Metadata also stores the user statements the model reports using, their timestamps, reply mode (`memory`, `search`, `cached_search`, `error`), warnings, query, and latency.

All queries are parameterized and reads are scoped to a conversation ID. Deleting a conversation cascades to its messages. Foreign keys prevent appending to nonexistent conversations.

### Retrieval algorithm

Read the latest 500 messages in the selected conversation. Always include the latest six. For older messages, tokenize Unicode letters/numbers, lowercase, drop tokens shorter than three characters and a small English stop-word set, and rank by distinct query-token overlap. Break ties by newest message ID. Select up to four older messages with positive overlap and combine chronologically with recent messages.

At most ten context records enter a prompt, each capped at 1,600 characters. Full contents remain in SQLite. Source snippets are capped at 1,800 characters each; the current query retains its full validated length.

This avoids embedding latency, dependencies, and SQLite FTS extension requirements. It can miss synonyms, indirect relationships, details outside the scan window, or text beyond prompt excerpt limits. English stop-word handling is incomplete. This is bounded relevance-assisted context, not unlimited semantic recall. Prompt limits use characters rather than an exact tokenizer.

### Timestamps

The server uses `datetime.now(timezone.utc)` and ISO 8601 with millisecond precision. User persistence, assistant persistence, and search retrieval each have separate timestamps. Integer message IDs preserve ordering when timestamps coincide. Latency uses `time.monotonic()`.

The model receives exact stored timestamps and current UTC time. The browser formats timestamps in the user's local timezone using `Date.toLocaleString()`. Client-supplied dates are not authoritative. Relative-time interpretation is model-directed; no natural-language date parser is included. A source publication date, if provided by Tavily, is distinct from retrieval time.

## Follow-up resolution

Recent turns give short follow-ups and pronouns a referent; older relevant messages supply constraints such as a project or budget. The model receives this context in its first request and produces a self-contained query without a separate rewrite call.

After “Compare SQLite and PostgreSQL for my Python app,” “What about concurrent writes?” should produce a search naming the databases and concurrency. “What preference did I mention, and when?” should refer to `USER_MEMORY`, its stored timestamp, and its ID without searching. If a referent is absent or ambiguous, instructions require clarification.

Returned memory IDs are intersected with retrieved **user** records only. Assistant-message IDs and other conversations cannot become remembered user context. The UI displays the actual stored statement and timestamp separately from web sources. Pronoun resolution, ambiguity detection, and reported memory usage still depend on the model. Tests establish the supplied context and validation contracts, not universal model behavior.

## Latency and accuracy trade-offs

| Choice | Benefit | Cost |
| --- | --- | --- |
| Combined first-pass decision/answer | No router or query-rewrite model call. | Search decisions depend on the model. |
| One basic search, five results | Bounded latency and spend. | Insufficient depth for some research. |
| No automatic provider retries | Avoids retry cascades and duplicate spend. | Manual retry needed for transient failures. |
| Five-minute evidence reuse | Avoids redundant search on some follow-ups. | Recent evidence may still be stale. |
| Local lexical plus recent retrieval | Fast, inspectable, dependency-free. | Weaker semantic recall than embeddings. |
| No model-generated summaries | No extra inference or memory-summary distortion. | History is not semantically compressed. |
| Buffered JSON output | Simple validation and safe rendering. | No streamed answer text. |

Each model request has a 25-second HTTP timeout; search has 12 seconds; the provider section has a 65-second overall async deadline. Search turns perform two sequential model requests around one search. No latency/accuracy benchmark is claimed; actual elapsed time is included per reply.

Up to four conversations can have active turns concurrently. Overlapping turns in the same conversation are rejected so context ordering is unambiguous. Admission controls are process-local: run one worker. SQLite work is synchronous and short; this is not a high-volume service architecture.

## Error handling and limitations

- Blank/oversized/non-string messages and invalid UUIDs: HTTP 422. Missing conversation: 404. Busy conversation/global cap: 409. Cross-origin writes: 403.
- Missing API keys: actionable configuration response. The original query and failure reply are preserved. Health checks key presence, not validity or provider reachability.
- HTTP errors, timeouts, malformed provider JSON/schema, or incomplete model output: safe provider error text without raw exception bodies or credentials.
- Invalid tool names/counts/IDs/arguments: no tool execution; error response persisted.
- Empty or low-scoring search results: explain that no usable evidence was found and request a more specific question. No hidden extra search or training-knowledge fallback.
- Irrelevant high-scoring, contradictory, or incomplete results: model instructed to abstain/qualify. Uncited search synthesis is replaced with an insufficient-evidence response. Score filtering is a heuristic.
- Unknown source IDs: reject the answer. Unknown memory IDs: discard those references.
- UI network errors: show a visible error and restore the draft. Reload before retrying to check persistence; requests are not idempotent and a disconnected response might already have been saved.
- Abrupt termination can leave an unanswered user message because it is saved before inference. Disk failures and database corruption require operator recovery. Deleting a conversation is blocked while it has an active in-process turn.
- The UI reloads the latest 200 messages and lists the latest 100 conversations. Older records remain in SQLite but there is no pagination interface. Retrieval scans at most 500 messages.

## Security and privacy

- Local single-user scope: UUIDs prevent accidental mixing, **not unauthorized access**. There is no login or ownership check. Bind to `127.0.0.1`. Public hosting requires authentication, authorization, TLS, rate limits, request-size limits, trusted-host checks, and durable concurrency coordination.
- Keys are environment variables, server-side only. Git ignores `.env`, `.venv`, SQLite files, and `data/`. Application code does not log request payloads or keys; ordinary access logs still contain endpoint paths and conversation IDs.
- Memory is plaintext on disk with no retention timer, secure erasure, or encryption. Deletion removes database rows; WAL pages, snapshots, and backups can retain copies. Use OS permissions, disk encryption, and appropriate backups.
- Retrieved context and current queries go to OpenAI with `store=false`; this does not replace provider account-level retention policies. Generated search queries go to Tavily and may reflect private context. The prompt asks the model to avoid unnecessary private details but cannot guarantee sanitization.
- Prior messages and web snippets are untrusted data with explicit prompt-injection resistance instructions. Search-only tooling blocks file/shell actions but cannot eliminate manipulated answers or unwanted disclosure through queries.
- UI rendering uses text nodes, not model-generated HTML or Markdown. Only citations validated against evidence become links. URLs must be HTTP(S), without embedded credentials or control characters. External links use `noopener noreferrer`.
- No third-party font, favicon, script, or tracking requests occur in the UI. A same-origin Content Security Policy prohibits framing; ordinary responses receive `nosniff`, no-referrer, and no-store headers.
- Cross-origin writes carrying an `Origin` header are rejected; CORS is not enabled. These defenses are not authentication or comprehensive localhost/DNS-rebinding protection.

## Tests and verification

Run `python -m pytest -q`. Temporary SQLite files verify persistence and retrieval. HTTPX mock transports inspect actual request payloads and inject timeout/status/schema failures. Agent tests inject deterministic provider outputs to exercise budgets, follow-up prompts, memory references, cache freshness, citations, and saved failures. API tests cover lifespan, validation, deletion, origin handling, and overlapping requests.

These tests verify engineering contracts, not live model quality. Production code has no canned successful replies. Live success requires valid keys and credits. Interactive browser QA and provider-connected evaluation remain separate from the verified suite. Screenshots are intentionally omitted.

## Provider contracts

- [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): function tools, tool choice, JSON-object output, and message format.
- [Tavily Search reference](https://docs.tavily.com/documentation/api-reference/endpoint/search): bearer authentication, basic search, result fields, and limits.

Changing the configurable model requires support for the parameters used here; providers/models are never silently substituted. Direct dependencies are pinned to tested versions; pip resolves transitive dependencies.

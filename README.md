# RecallSearch

**Memory-Augmented Web Search Agent**

A lightweight chat assistant that remembers what you asked and when, resolves follow-up questions, and links answers to web evidence. Exactly one agent-callable tool: `web_search`, powered by Tavily.

## Architecture

```text
Browser (HTML / CSS / JavaScript)
                │ same-origin JSON API
             FastAPI
                ├── SQLite: isolated conversations, timestamps, context, evidence
                └── Agent → OpenAI Chat Completions
                              └── web_search → Tavily Search API
```

Memory retrieval happens automatically in application code. There is no embedding API, page-fetch tool, or framework-managed agent loop. A turn uses one model request without search, or two model requests and at most one search. See [design.md](design.md) for details.

## Features

- Multiple persistent conversations with separate memory and deletion controls.
- Relevant older context plus recent turns, with UTC timestamps displayed in your local time.
- Clickable inline citations and source cards with retrieval times.
- Remembered user statements shown separately from web evidence.
- Recent cited evidence reusable for five minutes within its conversation.
- Input validation, timeouts, enforced search budgets, and saved failure responses.
- Responsive UI, keyboard submission, loading states, and no frontend build step.

## Installation

Requires **Python 3.11+**, OpenAI and Tavily API keys, and sufficient provider credits. Tested locally on Python 3.14.6. CI is configured for Python 3.11–3.13; those remote runs have not been verified.

```bash
git clone https://github.com/YOUR_USERNAME/RecallSearch.git
cd RecallSearch
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows: use `py -m venv .venv`, `.venv\Scripts\activate`, and `copy .env.example .env`.

## Configuration

Edit `.env`:

```dotenv
OPENAI_API_KEY=your-openai-key
TAVILY_API_KEY=your-tavily-key
OPENAI_MODEL=gpt-4.1-mini
DATABASE_PATH=data/recallsearch.sqlite3
```

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Server-side OpenAI authentication. |
| `TAVILY_API_KEY` | Server-side Tavily authentication. |
| `OPENAI_MODEL` | Model supporting Chat Completions, strict function calling, and JSON-object output. Default: `gpt-4.1-mini`. |
| `DATABASE_PATH` | SQLite location, relative to the working directory or absolute. Parent folders are created automatically. |

Environment variables override `.env`. Never commit your keys or database. Without keys, the interface starts and explains the missing configuration; it does not return fake answers. Restart after configuration changes.

## Run

From the repository root:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [RecallSearch](http://127.0.0.1:8000). API reference: [Swagger UI](http://127.0.0.1:8000/docs). Use **one worker** because turn admission control is process-local. This is a local, single-user app without authentication.

Try this sequence:

1. “I’m building a small Python app and prefer simple dependencies.”
2. “How do SQLite and PostgreSQL compare for it?”
3. “What about concurrent writes?”
4. “What preference did I mention, and when?”

**N** starts a new conversation outside the composer. Enter sends; Shift+Enter inserts a newline. Returning to an existing conversation restores its history.

## Test and verify

```bash
python -m pytest -q
python -m compileall -q app
curl http://127.0.0.1:8000/api/health
```

Optional JavaScript syntax check, if Node.js is installed:

```bash
node --check app/static/app.js
```

**Latest local result: 43 tests passed.** Coverage includes persistence, UTC timestamps, retrieval, isolation, follow-up context, search payloads and filtering, evidence reuse, citation validation, malformed model output, missing keys, timeouts, API validation, deletion, same-origin protection, and overlapping turns. Tests use simulated provider responses and make no paid requests. Starlette emits one deprecation warning about its HTTPX-based test client; it does not fail the suite.

Local startup and HTTP endpoints have been verified. Live OpenAI/Tavily success and interactive browser behavior have not been verified in this environment. For a live smoke test, configure both keys, run the example conversation, inspect citations and remembered context, then open a new conversation and ask about the preference.

## Repository

```text
RecallSearch/
├── app/
│   ├── __init__.py
│   ├── agent.py
│   ├── config.py
│   ├── main.py
│   ├── memory.py
│   ├── providers.py
│   └── static/
│       ├── index.html
│       ├── style.css
│       ├── fonts.css
│       ├── app.js
│       └── favicon.svg
├── tests/
│   ├── conftest.py
│   ├── test_agent.py
│   ├── test_api.py
│   ├── test_memory.py
│   └── test_providers.py
├── .github/workflows/tests.yml
├── .env.example
├── .gitignore
├── design.md
├── pytest.ini
├── requirements.txt
└── README.md
```

`data/` is generated at runtime and ignored by Git.

## Limitations

- Search snippets are evidence, not full-page verification. Citation IDs are validated; semantic support and relevance still depend on the model.
- Search decisions, ambiguity resolution, pronoun resolution, and used-memory selection are model-directed. Tests verify orchestration contracts, not universal model quality.
- Lexical retrieval reads the latest 500 messages; prompt excerpts are capped at 1,600 characters each. It can miss synonyms and older details. The UI loads the latest 200 messages and lists the latest 100 conversations; older data remains in SQLite.
- One search may be insufficient for complex research. There are no automatic retries or streamed replies.
- No authentication, encryption at rest, cross-device sync, or public-deployment hardening. Conversation scope is not user authorization.
- Context goes to OpenAI; generated search queries go to Tavily. See [security and privacy](design.md#security-and-privacy).

## Publish to GitHub

Create an empty GitHub repository called `RecallSearch`, then run:

```bash
git init
git add .
git commit -m "Build RecallSearch memory-augmented web search agent"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/RecallSearch.git
git push -u origin main
```

If `origin` already exists, inspect `git remote -v`; use `git remote set-url origin ...` only if you intend to replace it. Check staged files for credentials or private data before committing.

# XYZ handbook assistant

A retrieval-augmented (RAG) chatbot for the XYZ employee handbook. Ask a
question in plain English and get a grounded answer with page citations from
`xyz_company.pdf`.

## What it does

- Extracts and cleans the handbook text, then splits it into overlapping passages.
- Ranks passages with hybrid retrieval: local Sentence Transformers embeddings
  plus a BM25 keyword score.
- Streams answers from an OpenRouter model, constrained to the retrieved passages.
- Shows the source passages and page numbers for every answer.
- Optionally shows Gemma 4's extended reasoning.
- Caches embeddings in `.rag_cache/`, so later starts are instant.
- Falls back to keyword search if the embedding model is unavailable.
- Traces each chat turn, retrieval, and model call to LangSmith when configured.

## Setup

Python 3.10+ is recommended.

```powershell
python -m pip install -r requirements.txt
```

Create a `.env` file in this folder (one is already included):

```dotenv
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=google/gemma-4-26b-a4b-it:free
PDF_PATH=xyz_company.pdf

LANGSMITH_API_KEY=your-langsmith-key
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=xyz-handbook-rag
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

Run the app:

```powershell
python -m streamlit run app.py
```

If `streamlit` is on your PATH, `streamlit run app.py` works too. Open the URL
Streamlit prints (usually <http://localhost:8501>).

## Using the app

1. Pick an answer model in the sidebar. The free Gemma 4 models are a good
   default. If they are rate-limited, the app automatically tries the other
   free Gemma 4 model and then the free Nemotron 3 Ultra model. Paid Gemma 3
   models are never substituted automatically.
2. Ask a question, or choose one of the suggested questions on the empty screen.
3. Expand **Sources** under an answer to inspect the retrieved passages and pages.
4. Use **Rebuild index** after replacing the PDF, and **Clear chat** to start over.

## LangSmith tracing

Tracing is optional and on by default when `LANGSMITH_API_KEY` is set. Each
question produces a `handbook_chat` chain with two child spans:

- `handbook_retrieval` — the search query, top-k setting, and the passages found.
- `openrouter_chat` — the model, prompt messages, streamed answer, reasoning,
  and any free-model fallback notice.

The root span records the question, the model that actually answered, the final
answer, the cited pages, and any error. Open the **xyz-handbook-rag** project in
[LangSmith](https://smith.langchain.com) to inspect runs. The sidebar shows
whether tracing is active. If the key is missing or tracing is disabled, the app
runs normally and simply skips the traces.

Only standard `LANGSMITH_*` variables are required; the loader also accepts the
legacy `Langsmith=...` key for convenience. Never commit `.env`.

## How it works

```text
xyz_company.pdf
      │  pypdf
      ▼
clean text ──► sentence-aware chunks (1,100 chars, 180 overlap)
      │
      ├──► all-MiniLM-L6-v2 embeddings ──► cosine similarity ─┐
      │                                                       ├─► top-k passages
      └──► BM25 keyword scores ───────────────────────────────┘
                                                              │
                                          system prompt + passages + chat history
                                                              │
                                                    OpenRouter (Gemma)
                                                              │
                                                 streamed answer + citations
```

The first run downloads the `all-MiniLM-L6-v2` model (about 90 MB) and builds
the embedding cache. That only happens once per PDF version.

## Project files

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit chat interface and prompt assembly |
| `rag_engine.py` | PDF parsing, chunking, embeddings, hybrid search, cache |
| `openrouter.py` | Streaming OpenRouter client with free-model fallback |
| `tracing.py` | Loads `.env`, configures LangSmith, and provides no-op fallbacks |
| `.env` | API keys and model settings (ignored by git) |
| `.streamlit/config.toml` | App theme |
| `requirements.txt` | Python dependencies |

## Notes

- **Keep the API keys secret.** `.env` is listed in `.gitignore`. If a key is
  ever committed or shared, revoke it in the OpenRouter or LangSmith dashboard
  and create a new one.
- Free models share an upstream rate limit, so a 429 response is normal at busy
  times. Retry or switch models from the sidebar. Free Gemma 4 requests fall
  back to the other free Gemma 4 model and then to Nemotron 3 Ultra.
- File watching is disabled in `.streamlit/config.toml` to avoid noisy import
  warnings from the local embedding stack. Restart Streamlit after editing
  code, or add `--server.fileWatcherType=auto` when running it.
- The assistant only answers from the handbook. If a passage is missing, it
  will say so rather than invent a policy.

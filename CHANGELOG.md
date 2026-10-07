# Changelog

## 0.1.0 — 2026-10-08

First working Fixfinder MVP.

- Collect 100 closed Streamlit bug reports with explicit references in merged fix PRs, quality filtering, deduplication, and provenance.
- Generate local MiniLM description embeddings and store them with issue metadata in SQLite.
- Rank historical bugs using semantic and keyword similarity, with an optional component filter.
- Provide a dark Streamlit interface with example prompts, evidence excerpts, comparison tabs, source links, persistent results, and JSON export.
- Document external Wispr Flow dictation as the voice-to-text workflow; no embedded speech integration is included.
- Document setup for other users and a future RAG generation extension.
- Include six tests for data quality, ranking, stale indexes, evidence extraction, paraphrased queries, component filters, and interface interactions.

Known limits: a single-repository 100-case sample; heuristic ranking and relevance thresholds; no generated diagnosis, automated patching, or released-version verification. End-to-end Wispr Flow microphone dictation has not been tested by the application test suite.

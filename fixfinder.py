"""Local semantic embeddings and a small SQLite vector store (exact cosine search)."""
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
import sqlite3

import numpy as np

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "issues.json"
DATABASE = ROOT / "data" / "vectors.sqlite3"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_PATH = ROOT / "data" / "models" / "all-MiniLM-L6-v2"
INDEX_VERSION = "description-token-chunks-v1"


def load_issues(path=DATASET):
    issues = json.loads(Path(path).read_text(encoding="utf-8"))
    if not issues or len({x["id"] for x in issues}) != len(issues):
        raise ValueError("Dataset must contain unique issue IDs.")
    return issues


def signature(path=DATASET):
    return hashlib.sha256(Path(path).read_bytes() + MODEL_NAME.encode() + INDEX_VERSION.encode()).hexdigest()


def load_model():
    # This application uses PyTorch only; unrelated system TensorFlow installs
    # must not activate Transformers' optional Keras integration.
    os.environ["USE_TF"] = "0"
    from sentence_transformers import SentenceTransformer
    if MODEL_PATH.exists():
        return SentenceTransformer(str(MODEL_PATH))
    model = SentenceTransformer(MODEL_NAME)
    model.save(str(MODEL_PATH))
    return model


def embed(model, texts):
    # Encode every description, including long reports, without silent truncation.
    chunks, spans = [], []
    size = model.max_seq_length - 16
    for text in texts:
        tokens = model.tokenizer.encode(text, add_special_tokens=False, verbose=False)
        start = len(chunks)
        for offset in range(0, max(1, len(tokens)), size):
            chunks.append(model.tokenizer.decode(tokens[offset:offset + size], skip_special_tokens=True))
        spans.append((start, len(chunks)))
    encoded = model.encode(chunks, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    vectors = np.array([encoded[a:b].mean(axis=0) for a, b in spans], dtype=np.float32)
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)


def index_is_current(dataset=DATASET, database=DATABASE):
    if not Path(database).exists():
        return False
    try:
        with sqlite3.connect(database) as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()
            count = connection.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        return row is not None and row[0] == signature(dataset) and count == len(load_issues(dataset))
    except sqlite3.DatabaseError:
        return False


def build_index(model=None, dataset=DATASET, database=DATABASE):
    issues = load_issues(dataset)
    model = model or load_model()
    vectors = embed(model, [issue["description"] for issue in issues])
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    # Transactional replacement preserves the previous index on write failure.
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, payload TEXT NOT NULL, embedding BLOB NOT NULL)")
        connection.execute("DELETE FROM issues")
        connection.executemany("INSERT INTO issues VALUES (?, ?, ?)", [(issue["id"], json.dumps(issue), vector.astype('<f4').tobytes()) for issue, vector in zip(issues, vectors)])
        connection.execute("INSERT OR REPLACE INTO metadata VALUES ('signature', ?)", (signature(dataset),))
        connection.execute("INSERT OR REPLACE INTO metadata VALUES ('model', ?)", (MODEL_NAME,))
    return len(issues)


STOP_WORDS = set("a an the and or but to of in on at for from with by as is are was were be been being it its this that these those i we you my our your they them can cannot could should would will do does did not when then than if so just using use used have has had after before also any all into get gets got bug issue streamlit expected actual behavior behaviour steps reproduce version python operating system additional information none description summary please app code import return true false report click happens happen what how same only instead there here more which while through about value values".split())


def terms(text):
    return [word for word in re.findall(r"[a-z][a-z0-9_]+(?:\.[a-z][a-z0-9_]+)*", text.lower()) if word not in STOP_WORDS and len(word) > 2]


def evidence(query, issue):
    """Extract traceable overlap, not a generated diagnosis or model attribution."""
    query_terms = set(terms(query))
    title = issue.get("title", "")
    description = issue["description"]
    shared = query_terms & set(terms(title + " " + description))
    title_terms = set(terms(title))
    shared = sorted(shared, key=lambda term: (term not in title_terms, -len(term), term))[:8]
    candidates = [re.sub(r"^[#*\-\s]+", "", line).strip() for line in description.splitlines() if len(line.strip()) > 35 and not line.lstrip().startswith(("http", "![", "```"))]
    excerpt = max(candidates, key=lambda line: len(query_terms & set(terms(line))), default=description[:320])
    if len(excerpt) > 360:
        matches = [match.start() for match in re.finditer(r"\S+", excerpt) if set(terms(match.group())) & query_terms]
        start = max(0, (matches[0] if matches else 0) - 80)
        excerpt = ("…" if start else "") + excerpt[start:start + 360] + "…"
    return {"shared_terms": shared, "excerpt": excerpt,
        "query_only_terms": sorted(query_terms - set(terms(title + " " + description)))[:6]}


def lexical_scores(query, issues):
    """TF-IDF cosine signal emphasizes distinctive symptoms and widget names."""
    documents = [terms((issue.get("title", "") + " ") * 2 + issue["description"]) for issue in issues]
    frequencies = Counter(term for doc in documents for term in set(doc))
    weights = {term: np.log((1 + len(issues)) / (1 + count)) + 1 for term, count in frequencies.items()}
    query_counts = Counter(terms(query))
    q = {term: (1 + np.log(count)) * weights[term] for term, count in query_counts.items() if term in weights}
    qnorm = np.sqrt(sum(value * value for value in q.values()))
    scores = []
    for doc in documents:
        vector = {term: (1 + np.log(count)) * weights[term] for term, count in Counter(doc).items()}
        norm = np.sqrt(sum(value * value for value in vector.values()))
        scores.append(sum(value * vector.get(term, 0) for term, value in q.items()) / max(qnorm * norm, 1e-12))
    return np.array(scores)


def search(query, model, k=3, dataset=DATASET, database=DATABASE, component=None):
    if len(query.strip()) < 10:
        raise ValueError("Please describe the bug in at least 10 characters.")
    if not index_is_current(dataset, database):
        raise ValueError("The index is missing or outdated. Rebuild it before searching.")
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT payload, embedding FROM issues ORDER BY id").fetchall()
    matrix = np.stack([np.frombuffer(row[1], dtype='<f4') for row in rows])
    issues = [json.loads(row[0]) for row in rows]
    scores = np.clip(matrix @ embed(model, [query])[0], -1, 1)
    keywords = lexical_scores(query, issues)
    ranking = 0.85 * scores + 0.15 * keywords
    positions = [i for i in np.argsort(-ranking, kind="stable") if not component or component in issues[i].get("labels", [])][:max(0, k)]
    return [{"issue": issues[i], "score": float(scores[i]), "rank_score": float(ranking[i]),
        "keyword_score": float(keywords[i]), "evidence": evidence(query, issues[i])} for i in positions]


if __name__ == "__main__":
    print(f"Indexed {build_index()} issues in {DATABASE}")

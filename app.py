"""Fixfinder — a local, evidence-first workspace for Streamlit bug triage."""
from html import escape
import json
from pathlib import Path

import streamlit as st

from fixfinder import build_index, index_is_current, load_issues, load_model, search

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Fixfinder · Find the fix", page_icon="🔎", layout="wide", initial_sidebar_state="collapsed")
st.markdown(f"<style>{(ROOT / 'assets' / 'style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

GITHUB = '<svg viewBox="0 0 24 24" width="19" height="19" fill="currentColor" aria-hidden="true"><path d="M12 .7a11.5 11.5 0 0 0-3.64 22.41c.57.1.78-.25.78-.55v-2.14c-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.76 2.7 1.25 3.36.95.1-.74.4-1.25.73-1.54-2.55-.3-5.23-1.28-5.23-5.69 0-1.26.45-2.29 1.18-3.1-.12-.3-.51-1.47.11-3.06 0 0 .96-.31 3.16 1.18a10.96 10.96 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.62 1.59.23 2.76.11 3.05.74.82 1.18 1.85 1.18 3.11 0 4.42-2.69 5.38-5.25 5.67.41.36.78 1.06.78 2.14v3.16c0 .3.2.66.79.55A11.5 11.5 0 0 0 12 .7Z"/></svg>'
st.markdown(f'''<nav class="topbar"><a class="wordmark" href="/" aria-label="Fixfinder home">Fix<span>finder</span><i>⌁</i></a><div class="nav-right"><span class="local-pill"><b></b> LOCAL WORKSPACE</span><a class="repo-link" href="https://github.com/streamlit/streamlit" target="_blank" rel="noopener noreferrer">{GITHUB} streamlit / streamlit ↗</a></div></nav>''', unsafe_allow_html=True)


@st.cache_resource
def get_model():
    return load_model()


def choose_example(text):
    st.session_state.bug_query = text


def clear_search():
    st.session_state.bug_query = ""
    st.session_state.pop("search_result", None)


try:
    issues = load_issues()
except (OSError, ValueError) as exc:
    st.error(f"Cannot load the historical cases: {exc}")
    st.stop()

st.markdown(f'''<section class="hero"><div class="eyebrow">LESS GUESSWORK. MORE FIXING.</div><h1>New bug?<br>Start with a <span class="accent">known fix.</span></h1><p>Search real Streamlit bug reports. Compare the evidence.<br>Go straight to the pull request that resolved it.</p><div class="hero-facts"><span><strong>{len(issues)}</strong> historical bugs</span><span><strong>100%</strong> linked to merged PRs</span><span class="private-note">Your query stays on this machine</span></div><div class="hero-art" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><span>⌁</span><i>+</i></div></section>''', unsafe_allow_html=True)

left, right = st.columns([0.9, 1.45], gap="large")
with left:
    st.markdown('<div class="section-label">01 / DESCRIBE THE BUG</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.subheader("What’s breaking?")
        st.caption("Include the widget, the unexpected behavior, and what triggers it.")
        with st.form("bug_search", border=False):
            query = st.text_area("Bug description", key="bug_query", height=140, placeholder="e.g. In st.data_editor, entering .5 drops the decimal point and saves 5 instead…", label_visibility="collapsed")
            components = sorted({label for issue in issues for label in issue['labels'] if label.startswith('feature:')})
            component = st.selectbox("Narrow to a component", ["All Streamlit components"] + components, format_func=lambda value: value.removeprefix("feature:"))
            submitted = st.form_submit_button("Find similar bugs", type="primary", use_container_width=True)
        st.caption("Searches 100 closed Streamlit bugs, not all of GitHub.")
    st.markdown('<div class="small-label">TRY A REAL-WORLD SYMPTOM</div>', unsafe_allow_html=True)
    for label, sample in [
        ("↳  Decimal input loses its point", "In st.data_editor, typing a number starting with a decimal point like .5 drops the decimal point and reads it as 5."),
        ("↳  Dialog disappears after a rerun", "A dialog created inside a fragment stops working after the parent fragment reruns, even though the dialog is still visible."),
        ("↳  Tooltip appears far from the cursor", "After upgrading Streamlit, pydeck tooltips appear far above the hovered element instead of next to the cursor.")]:
        st.button(label, on_click=choose_example, args=(sample,), use_container_width=True)
    st.button("Clear search", on_click=clear_search, type="tertiary")
    with st.expander("How matching works"):
        st.write("Results combine semantic similarity (85%) with distinctive shared words and component names (15%). The displayed cosine score measures similarity in meaning, not the probability of a duplicate.")
        st.write("‘Why this surfaced’ shows literal text evidence. It does not explain the model’s internal reasoning. Compare the reproduction steps and version before applying a fix.")
        st.caption("MiniLM · local SQLite vector store · no query leaves this app")
    with st.expander("Dataset & maintenance"):
        st.write("Every case is a closed, bug-labeled report with an explicit closing reference in a merged pull request. Resolution summaries come from PR titles.")
        st.download_button("Download 100 bug cases", json.dumps(issues, ensure_ascii=False, indent=2), "issues.json", "application/json", use_container_width=True)
        if st.button("Rebuild local index", use_container_width=True):
            try:
                with st.spinner("Rebuilding local embeddings…"):
                    build_index(get_model())
                st.session_state.pop("search_result", None)
                st.success("Index rebuilt. Ready to search.")
            except Exception as exc:
                st.error(f"Could not rebuild the index: {exc}")

if submitted:
    if len(query.strip()) < 10:
        st.session_state.pop("search_result", None)
        with left:
            st.warning("Add a little more detail — at least 10 characters — so we can compare the symptom.")
    else:
        try:
            with right, st.spinner("Comparing your bug with historical reports…"):
                model = get_model()
                if not index_is_current():
                    build_index(model)
                results = search(query, model, component=None if component == "All Streamlit components" else component)
                st.session_state.search_result = {"query": query, "component": component, "results": results}
        except Exception as exc:
            st.session_state.pop("search_result", None)
            with right:
                st.error(f"Search could not finish: {exc}")
                st.info("Initial setup needs internet to download the model. Retry with `python fixfinder.py` if setup is incomplete.")


def render_result(rank, result):
    issue, ev = result['issue'], result['evidence']
    pr = issue['related_pr']
    with st.container(border=True):
        tag = 'CLOSEST RESULT' if rank == 1 else 'RELATED REPORT'
        st.markdown(f'<div class="result-meta"><span class="rank-badge">0{rank}</span><span>{tag}</span><span class="merged-pill">✓ PR MERGED</span></div>', unsafe_allow_html=True)
        title_col, score_col = st.columns([4.3, 1])
        with title_col:
            st.markdown(f'<h3 class="result-title">{escape(issue["title"])}</h3>', unsafe_allow_html=True)
            st.caption(f"#{issue['number']} · " + ' · '.join(label.removeprefix('feature:') for label in issue['labels'] if label.startswith('feature:')))
        with score_col:
            st.metric("Cosine similarity", f"{result['score']:.3f}")
        st.markdown('<div class="small-label">WHY THIS SURFACED</div>', unsafe_allow_html=True)
        if ev['shared_terms']:
            st.markdown('<div class="chips">' + ''.join(f'<span>{escape(term)}</span>' for term in ev['shared_terms']) + '</div>', unsafe_allow_html=True)
            st.caption("Shared terms in your query and this report")
        else:
            st.caption("Semantic similarity only — no distinctive literal terms overlap.")
        st.markdown(f'<div class="evidence-quote">“{escape(ev["excerpt"])}”</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="fix-block"><span>↳ PREVIOUS FIX</span><p>{escape(pr["title"])}</p></div>', unsafe_allow_html=True)
        links = st.columns(2)
        links[0].link_button(f"GitHub issue #{issue['number']} ↗", issue['issue_url'], use_container_width=True)
        links[1].link_button(f"Merged PR #{pr['number']} ↗", pr['url'], use_container_width=True)
        with st.expander("Compare report & inspect the fix"):
            report_tab, fix_tab, compare_tab = st.tabs(["Original report", "Fix details", "Compare with your bug"])
            with report_tab:
                st.text(issue['description'])
            with fix_tab:
                st.write(issue['resolution'])
                st.caption(f"Merged {pr['merged_at'][:10]} · Commit {pr['merge_commit_sha'][:10]}")
                st.text(pr['description'])
            with compare_tab:
                st.markdown("**Your submitted bug**")
                st.write(st.session_state.search_result['query'])
                st.markdown("**What still needs checking**")
                st.write("Compare the affected Streamlit version, reproduction steps, and expected behavior. A merged PR alone does not identify which release contains the fix.")
                if ev['query_only_terms']:
                    st.write("Query terms not found literally in this report: " + ', '.join(ev['query_only_terms']) + ". These may be synonyms or differences; they are not proof of a mismatch.")
                st.caption(f"Ranking score {result['rank_score']:.3f} = 85% semantic ({result['score']:.3f}) + 15% keyword ({result['keyword_score']:.3f}). Text overlap is supporting evidence, not a diagnosis.")


with right:
    saved = st.session_state.get('search_result')
    st.markdown('<div class="section-label">02 / FOLLOW THE EVIDENCE</div>', unsafe_allow_html=True)
    if saved:
        st.subheader(f"{len(saved['results'])} reports to investigate")
        st.caption('Results for: ' + saved['query'][:170] + ('…' if len(saved['query']) > 170 else ''))
        if query != saved['query'] or component != saved['component']:
            st.info("Your draft has changed. Search again to update these results.")
        if not saved['results']:
            st.info("No historical cases match this component. Try all Streamlit components.")
        elif max(result['score'] for result in saved['results']) < 0.35:
            st.warning("Weak similarity. These are the nearest reports, but this dataset may not contain your bug.")
        else:
            st.caption("Ranked candidates, not confirmed duplicates. Open the evidence before applying a fix.")
        for rank, result in enumerate(saved['results'], 1):
            render_result(rank, result)
        st.download_button("↓ Export these results", json.dumps(saved, ensure_ascii=False, indent=2), 'fixfinder-results.json', 'application/json')
    else:
        st.markdown('''<div class="empty-state"><div class="search-orbit">⌕</div><div class="eyebrow">THE FIX MAY ALREADY EXIST</div><h2>Connect the symptom<br>to the solution.</h2><p>Describe your bug on the left. Your closest<br>historical reports will appear here.</p><div class="empty-steps"><div><b>01</b><span>Match the symptom<small>Meaning + distinctive terms</small></span></div><div><b>02</b><span>Compare the evidence<small>Real excerpts from the original report</small></span></div><div><b>03</b><span>Inspect the merged fix<small>Direct links to the issue and pull request</small></span></div></div></div>''', unsafe_allow_html=True)

st.markdown('<footer>FIXFINDER <span>Built for developers who would rather fix it once.</span><span>LOCAL SEARCH · PUBLIC EVIDENCE</span></footer>', unsafe_allow_html=True)

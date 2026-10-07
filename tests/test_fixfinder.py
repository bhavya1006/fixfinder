import json
import re

import numpy as np
import pytest

import fixfinder as ff


def test_dataset_quality_and_provenance():
    issues = ff.load_issues()
    assert 90 <= len(issues) <= 110
    assert len({x['issue_url'] for x in issues}) == len(issues)
    assert len({re.sub(r'\s+', ' ', x['description'].lower()) for x in issues}) == len(issues)
    for issue in issues:
        assert issue['state'] == 'closed'
        assert 'type:bug' in issue['labels']
        assert len(issue['description'].split()) >= 55
        assert issue['related_pr']['merged_at']
        assert issue['related_pr']['merge_commit_sha']
        assert str(issue['number']) in issue['related_pr']['description']
        assert issue['resolution_source'] == 'merged_pull_request_title'


def test_search_ranking_and_stale_index(tmp_path, monkeypatch):
    dataset = tmp_path / 'issues.json'
    database = tmp_path / 'vectors.sqlite3'
    dataset.write_text(json.dumps([{'id': str(i), 'description': str(i)} for i in range(4)]))
    vectors = np.array([[1, 0], [0.8, 0.6], [0, 1], [-1, 0]], dtype=np.float32)
    monkeypatch.setattr(ff, 'embed', lambda model, texts: vectors if len(texts) == 4 else vectors[:1])
    ff.build_index(object(), dataset, database)
    result = ff.search('sufficiently long query', object(), dataset=dataset, database=database)
    assert [r['issue']['id'] for r in result] == ['0', '1', '2']
    assert result[0]['score'] == pytest.approx(1)
    with pytest.raises(ValueError, match='10 characters'):
        ff.search(' ', object(), dataset=dataset, database=database)
    dataset.write_text(dataset.read_text() + '\n')
    assert not ff.index_is_current(dataset, database)
    with pytest.raises(ValueError, match='outdated'):
        ff.search('sufficiently long query', object(), dataset=dataset, database=database)


def test_real_index_self_retrieval():
    assert ff.index_is_current(), 'Run python fixfinder.py before integration tests'
    model = ff.load_model()
    for issue in ff.load_issues()[::20]:
        result = ff.search(issue['description'], model)
        assert result[0]['issue']['id'] == issue['id']
        assert result[0]['score'] > 0.99


def test_evidence_is_traceable_and_handles_no_overlap():
    issue = {'title': 'Decimal point lost', 'description': 'Typing a leading decimal point drops the decimal and saves an integer.'}
    result = ff.evidence('The decimal point disappears', issue)
    assert 'decimal' in result['shared_terms']
    assert result['excerpt'] in issue['description']
    assert 'disappears' in result['query_only_terms']
    assert not ff.evidence('zebra migration failure', issue)['shared_terms']


def test_paraphrases_and_component_filter():
    model = ff.load_model()
    samples = [
        ('The data editor drops the decimal point when I type a number starting with a dot.', 16909),
        ('A dialog created inside a fragment stops working after the parent fragment reruns, even though the dialog is still visible.', 17011),
        ('After upgrading Streamlit, pydeck tooltips appear far above the hovered element instead of next to the cursor.', 17309),
    ]
    for query, expected in samples:
        results = ff.search(query, model)
        assert results[0]['issue']['number'] == expected
        assert results[0]['evidence']['shared_terms']
    results = ff.search(samples[0][0], model, component='feature:st.data_editor')
    assert results
    assert all('feature:st.data_editor' in result['issue']['labels'] for result in results)
    assert ff.search(samples[0][0], model, component='feature:does_not_exist') == []


def test_streamlit_search():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ff.ROOT / 'app.py'), default_timeout=120).run()
    assert not app.exception
    assert not app.error
    app.text_area[0].set_value('The data editor drops the decimal point when I type a number starting with a dot.')
    next(button for button in app.button if button.label == 'Find similar bugs').click().run()
    assert not app.exception
    assert not app.error
    assert len([metric for metric in app.metric if metric.label == 'Cosine similarity']) == 3
    assert app.session_state['search_result']['results'][0]['issue']['number'] == 16909
    # Filling an example preserves the old result and labels it as an older query.
    next(button for button in app.button if 'Tooltip appears' in button.label).click().run()
    assert 'pydeck' in app.text_area[0].value
    assert len(app.metric) == 3
    assert any('draft has changed' in info.value for info in app.info)
    next(button for button in app.button if button.label == 'Clear search').click().run()
    assert not app.text_area[0].value
    assert not app.metric
    next(button for button in app.button if button.label == 'Find similar bugs').click().run()
    assert app.warning
    assert not app.exception

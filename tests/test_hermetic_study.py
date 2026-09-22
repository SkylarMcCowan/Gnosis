"""Correspondence invariants and actual study interactions, without a live LLM."""
from datetime import datetime, timedelta, timezone
import json
import os

import pytest

from hermetic_study.model import Catalog
from hermetic_study.study import Progress, question_bank


def test_complete_mapping_and_decans():
    c = Catalog()
    assert len(c.cards) == 62
    assert len({p['letter'] for p in c.paths.values()}) == 22
    assert len({tuple(sorted(p['endpoints'])) for p in c.paths.values()}) == 22
    for number in range(1, 11):
        assert len([m for m in c.minors.values() if m['sephirah'] == number]) == 4
    decans = {(m['zodiac'], m['decan']) for m in c.minors.values() if m['number'] > 1}
    assert len(decans) == 36
    for m in c.minors.values():
        if m['number'] == 1:
            assert m['decan'] is None
            assert 'no individual decan' in c.render('card', m['id']).lower()


def test_gd_thoth_distinctions_and_derivation():
    c = Catalog()
    assert c.paths[15]['letter'] == 'Heh'
    assert c.paths[15]['endpoints'] == [2, 6]
    assert c.majors['major-15']['thoth_letter'] == 'Tzaddi'
    assert c.paths[28]['letter'] == 'Tzaddi'
    assert c.majors['major-28']['thoth_letter'] == 'Heh'
    assert c.paths[19]['astrology'] == 'Leo'
    assert c.majors['major-19']['thoth_number'] == 'XI'
    five = c.minors['minor-wands-5']
    seven = c.minors['minor-wands-7']
    assert (five['planet'], five['zodiac'], five['thoth_title']) == ('Saturn', 'Leo', 'Strife')
    assert (seven['planet'], seven['zodiac'], seven['thoth_title']) == ('Mars', 'Leo', 'Valour')
    text = str(c.derivation(five['id']))
    assert all(x in text for x in ('Geburah', 'Fire', 'Saturn', 'Strife'))
    assert 'study:path/15' in c.render('card', 'major-15')
    assert 'study:sephirah/5' in c.render('card', five['id'])
    assert 'Source / history' not in c.render('card', five['id'], depth=0)


def test_quiz_answers_and_unique_ids():
    bank = question_bank(Catalog())
    assert len({q.id for q in bank}) == len(bank)
    assert {q.category for q in bank} == {'Correspondences', 'Paths', 'Elements', 'Tree', 'Derivation'}
    for q in bank:
        assert q.choices.count(q.answer) == 1
        assert len(set(q.choices)) == len(q.choices)
        assert len(q.choices) >= 3


def test_progress_roundtrip_review_and_mistakes(tmp_path):
    p = Progress(tmp_path/'progress.json')
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bank = question_bank(Catalog())[:2]
    p.record(bank[0].id, False, now)
    p.record(bank[0].id, False, now)
    assert p.choose(bank, now+timedelta(minutes=11)).id == bank[0].id
    assert p.records[bank[0].id]['mistakes'] == 2
    for i in range(3):
        p.record(bank[1].id, True, now)
    reloaded = Progress(p.path)
    assert reloaded.summary() == (5, 3, 1)
    assert reloaded.records[bank[1].id]['due'] == (now+timedelta(days=4)).isoformat()
    p.record(bank[1].id, False, now)
    assert p.records[bank[1].id]['streak'] == 0


def test_corrupt_progress_preserved(tmp_path):
    path = tmp_path/'progress.json'
    path.write_text('{broken')
    with pytest.raises(ValueError):
        Progress(path)
    assert path.read_text() == '{broken'


def test_failed_write_preserves_existing_state(tmp_path, monkeypatch):
    p = Progress(tmp_path/'progress.json')
    p.record('test', True)
    original = p.path.read_bytes()
    def fail(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        p.record('test', False)
    assert p.path.read_bytes() == original
    assert p.summary() == (1, 1, 0)
    assert list(tmp_path.iterdir()) == [p.path]


@pytest.fixture
def panel(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PyQt6')
    from PyQt6.QtWidgets import QApplication
    from hermetic_study.widget import HermeticStudyWidget
    app = QApplication.instance() or QApplication([])
    widget = HermeticStudyWidget(progress_path=tmp_path/'progress.json')
    widget.resize(1200, 850)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_navigation_tree_and_links(panel):
    from PyQt6.QtCore import QUrl
    assert panel.pages.count() == panel.navigation.count() == 12
    for i in range(12):
        panel.navigation.setCurrentRow(i)
        assert panel.pages.currentIndex() == i
    panel.select_tree('path', '15')
    assert panel.tree_selector.currentIndex() >= 0
    assert tuple(panel.tree_selector.currentData()) == ('path', '15')
    assert 'The Emperor' in panel.tree_detail.toPlainText()
    assert panel.tree.paths[15].pen().width() == 7
    for n in [2, 6]:
        assert panel.tree.nodes[n].brush().color().name() == '#605132'
    panel.polarity.setChecked(True)
    assert all(item.isVisible() for item in panel.tree.pillars)
    panel.follow_link(QUrl('study:card/minor-wands-5'))
    assert panel.current_topic == ('card', 'minor-wands-5')
    assert 'Geburah' in panel.detail.toPlainText()
    panel.follow_link(QUrl('study:tree/s5'))
    assert panel.tree_topic == ('sephirah', '5')
    panel.tree_selector.setCurrentIndex(0)
    assert panel.tree_topic == ('sephirah', '1')


def test_actual_graph_mouse_selection(panel):
    from PyQt6.QtCore import Qt, QPointF
    from PyQt6.QtTest import QTest
    panel.go('Tree of Life')
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
    point = panel.tree.mapFromScene(QPointF(480, 335))
    QTest.mouseClick(panel.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert panel.tree_topic == ('sephirah', '4')
    # Midpoint of path 16 is clear of nodes and crossings.
    point = panel.tree.mapFromScene(QPointF(480, 260))
    QTest.mouseClick(panel.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert panel.tree_topic == ('path', '16')


def test_search_and_progressive_disclosure(panel):
    panel.search.setText('Valour')
    assert panel.card_list.count() == 1
    assert '7 of Wands' in panel.detail.toPlainText()
    panel.search.setText('not a card')
    assert panel.card_list.count() == 0
    assert 'No matching' in panel.detail.toPlainText()
    panel.search.clear()
    panel.select_tree('sephirah', '5')
    panel.basic.setChecked(False)
    panel.depth.setCurrentIndex(0)
    text = panel.tree_detail.toPlainText()
    assert 'Basic explanation' not in text
    assert 'Divine name:' not in text
    panel.depth.setCurrentIndex(2)
    assert 'Divine name:' in panel.tree_detail.toPlainText()


def test_quiz_requires_answer_and_counts_once(panel):
    panel.check_answer()
    assert panel.progress.summary() == (0, 0, 0)
    panel.answers.setCurrentIndex(panel.answers.findData(panel.question.answer))
    panel.check_answer()
    panel.check_answer()
    assert panel.progress.summary() == (1, 1, 0)
    assert panel.review_button.isEnabled()
    assert 'Next review:' in panel.feedback.toPlainText()
    panel.next_question()
    assert panel.check_button.isEnabled()
    assert not panel.review_button.isEnabled()
    assert Progress(panel.progress.path).summary() == (1, 1, 0)


def test_every_reference_renders_at_each_depth():
    c = Catalog()
    topics = [('card', k) for k in c.cards] + [('sephirah', k) for k in c.sephiroth] + [('path', k) for k in c.paths] + [('suit', k) for k in c.suits] + [('source', k) for k in c.sources]
    for kind, key in topics:
        for depth in range(3):
            assert '<h2>' in c.render(kind, key, basic=False, depth=depth)


def test_quiz_save_error_is_visible(panel, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('read-only directory')
    monkeypatch.setattr(panel.progress, 'record', fail)
    panel.answers.setCurrentIndex(panel.answers.findData(panel.question.answer))
    panel.check_answer()
    assert 'Could not save this attempt' in panel.feedback.toPlainText()
    assert panel.progress.summary() == (0, 0, 0)

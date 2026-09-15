"""A long text kept as a book, one chapter at a time into the ordinary flow."""
from runtime.books import split_chapters, CHAPTER_LIMIT
from tests.test_workflow import client, create  # noqa: F401


def test_chapters_are_found_by_their_headings_and_reassemble_exactly():
    book = '序言\n开头的一段。\n\n第一章 到镇上去\n' + '林小雪走在路上。' * 30 + '\n\n第二回 雨\n雨点敲着窗。\n第三卷 尾声\n结束了。\n'
    chapters = split_chapters(book)
    assert [c['title'] for c in chapters] == ['（开头）', '第一章 到镇上去', '第二回 雨', '第三卷 尾声']
    assert ''.join(c['text'] for c in chapters) == book
    assert chapters[1]['text'].startswith('第一章 到镇上去\n')


def test_a_headingless_text_is_cut_at_paragraphs_never_inside_a_sentence():
    text = '雨点敲着窗。她抬头看了看。\n\n' * 400
    chapters = split_chapters(text)
    assert len(chapters) > 1 and all(len(c['text']) <= CHAPTER_LIMIT for c in chapters)
    assert all(c['text'].endswith('\n\n') for c in chapters)          # cut at paragraph breaks
    assert ''.join(c['text'] for c in chapters) == text


def test_a_single_overlong_paragraph_is_cut_after_sentence_ends():
    text = '第一章 很长\n' + '这是一个非常长的段落，没有空行。' * 400 + '\n'
    chapters = split_chapters(text)
    assert all(len(c['text']) <= CHAPTER_LIMIT for c in chapters)
    assert all(c['text'].rstrip('\n').endswith('。') for c in chapters)
    assert [c['title'] for c in chapters][:2] == ['第一章 很长 · 1', '第一章 很长 · 2']
    assert ''.join(c['text'] for c in chapters) == text


def test_a_short_text_is_one_chapter_and_short_flow_is_unchanged():
    assert split_chapters('小雪看着窗外。') == [{'title': '', 'text': '小雪看着窗外。'}]


def test_a_book_hands_out_chapters_with_names_from_its_other_chapters(client):
    book = client.post('/api/books', json={'title': '孔乙己', 'language': 'zh',
                                           'script': '第一章 酒店\n' + '鲁镇的酒店。' * 300 + '\n第二章 伙计\n我从十二岁起。\n'}).json()
    assert [c['title'] for c in book['chapters']] == ['第一章 酒店', '第二章 伙计']
    assert 'text' not in book['chapters'][0]                           # listing carries no bodies
    assert client.get('/api/books').json()[0]['chapters'] == 2
    # A project made from chapter one contributes its names to chapter two.
    create(client, 'zh', script='掌柜：还欠十九个钱呢。\n孔乙己：下回还清罢。')
    p = client.get('/api/projects').json()[0]
    client.patch('/api/projects/' + p['id'], json={'revision': 0, 'name': '孔乙己 · 第一章 酒店'})
    second = client.get(f"/api/books/{book['id']}/chapters/2").json()
    assert second['project_name'] == '孔乙己 · 第二章 伙计'
    assert second['text'].startswith('第二章 伙计')
    assert set(second['known_names']) == {'掌柜', '孔乙己'}
    assert client.get(f"/api/books/{book['id']}/chapters/9").status_code == 400
    assert client.get('/api/books/' + 'f' * 32).status_code == 400
    # Forgetting the book leaves the project made from it untouched.
    assert client.delete('/api/books/' + book['id']).status_code == 200
    assert client.get('/api/books').json() == []
    assert client.delete('/api/books/' + book['id']).status_code == 400
    assert client.get('/api/projects').json()[0]['name'] == '孔乙己 · 第一章 酒店'


def test_english_chapter_headings_are_found_too():
    book = 'CHAPTER I\n\nIt is a truth universally acknowledged.\n\nChapter Two\n\n"My dear Mr. Bennet," said his lady.\n\nChapter 3\n\nThe end.\n'
    chapters = split_chapters(book)
    assert [c['title'] for c in chapters] == ['CHAPTER I', 'Chapter Two', 'Chapter 3']
    assert ''.join(c['text'] for c in chapters) == book
    # A sentence that merely contains the word is not a heading.
    assert len(split_chapters('He read the chapter twice.\n')) == 1


def test_a_dialogue_heavy_chapter_is_cut_so_the_draft_can_take_each_piece():
    from runtime.books import UNIT_LIMIT
    from evals.speaker_attribution.source_units import source_units
    # 2,400 characters, but 200 quoted units: under the character cap, far over the unit cap.
    line = '宝玉道：“你来了。”黛玉笑道：“来了。”\n'
    text = '第三回 相见\n' + line * 100
    chapters = split_chapters(text)
    assert len(chapters) > 1
    assert all(len(source_units(c['text'])) <= UNIT_LIMIT for c in chapters)
    assert all(c['text'].endswith('\n') for c in chapters)                     # cut at paragraph ends
    assert [c['title'] for c in chapters][:2] == ['第三回 相见 · 1', '第三回 相见 · 2']
    assert ''.join(c['text'] for c in chapters) == text


def test_a_single_paragraph_of_dialogue_is_never_cut_inside_a_quotation():
    from runtime.books import UNIT_LIMIT
    from evals.speaker_attribution.source_units import source_units
    text = '宝玉道：“你来了。我等了很久。”黛玉笑道：“来了。”' * 120 + '\n'    # no paragraph breaks at all
    chapters = split_chapters(text)
    assert len(chapters) > 1
    for c in chapters:
        assert len(source_units(c['text'])) <= UNIT_LIMIT
        assert c['text'].count('“') == c['text'].count('”')                    # every quotation closed
        assert c['text'].rstrip('\n').endswith(('。', '”'))
    assert ''.join(c['text'] for c in chapters) == text


def test_single_newline_paragraphs_are_paragraphs_but_hard_wrapped_lines_are_not():
    # Web-novel style: one newline between paragraphs. Cut at those, not mid-sentence.
    text = ('雨点敲着窗。她抬头看了看，' * 6 + '然后继续写。\n') * 120
    chapters = split_chapters(text)
    assert all(len(c['text']) <= CHAPTER_LIMIT and c['text'].endswith('。\n') for c in chapters)
    assert ''.join(c['text'] for c in chapters) == text
    # Hard-wrapped: a line break mid-sentence is not a paragraph end, so no piece ends there.
    wrapped = ('雨点敲着窗，她抬头看了看\n然后继续写。\n') * 150
    chapters = split_chapters(wrapped)
    assert all(c['text'].endswith('。\n') for c in chapters)
    assert ''.join(c['text'] for c in chapters) == wrapped


def test_a_chapter_project_remembers_its_book_and_inherits_the_previous_chapter(tmp_path):
    """Configure a book once: the next chapter's project starts with the same
    voices for the characters it shares, the same lexicon, model, pause and speed."""
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.engines import FixtureEngine
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from tests.test_attribution_import import Roles, HEADERS
    with TestClient(create_app(tmp_path/'projects', FixtureEngine(), role_engine=Roles()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        text = '第一章 酒店\n掌柜看着他。“还欠十九个钱呢。”掌柜说。\n\n第二章 伙计\n“又来了？”掌柜说。“下回还清罢。”孔乙己说。\n'
        book = c.post('/api/books', json={'title': '孔乙己', 'language': 'zh', 'script': text}).json()
        def make(index, speakers):
            ch = c.get(f"/api/books/{book['id']}/chapters/{index}").json()
            d = c.post('/api/attribution/draft', json={'script': ch['text'], 'language': 'zh'}).json()
            labels = [{k: u[k] for k in ('id', 'kind', 'speaker')} for u in d['units']]
            for label in labels:
                if label['speaker'] == 'UNKNOWN': label['speaker'] = speakers.pop(0)
            r = c.post('/api/attribution/confirm', json={'draft_id': d['draft_id'], 'name': ch['project_name'], 'labels': labels,
                                                        'book_id': book['id'], 'chapter_index': index})
            assert r.status_code == 200, r.text
            return r.json()
        first = make(1, ['掌柜'])
        assert first['book'] == {'id': book['id'], 'title': '孔乙己', 'index': 1, 'chapters': 2} and first['inherited'] is None
        url = '/api/projects/' + first['id']
        first = c.patch(url, json={'revision': first['revision'], 'speaker': '掌柜', 'voice': 'Uncle_Fu'}).json()
        first = c.patch(url, json={'revision': first['revision'], 'lexicon': {'偸': '偷'}, 'pause_ms': 500}).json()
        # The chapter listing knows a project exists for chapter one now.
        assert c.get(f"/api/books/{book['id']}/chapters/1").json()['existing_project_id'] == first['id']
        second = make(2, ['掌柜', '孔乙己'])
        assert second['book']['index'] == 2
        assert second['inherited']['from'] == first['name']
        assert second['voices']['掌柜'] == 'Uncle_Fu' and set(second['inherited']['voices']) == {'旁白', '掌柜'}   # 孔乙己 is new here
        assert second['lexicon'] == {'偸': '偷'} and second['pause_ms'] == 500
        assert set(second['inherited']['settings']) >= {'lexicon', 'pause_ms'}
        # A project can also take another's settings on request, and undo it.
        third = c.post('/api/projects', json={'name': '别的', 'language': 'zh', 'script': '掌柜：好。\n孔乙己：好。'}).json()
        r = c.post(f"/api/projects/{third['id']}/inherit", json={'revision': third['revision'], 'source_id': first['id']})
        assert r.status_code == 200, r.text
        assert r.json()['voices']['掌柜'] == 'Uncle_Fu' and r.json()['inherited']['from'] == first['name']
        undone = c.post(f"/api/projects/{third['id']}/undo", json={'revision': r.json()['revision']}).json()
        assert undone['voices']['掌柜'] == third['voices']['掌柜']
        assert c.post(f"/api/projects/{third['id']}/inherit", json={'revision': undone['revision'], 'source_id': third['id']}).status_code == 400


def test_a_project_made_before_the_link_existed_is_linked_by_its_name(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.engines import FixtureEngine
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from tests.test_attribution_import import Roles, HEADERS
    with TestClient(create_app(tmp_path/'projects', FixtureEngine(), role_engine=Roles()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        book = c.post('/api/books', json={'title': '孔乙己', 'language': 'zh', 'script': '第一章 酒店\n掌柜看着他。\n\n第二章 伙计\n他走了。\n'}).json()
        old = c.post('/api/projects', json={'name': '孔乙己 · 第一章 酒店', 'language': 'zh', 'script': '旁白：掌柜看着他。'}).json()
        assert 'book' not in old or old.get('book') is None
        ch = c.get(f"/api/books/{book['id']}/chapters/1").json()
        assert ch['existing_project_id'] == old['id']
        assert c.get('/api/projects/' + old['id']).json()['book'] == {'id': book['id'], 'title': '孔乙己', 'index': 1, 'chapters': 2}
        assert c.get('/api/projects/' + old['id']).json()['revision'] == old['revision']


def test_a_template_keeps_a_configuration_and_applies_it_to_another_project(client):
    from tests.test_workflow import create
    first = create(client, 'zh', script='掌柜：好。\n孔乙己：好。')
    url = '/api/projects/' + first['id']
    first = client.patch(url, json={'revision': first['revision'], 'speaker': '掌柜', 'voice': 'Uncle_Fu'}).json()
    first = client.patch(url, json={'revision': first['revision'], 'speaker': '掌柜', 'color': '#000080'}).json()
    first = client.patch(url, json={'revision': first['revision'], 'lexicon': {'偸': '偷'}, 'pause_ms': 500, 'color_scope': 'both'}).json()
    t = client.post('/api/templates', json={'name': '鲁镇标准', 'project_id': first['id']}).json()
    assert t['voices']['掌柜'] == 'Uncle_Fu' and t['colors'] == {'掌柜': '#000080'} and t['lexicon'] == {'偸': '偷'}
    assert 'voice_profiles' not in t                                          # references stay with their project
    assert [x['name'] for x in client.get('/api/templates').json()] == ['鲁镇标准']
    other = create(client, 'zh', script='掌柜：来了。\n酒客：来了。')
    r = client.post(f"/api/projects/{other['id']}/inherit", json={'revision': other['revision'], 'template_id': t['id']})
    assert r.status_code == 200, r.text
    applied = r.json()
    assert applied['voices']['掌柜'] == 'Uncle_Fu' and applied['colors'] == {'掌柜': '#000080'} and applied['color_scope'] == 'both'
    assert applied['lexicon'] == {'偸': '偷'} and applied['pause_ms'] == 500 and applied['inherited']['from'] == '鲁镇标准'
    assert client.post(f"/api/projects/{other['id']}/inherit", json={'revision': applied['revision']}).status_code == 400
    assert client.delete('/api/templates/' + t['id']).status_code == 200
    assert client.get('/api/templates').json() == []


def test_a_chapter_still_drafts_after_its_book_was_deleted(tmp_path):
    """The chapter page keeps the book id it was opened with; the book may be
    gone by the time the draft is asked for (2026-09-16)."""
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from tests.test_attribution_import import Roles, HEADERS
    from evals.speaker_attribution.source_units import source_units
    from runtime.engines import FixtureEngine
    class Plain(Roles):
        def annotate(self, text, log_path):
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': '阿宁' if u['text'].startswith('“') else 'NARRATOR', 'certain': True} for u in source_units(text)],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Plain()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        book = c.post('/api/books', json={'title': '书', 'language': 'zh', 'script': '第一章 一\n阿宁说：“来。”\n\n第二章 二\n阿宁又说：“来呀。”\n'}).json()
        ch = c.get(f"/api/books/{book['id']}/chapters/2").json()
        assert c.delete('/api/books/' + book['id']).status_code == 200
        d = c.post('/api/attribution/draft', json={'script': ch['text'], 'language': 'zh', 'book_id': book['id']})
        assert d.status_code == 200, d.text
        assert [u['speaker'] for u in d.json()['units'] if u['kind'] == 'dialogue'] == ['阿宁']


def test_a_character_has_a_sex_apart_from_the_voice_and_it_is_inherited(client):
    """Astra 2026-09-15: the voice chosen must not decide whose line it is. The
    sex the speaker rules go by is set on the character; the voice only suggests."""
    p = create(client, 'zh', '旁白：一。\n阿宁：二。\n')
    r = client.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'speaker': '阿宁', 'sex': 'f'})
    assert r.status_code == 200 and r.json()['sexes'] == {'阿宁': 'f'}
    p = r.json()
    q = create(client, 'zh', '旁白：三。\n阿宁：四。\n')
    q = client.post(f"/api/projects/{q['id']}/inherit", json={'revision': q['revision'], 'source_id': p['id']}).json()
    assert q['sexes'] == {'阿宁': 'f'}
    p = client.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'speaker': '阿宁', 'sex': 'auto'}).json()
    assert p['sexes'] == {}

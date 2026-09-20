"""Engineering checks for the foundation; not product acceptance or model evals."""
from copy import deepcopy
import pytest

from runtime.book_master import plan_book, plan_chapter, new_book, structure_conflicts
from runtime.project_settings import (application_defaults, effective, initialize,
                                     reference_requirements, VIEW_KEY)
from runtime.core import Store, fingerprint, spoken_text
from runtime.engines import FixtureEngine
from runtime.capacity import role_batch_limits, estimate_role_batch
from runtime.attribution import ROLE_MODELS


def test_unprocessed_chapters_keep_full_source_and_order_without_fake_segments():
    chapters = [{'title': '第一章', 'text': '第一章\n' + '雨落在屋檐。' * 2300},
                {'title': '第二章', 'text': '第二章\n“回来吧。”\n', 'cut': 'lines',
                 'hints': [{'start': 4, 'end': 10, 'speaker': '阿宁', 'colour': '#112233'}], 'silent': [0]}]
    before = deepcopy(chapters)
    plan = plan_book('雨', 'zh', chapters, defaults=application_defaults(clone_model='1.7B'))
    book, projects = plan['book'], plan['projects']
    assert chapters == before
    assert len(projects) == 2 and book['members'] == [p['id'] for p in projects]
    assert ''.join(p['source_script'] for p in projects) == ''.join(c['text'] for c in chapters)
    assert all(p['segments'] == [] and p['processing_state'] == 'unprocessed' for p in projects)
    assert all('clone_model' not in p and 'pause_ms' not in p for p in projects)
    assert effective(projects[0], book)['clone_model'] == '1.7B'
    assert projects[1]['hints'] == before[1]['hints'] and projects[1]['silent'] == [0]
    assert all('text' not in c for c in book['chapters'])


def test_parent_changes_reach_inheriting_child_but_keep_explicit_zero_and_empty():
    book = new_book('雨', 'zh', defaults={'pause_ms': 350, 'lexicon': {'行': '航'},
                                         'voices': {'阿宁': 'Vivian', '王伯': 'Uncle_Fu'}})
    child = plan_chapter('一', '“行。”', 'zh', book=book)['project']
    overridden = deepcopy(child)
    overridden.update(pause_ms=0, lexicon={}, voices={'阿宁': 'Serena'})
    book['settings'].update(pause_ms=800, lexicon={'行': '型'})
    book['revision'] += 1
    inherited = effective(child, book)
    local = effective(overridden, book)
    assert inherited['pause_ms'] == 800 and inherited['lexicon'] == {'行': '型'}
    assert local['pause_ms'] == 0 and local['lexicon'] == {}
    assert local['voices'] == {'阿宁': 'Serena', '王伯': 'Uncle_Fu'}
    assert local[VIEW_KEY]['sources']['voices']['roles']['王伯']['level'] == 'book'
    assert local[VIEW_KEY]['sources']['voices']['roles']['阿宁']['level'] == 'project'
    local['voices']['王伯'] = 'Dylan'
    assert book['settings']['voices']['王伯'] == 'Uncle_Fu'
    del overridden['pause_ms']
    assert effective(overridden, book)['pause_ms'] == 800


def test_empty_role_map_and_empty_mute_list_are_explicit():
    book = new_book('雨', 'zh', defaults={'colors': {'阿宁': '#112233'}, 'muted_speakers': ['阿宁']})
    child = plan_chapter('一', '原文', 'zh', book=book)['project']
    child.update(colors={}, muted_speakers=[])
    view = effective(child, book)
    assert view['colors'] == {} and view['muted_speakers'] == []
    assert child['colors'] == {} and book['settings']['colors'] == {'阿宁': '#112233'}


def test_legacy_project_keeps_its_audio_identity_despite_new_defaults(tmp_path):
    store = Store(tmp_path)
    old = store.create('旧稿', '阿宁：等等……\n', 'zh')
    old.pop('clone_model', None); old.pop('ellipsis_pause_ms', None)
    old['book'] = {'id': 'a' * 32}
    original = deepcopy(old)
    book = {'id': 'a' * 32, 'revision': 9, 'settings': {'ellipsis_pause_ms': 700, 'preset_model': '1.7B'}}
    engine = FixtureEngine(); seg = old['segments'][0]
    view = effective(old, book, defaults=application_defaults(clone_model='1.7B'))
    assert view['ellipsis_pause_ms'] == 0 and view['clone_model'] == '0.6B'
    assert fingerprint(old, seg, engine) == fingerprint(view, seg, engine)
    assert old == original


def test_effective_view_passes_existing_consumers_and_cannot_be_written(tmp_path):
    store = Store(tmp_path)
    raw = store.create('试读', '阿宁：行。\n', 'zh')
    book = new_book('书', 'zh', defaults={'voices': {'阿宁': 'Vivian'}, 'lexicon': {'行': '航'}})
    child = initialize(raw, book=book)
    store.write(child)
    disk_before = (store.directory(child['id'])/'project.json').read_bytes()
    reread = store.read(child['id'])
    assert 'speech_rate' not in reread and 'voice_profiles' not in reread
    view = effective(reread, book)
    assert spoken_text(view, view['segments'][0]) == '航。'
    first = fingerprint(view, view['segments'][0], FixtureEngine())
    book['settings']['lexicon'] = {'行': '型'}
    later = effective(reread, book)
    assert fingerprint(later, later['segments'][0], FixtureEngine()) != first
    # One operation retains its original resolved snapshot, even if parent changes.
    assert spoken_text(view, view['segments'][0]) == '航。'
    with pytest.raises(ValueError, match='不能写回'):
        store.write(dict(view))
    assert (store.directory(child['id'])/'project.json').read_bytes() == disk_before


def test_standalone_freezes_machine_defaults_and_sibling_copy_is_independent():
    defaults = application_defaults(preset_model='1.7B', clone_model='1.7B')
    original = plan_chapter('独立', '原文', 'zh', defaults=defaults)['project']
    assert original['preset_model'] == original['clone_model'] == '1.7B'
    source = effective(original, defaults=application_defaults())
    book = new_book('别的书', 'zh', defaults={'pause_ms': 900})
    copied = plan_chapter('复制设置', '另一段原文', 'zh', book=book, copy_from=source)
    assert copied['project']['pause_ms'] == 250
    book['settings']['pause_ms'] = 1400
    assert effective(copied['project'], book)['pause_ms'] == 250
    assert copied['project']['segments'] == [] and copied['project']['source_script'] == '另一段原文'


def test_copy_plan_keeps_fixed_voice_owner_instead_of_guessing_asset_path():
    book = new_book('雨', 'zh', defaults={'voice_profiles': {'阿宁': {'sha256': 'c' * 64, 'text': '参考'}}})
    child = plan_chapter('一', '原文', 'zh', book=book)['project']
    source = effective(child, book)
    requirements = reference_requirements(source)
    copied = plan_chapter('二', '新文', 'zh', book=book, copy_from=source)
    assert requirements == copied['reference_copies']
    assert requirements[0]['owner'] == {'level': 'book', 'id': book['id']}
    assert copied['project']['voice_profiles']['阿宁']['sha256'] == 'c' * 64
    requirements[0]['profile']['text'] = '改动'
    assert source['voice_profiles']['阿宁']['text'] == '参考'
    with pytest.raises(ValueError, match='解析来源'):
        plan_chapter('三', '原文', 'zh', copy_from=child)


def test_named_character_rename_does_not_change_fingerprint_if_settings_move(tmp_path):
    raw = Store(tmp_path).create('名字', '阿宁：回来吧。\n', 'zh')
    view = effective(raw)
    seg = view['segments'][0]
    original = fingerprint(view, seg, FixtureEngine())
    view['voices']['小宁'] = view['voices'].pop('阿宁')
    seg['speaker'] = '小宁'
    assert fingerprint(view, seg, FixtureEngine()) == original


@pytest.mark.parametrize('bad_book', [None, {'id': 'b' * 32, 'settings': {}}])
def test_new_inherited_child_fails_explicitly_when_parent_missing_or_wrong(bad_book):
    child = plan_chapter('一', '原文', 'zh', book={'id': 'a' * 32, 'title': '书', 'language': 'zh'})['project']
    with pytest.raises(ValueError, match='主工程'):
        effective(child, bad_book)


def test_structure_conflicts_include_author_marks_and_are_nonmutating():
    left = {'language': 'zh', 'cut': None, 'hints': [], 'silent': []}
    right = {'language': 'zh', 'cut': 'lines', 'hints': [{'start': 0, 'end': 2}], 'silent': [0]}
    conflicts = structure_conflicts(left, right)
    assert set(conflicts) == {'cut', 'hints', 'silent'}
    conflicts['hints']['right'][0]['start'] = 1
    assert right['hints'][0]['start'] == 0


@pytest.mark.parametrize('kwargs', [{'silent': [5]}, {'hints': [{'start': 0, 'end': 99}]}, {'cut': 'unknown'}])
def test_bad_author_ranges_are_not_silently_carried(kwargs):
    with pytest.raises(ValueError):
        plan_chapter('一', '正文', 'zh', **kwargs)


def test_model_specific_cap_and_memory_limits_both_bind(monkeypatch):
    monkeypatch.delenv('VOXSTAGE_DRAFT_CHARS', raising=False)
    model = ROLE_MODELS['qwen3-30b-a3b-instruct-2507-q4km']
    small = role_batch_limits(model, 16)
    large = role_batch_limits(model, 32)
    assert small['units'] == large['units'] == 100
    assert small['context'] == 16384 and large['context'] == 20480
    assert small['chars'] == 3000 and large['chars'] == 6000
    assert role_batch_limits(ROLE_MODELS['qwen3-14b-q4km'], 32)['units'] == 280
    rejected = estimate_role_batch(1000, 151, large)
    assert not rejected['fits'] and 'unit_limit' in rejected['reasons']
    assert estimate_role_batch(1000, 80, large)['fits']
    assert not estimate_role_batch(3100, 80, small)['fits']
    assert estimate_role_batch(3100, 80, large)['fits']


def test_token_cap_still_binds_when_characters_and_unit_counts_fit():
    limits = role_batch_limits({'max_tokens': 200}, 16)
    result = estimate_role_batch(100, 20, limits)
    assert not result['fits'] and result['reasons'] == ['token_budget']


def test_master_book_api_keeps_author_chapters_and_exposes_effective_settings(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app

    headers = {'x-voxstage': '1'}
    body = '第一章 风起\n' + '风吹过窗。' * 900 + '\n第二章 雨\n雨落下来。\n'
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine()),
                    base_url='http://127.0.0.1', headers=headers) as client:
        response = client.post('/api/master-books', json={
            'title': '长篇', 'language': 'zh', 'script': body,
        })
        assert response.status_code == 200, response.text
        book = response.json()
        assert [chapter['title'] for chapter in book['chapters']] == ['第一章 风起', '第二章 雨']
        assert len(book['projects']) == 2
        first_id = book['projects'][0]['id']
        project = client.get('/api/projects/' + first_id).json()
        state = project['settings_state']
        assert project['processing_state'] == 'unprocessed'
        assert state['overrides'] == {}
        assert state['effective']['pause_ms'] == 250
        assert state['sources']['pause_ms'] == {'level': 'book', 'id': book['id']}

        changed = client.patch('/api/master-books/' + book['id'] + '/settings', json={
            'revision': book['revision'], 'values': {'pause_ms': 600},
        })
        assert changed.status_code == 200, changed.text
        inherited = client.get('/api/projects/' + first_id + '/settings').json()
        assert inherited['effective']['pause_ms'] == 600
        assert inherited['overrides'] == {}

        local = client.patch('/api/projects/' + first_id + '/settings', json={
            'revision': inherited['project_revision'], 'values': {'pause_ms': 0},
        })
        assert local.status_code == 200, local.text
        assert local.json()['effective']['pause_ms'] == 0
        assert local.json()['sources']['pause_ms'] == {'level': 'project', 'id': first_id}
        restored = client.patch('/api/projects/' + first_id + '/settings', json={
            'revision': local.json()['project_revision'], 'inherit': ['pause_ms'],
        })
        assert restored.status_code == 200, restored.text
        assert restored.json()['effective']['pause_ms'] == 600


def test_new_standalone_freezes_defaults_and_old_project_stays_legacy(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app

    headers = {'x-voxstage': '1'}
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine()),
                    base_url='http://127.0.0.1', headers=headers) as client:
        standalone = client.post('/api/project-records', json={
            'name': '独立原稿', 'language': 'zh', 'script': '尚未处理的原文。',
        })
        assert standalone.status_code == 200, standalone.text
        state = standalone.json()['settings_state']
        assert state['settings_schema'] == 1
        assert set(state['overrides']) == set(state['effective'])
        assert all(source['level'] == 'project' for source in state['sources'].values())

        legacy = client.post('/api/projects', json={
            'name': '旧入口', 'language': 'zh', 'script': '旁白：照旧工作。',
        })
        assert legacy.status_code == 200, legacy.text
        assert 'settings_state' not in legacy.json()


def test_adding_chapter_can_copy_sibling_settings_without_copying_text(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app

    headers = {'x-voxstage': '1'}
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine()),
                    base_url='http://127.0.0.1', headers=headers) as client:
        book = client.post('/api/master-books', json={
            'title': '书', 'language': 'zh', 'script': '第一章\n原文。',
        }).json()
        source_id = book['projects'][0]['id']
        state = client.get('/api/projects/' + source_id + '/settings').json()
        client.patch('/api/projects/' + source_id + '/settings', json={
            'revision': state['project_revision'], 'values': {'speech_rate': 1.2},
        })
        response = client.post(f"/api/master-books/{book['id']}/chapters", json={
            'revision': book['revision'], 'title': '第二章', 'text': '另一段原文。',
            'copy_settings_from': source_id,
        })
        assert response.status_code == 200, response.text
        copied = response.json()['project']
        assert copied['source_script'] == '另一段原文。'
        assert copied['settings_state']['effective']['speech_rate'] == 1.2
        assert copied['settings_state']['sources']['speech_rate']['level'] == 'project'


def test_copying_sibling_settings_copies_and_verifies_fixed_voice_asset(tmp_path):
    import hashlib
    from runtime.books import Books
    from runtime.project_service import ProjectService

    store = Store(tmp_path / 'projects')
    books = Books(tmp_path / 'books')
    service = ProjectService(store, books, application_defaults)
    book, projects = service.create_book('书', 'zh', [{'title': '一', 'text': '原文。'}])
    source = store.read(projects[0]['id'])
    audio = b'fixed voice fixture'
    digest = hashlib.sha256(audio).hexdigest()
    source['voice_profiles'] = {'阿宁': {'sha256': digest, 'text': '参考文字'}}
    store.write(source)
    folder = store.directory(source['id']) / 'references'
    folder.mkdir()
    (folder / (digest + '.wav')).write_bytes(audio)

    updated, copied = service.create_chapter(
        book['id'], book['revision'], '二', '另一段。', copy_from_id=source['id'])
    assert (store.directory(copied['id']) / 'references' / (digest + '.wav')).read_bytes() == audio
    assert copied['voice_profiles']['阿宁']['sha256'] == digest
    assert store.read(source['id'])['book']['chapters'] == 2

    (folder / (digest + '.wav')).unlink()
    before = books.get(book['id'])
    with pytest.raises(ValueError, match='缺失或校验失败'):
        service.create_chapter(book['id'], updated['revision'], '三', '第三段。',
                               copy_from_id=source['id'])
    assert books.get(book['id']) == before
    assert len(list(store.root.glob('*/project.json'))) == 2

"""Project packages (本人 2026-09-25: 打包一个主工程或子工程的全部内容；删掉工程后
导入这个包，可以恢复). A package brings back the lines, the takes, the library
voices, a whole book with its chapters; a chapter whose book no longer lists
it comes back on its own with its settings; nothing is ever overwritten; a
supplied recording needs its consent confirmed again. Claude Hera."""
import io
import json
import zipfile

import numpy as np
from fastapi.testclient import TestClient

from runtime.app import create_app
from tests.test_voice_library import LongFixtureEngine
from tests.test_workflow import create, generate, HEADERS


def client_for(tmp_path):
    return TestClient(create_app(tmp_path / 'projects', LongFixtureEngine()), base_url='http://127.0.0.1:8765', headers=HEADERS)


def fetch(c, made):
    r = c.get(made['url'])
    assert r.status_code == 200 and r.content[:2] == b'PK'
    return r.content


def bring_back(c, data, **query):
    return c.post('/api/packages/import', content=data, params=query, headers={'content-type': 'application/octet-stream'})


def remove_project(c, p):
    p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'archived': True}).json()
    assert c.delete(f"/api/projects/{p['id']}?revision={p['revision']}").status_code == 200


def test_a_deleted_project_comes_back_with_its_takes_and_its_library_voice(tmp_path):
    with client_for(tmp_path) as c:
        p = create(c, 'zh')
        voice = c.post('/api/voices/custom', json={'name': '王伯', 'language': 'zh', 'reference_text': '雨点敲着窗。', 'from_voice': 'Vivian'}).json()
        speaker = p['segments'][0]['speaker']
        p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'speaker': speaker, 'voice': 'custom:' + voice['id']}).json()
        p = generate(c, p)
        assert all(s['status'] == 'ready' for s in p['segments'])
        made = c.post(f"/api/projects/{p['id']}/package").json()
        assert made['projects'] == 1 and made['voices'] == 1 and made['provided_recordings'] == []
        assert made['local'] is False                                            # a browser elsewhere downloads it
        data = fetch(c, made)
        remove_project(c, p)
        assert c.delete(f"/api/voices/custom/{voice['id']}").status_code == 200
        back = bring_back(c, data)
        assert back.status_code == 200, back.text
        assert back.json()['projects'] == [p['id']] and back.json()['voices_added'] == 1
        again = c.get('/api/projects/' + p['id']).json()
        assert not again['archived'] and again['voices'][speaker] == 'custom:' + voice['id']
        assert [s['text'] for s in again['segments']] == [s['text'] for s in p['segments']]
        assert all(s['status'] == 'ready' for s in again['segments'])      # the takes came back, nothing to regenerate
        assert any(v['id'] == voice['id'] for v in c.get('/api/voices/custom').json())


def test_a_project_still_here_is_never_overwritten_and_can_come_back_as_a_copy(tmp_path):
    with client_for(tmp_path) as c:
        p = generate(c, create(c, 'zh'))
        data = fetch(c, c.post(f"/api/projects/{p['id']}/package").json())
        before = (tmp_path / 'projects' / p['id'] / 'project.json').read_bytes()
        refused = bring_back(c, data)
        assert refused.status_code == 409 and refused.json()['detail']['conflict'] == ['Test']
        assert (tmp_path / 'projects' / p['id'] / 'project.json').read_bytes() == before
        copy = bring_back(c, data, copy='true').json()
        new = copy['projects'][0]
        assert new != p['id'] and copy['copy'] and copy['title'] == 'Test（副本）'
        twin = c.get('/api/projects/' + new).json()
        assert twin['name'] == 'Test（副本）' and all(s['status'] == 'ready' for s in twin['segments'])


def test_a_whole_book_comes_back_with_every_chapter(tmp_path):
    with client_for(tmp_path) as c:
        book = c.post('/api/master-books', json={'title': '雨夜', 'language': 'zh', 'script': '第一章\n陈小雪：走吧。\n第二章\n阿宁：好。\n'}).json()
        members = [x['id'] for x in book['projects']]
        made = c.post(f"/api/master-books/{book['id']}/package").json()
        assert made['projects'] == 2
        data = fetch(c, made)
        assert c.delete(f"/api/master-books/{book['id']}?with_chapters=true").status_code == 200
        assert c.get('/api/books/' + book['id']).status_code >= 400
        back = bring_back(c, data).json()
        assert back['kind'] == 'book' and back['book_id'] == book['id'] and back['projects'] == members
        restored = c.get('/api/books/' + book['id']).json()
        assert restored['title'] == '雨夜' and restored['members'] == members
        assert all(c.get('/api/projects/' + m).json()['book']['id'] == book['id'] for m in members)


def test_a_chapter_whose_book_let_it_go_comes_back_on_its_own_with_its_settings(tmp_path):
    with client_for(tmp_path) as c:
        book = c.post('/api/master-books', json={'title': '雨夜', 'language': 'zh', 'script': '第一章\n陈小雪：走吧。\n第二章\n阿宁：好。\n'}).json()
        chapter = book['projects'][0]['id']
        revision = c.get('/api/books/' + book['id']).json()['revision']
        c.post(f"/api/master-books/{book['id']}/settings/unify-role", json={'revision': revision, 'key': 'voices', 'name': '陈小雪', 'value': 'Serena'})
        data = fetch(c, c.post(f'/api/projects/{chapter}/package').json())
        revision = c.get('/api/books/' + book['id']).json()['revision']
        assert c.delete(f"/api/master-books/{book['id']}/chapters/{chapter}?revision={revision}").status_code == 200
        back = bring_back(c, data).json()
        assert back['projects'] == [chapter] and back['loose'] == [chapter]
        alone = c.get('/api/projects/' + chapter).json()
        assert not alone.get('book') and alone['voices']['陈小雪'] == 'Serena'     # the book's voice, frozen in
        assert chapter not in c.get('/api/books/' + book['id']).json()['members']


def test_a_supplied_recording_needs_its_consent_confirmed_again(tmp_path):
    with client_for(tmp_path) as c:
        library = c.app.state.store.library
        rate = 24000
        pcm = (0.2 * np.sin(2 * np.pi * 180 * np.arange(rate * 3) / rate)).astype(np.float32)
        own = library.create(name='我的声音', pcm=pcm, rate=rate, reference_text='雨点敲着窗。', language='zh', source='provided', consent_confirmed=True)
        p = create(c, 'zh')
        speaker = p['segments'][0]['speaker']
        p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'speaker': speaker, 'voice': 'custom:' + own['id']}).json()
        made = c.post(f"/api/projects/{p['id']}/package").json()
        assert made['provided_recordings'] == ['我的声音']
        data = fetch(c, made)
        remove_project(c, p)
        assert c.delete(f"/api/voices/custom/{own['id']}").status_code == 200
        asked = bring_back(c, data)
        assert asked.status_code == 409 and asked.json()['detail']['consent'] == ['我的声音']
        assert not (tmp_path / 'projects' / p['id']).exists()                        # nothing came back without it
        assert bring_back(c, data, consent='true').status_code == 200
        assert library.get(own['id'])['source'] == 'provided'


def test_a_package_that_is_tampered_with_or_reaches_outside_is_refused(tmp_path):
    with client_for(tmp_path) as c:
        p = generate(c, create(c, 'zh'))
        data = fetch(c, c.post(f"/api/projects/{p['id']}/package").json())
        remove_project(c, p)

        def rebuilt(change):
            out = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, 'w') as dst:
                for info in src.infolist():
                    name, body = change(info.filename, src.read(info.filename))
                    if name:
                        dst.writestr(name, body)
            return out.getvalue()

        one_take = next(n for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.endswith('.wav'))
        tampered = rebuilt(lambda n, b: (n, b[:-4] + b'\x00\x00\x00\x01' if n == one_take else b))
        r = bring_back(c, tampered)
        assert r.status_code == 400 and '校验不一致' in r.json()['detail']

        def escape(n, b):
            if n == 'manifest.json':
                m = json.loads(b); m['files']['../outside.txt'] = m['files'].pop(one_take); return n, json.dumps(m).encode()
            return ('../outside.txt', b) if n == one_take else (n, b)
        r = bring_back(c, rebuilt(escape))
        assert r.status_code == 400 and '不该出现' in r.json()['detail']
        assert not (tmp_path / 'outside.txt').exists() and not (tmp_path / 'projects' / p['id']).exists()
        assert bring_back(c, b'not a zip').status_code == 400

FIXTURES = __import__('pathlib').Path(__file__).parent / 'fixtures'


def test_packages_made_by_the_first_version_still_come_back(tmp_path):
    """本人 2026-09-25: 注意打包的版本，将来恢复时，有可能数据结构变了. These two
    packages were made by the first version of the format (test tones, not
    speech) and are never regenerated: if a change to a record's shape stops
    them restoring, it needs its step in packages.UPGRADES — not a new sample."""
    with client_for(tmp_path) as c:
        one = bring_back(c, (FIXTURES / 'package-v1-project.voxstage').read_bytes())
        assert one.status_code == 200, one.text
        p = c.get('/api/projects/' + one.json()['projects'][0]).json()
        assert p['name'] == '雨夜样本' and [s['text'] for s in p['segments']] == ['雨点敲着窗。', '走吧。']
        assert p['voices']['陈小雪'].startswith('custom:') and one.json()['voices_added'] == 1
        book = bring_back(c, (FIXTURES / 'package-v1-book.voxstage').read_bytes())
        assert book.status_code == 200, book.text
        assert c.get('/api/books/' + book.json()['book_id']).json()['title'] == '雨夜样本书'
        assert len(book.json()['projects']) == 2


def test_a_package_from_a_newer_program_is_refused_and_an_older_shape_is_brought_up(tmp_path, monkeypatch):
    from runtime import packages
    data = (FIXTURES / 'package-v1-project.voxstage').read_bytes()

    def with_manifest(change):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, 'w') as dst:
            for name in src.namelist():
                body = src.read(name)
                if name == 'manifest.json':
                    m = json.loads(body); change(m); body = json.dumps(m).encode()
                dst.writestr(name, body)
        return out.getvalue()

    with client_for(tmp_path) as c:
        for change in (lambda m: m.update(version=packages.VERSION + 1), lambda m: m['data'].update(project=packages.DATA['project'] + 1)):
            r = bring_back(c, with_manifest(change))
            assert r.status_code == 400 and '更新的 VoxStage' in r.json()['detail']
        # A future shape 2: the step from 1 runs on the old record before it is kept.
        monkeypatch.setitem(packages.DATA, 'project', 2)
        monkeypatch.setitem(packages.UPGRADES, ('project', 1), lambda record: {**record, 'schema_version': 2, 'upgraded': True})
        back = bring_back(c, data)
        assert back.status_code == 200, back.text
        stored = json.loads((tmp_path / 'projects' / back.json()['projects'][0] / 'project.json').read_text())
        assert stored['schema_version'] == 2 and stored['upgraded']


# 最后更新：2026-09-25 · Claude Hera

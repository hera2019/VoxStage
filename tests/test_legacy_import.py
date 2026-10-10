"""Installer folder import, using invented test tones and disposable data only."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runtime.app import create_app
from runtime import packages
from runtime.books import Books
from runtime.legacy_import import LegacyImporter
from tests.test_voice_library import LongFixtureEngine, wav_b64
from tests.test_workflow import create, generate, HEADERS


def client(root):
    return TestClient(create_app(root/'projects',LongFixtureEngine()),
        base_url='http://127.0.0.1:8765',headers=HEADERS,client=('127.0.0.1',12345))


def importer(c,root):
    return LegacyImporter(c.app.state.store,Books(root/'books'),c.app.state.store.library,root/'projects-role-drafts')


def snapshot(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def work(tmp_path,monkeypatch):
    monkeypatch.setenv('VOXSTAGE_DATA_DIR',str(tmp_path/'model-config'))
    monkeypatch.setenv('VOXSTAGE_NATIVE_TOKEN','test-native-secret')
    old=tmp_path/'old';new=tmp_path/'new'
    with client(old) as source, client(new) as dest:
        yield old,new,source,dest,importer(dest,new)


def test_takes_exports_and_voices_survive_without_changing_source(work):
    old,new,source,dest,imp=work
    p=create(source,'zh')
    v=source.post('/api/voices/custom',json=dict(name='测试声线',language='zh',reference_text='雨点敲窗。',from_voice='Vivian')).json()
    p=source.patch('/api/projects/'+p['id'],json=dict(revision=p['revision'],speaker=p['segments'][0]['speaker'],voice='custom:'+v['id'])).json()
    p=generate(source,p)
    export=old/'projects'/p['id']/'exports'/'7';export.mkdir(parents=True)
    (export/'test.txt').write_text('测试字幕')
    for name in ('models','logs'):
        (old/name).mkdir();(old/name/'excluded').write_text('do not import')
    (old/'settings.json').write_text('{}');(old/'lan-key.txt').write_text('exclude')
    before=snapshot(old)
    plan=imp.preview(str(old));assert plan['voices']==1
    result=imp.commit(plan['import_id']);assert result['projects']==[p['id']]
    again=dest.get('/api/projects/'+p['id']).json()
    assert all(s['status']=='ready' for s in again['segments'])
    assert (new/'projects'/p['id']/'exports'/'7'/'test.txt').read_text()=='测试字幕'
    assert dest.app.state.store.library.get(v['id'])['synthetic_audio'] is True
    assert snapshot(old)==before
    assert not any((new/n).exists() for n in ('models','logs','settings.json','lan-key.txt'))


def test_book_members_and_inherited_voice_settings_survive_copy(work):
    old,new,source,dest,imp=work
    book=source.post('/api/master-books',json=dict(title='测试书',language='zh',script='第一章\n小雨：走吧。\n第二章\n小雨：好。')).json()
    record=source.get('/api/books/'+book['id']).json()
    response=source.post('/api/master-books/'+book['id']+'/settings/unify-role',json=dict(revision=record['revision'],key='voices',name='小雨',value='Serena'))
    assert response.status_code==200,response.text
    plan=imp.preview(str(old));imp.commit(plan['import_id'])
    before=snapshot(new)
    plan=imp.preview(str(old))
    with pytest.raises(packages.Conflict):imp.commit(plan['import_id'])
    assert snapshot(new)==before
    copied=imp.commit(plan['import_id'],as_copy=True)
    assert all(pid not in record['members'] for pid in copied['projects'])
    links={dest.get('/api/projects/'+pid).json()['book']['id'] for pid in copied['projects']}
    assert len(links)==1 and book['id'] not in links
    parent=dest.get('/api/books/'+links.pop()).json()
    assert parent['members']==copied['projects']
    assert all(dest.get('/api/projects/'+pid).json()['voices']['小雨']=='Serena' for pid in copied['projects'])


def test_recordings_require_programmatic_consent(work):
    old,new,source,dest,imp=work
    p=create(source,'zh')
    v=source.post('/api/voices/custom',json=dict(name='授权测试',language='zh',reference_text='雨点敲窗。',audio_base64=wav_b64(),consent_confirmed=True)).json()
    source.patch('/api/projects/'+p['id'],json=dict(revision=p['revision'],speaker=p['segments'][0]['speaker'],voice='custom:'+v['id']))
    plan=imp.preview(str(old))
    with pytest.raises(packages.NeedsConsent):imp.commit(plan['import_id'])
    assert not (new/'projects'/p['id']).exists()
    imp.commit(plan['import_id'],consent=True)
    assert dest.app.state.store.library.get(v['id'])['synthetic_audio'] is False


def test_changed_source_requires_a_new_preview(work):
    old,new,source,dest,imp=work
    p=create(source);plan=imp.preview(str(old))
    path=old/'projects'/p['id']/'project.json';path.write_text(path.read_text()+'\n')
    with pytest.raises(ValueError,match='已改变'):imp.commit(plan['import_id'])
    assert not (new/'projects'/p['id']).exists()


def test_symlinks_and_overlapping_folders_are_refused(work):
    old,new,source,dest,imp=work
    create(source)
    with pytest.raises(ValueError,match='不能相同'):imp.preview(str(new))
    (old/'projects'/'link').symlink_to(new,target_is_directory=True)
    with pytest.raises(ValueError,match='文件链接'):imp.preview(str(old))


def test_corrupt_voice_is_refused_before_any_project_is_placed(work):
    old,new,source,dest,imp=work
    p=create(source)
    v=source.post('/api/voices/custom',json=dict(name='测试声线',language='zh',reference_text='雨点敲窗。',from_voice='Vivian')).json()
    source.patch('/api/projects/'+p['id'],json=dict(revision=p['revision'],speaker=p['segments'][0]['speaker'],voice='custom:'+v['id']))
    (old/'voices'/(v['id']+'.wav')).write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='不一致'):imp.preview(str(old))
    assert not (new/'projects'/p['id']).exists()


def test_failure_in_second_group_rolls_back_first_group(work,monkeypatch):
    old,new,source,dest,imp=work
    create(source);create(source);create(dest)
    before=snapshot(new);plan=imp.preview(str(old));restore=packages.restore;calls=[]
    def fail_second(*args,**kwargs):
        calls.append(1)
        if len(calls)==2:raise ValueError('simulated failure')
        return restore(*args,**kwargs)
    monkeypatch.setattr(packages,'restore',fail_second)
    with pytest.raises(ValueError,match='simulated'):imp.commit(plan['import_id'])
    assert snapshot(new)==before


def test_draft_collision_copies_draft_and_relinks_its_project(work):
    old,new,source,dest,imp=work
    p=create(source);did='1'*32
    path=old/'projects'/p['id']/'project.json';record=json.loads(path.read_text());record['attribution']={'draft_id':did};path.write_text(json.dumps(record))
    drafts=old/'projects-role-drafts';drafts.mkdir(exist_ok=True)
    (drafts/(did+'.json')).write_text(json.dumps(dict(id=did,project_id=p['id'],text='旧草稿')))
    dest_drafts=new/'projects-role-drafts';dest_drafts.mkdir(exist_ok=True)
    (dest_drafts/(did+'.json')).write_text('{"text":"已有草稿"}')
    plan=imp.preview(str(old));assert plan['conflicts']
    result=imp.commit(plan['import_id'],as_copy=True);newid=result['projects'][0]
    record=json.loads((new/'projects'/newid/'project.json').read_text());newdraft=record['attribution']['draft_id']
    assert newdraft!=did
    draft=json.loads((dest_drafts/(newdraft+'.json')).read_text())
    assert draft['project_id']==newid and draft['id']==newdraft
    assert json.loads((dest_drafts/(did+'.json')).read_text())['text']=='已有草稿'


def test_empty_book_with_reference_assets_is_imported(work):
    old,new,source,dest,imp=work
    # Empty master projects are valid after all their chapters are discarded.
    book=source.post('/api/master-books',json=dict(title='空测试书',language='zh',script='第一章\n小雨：走吧。')).json()
    path=old/'books'/(book['id']+'.json');record=json.loads(path.read_text());record['members']=[];path.write_text(json.dumps(record))
    shutil.rmtree(old/'projects'/book['projects'][0]['id'])
    sha=hashlib.sha256(b'reference test').hexdigest();refs=old/'books'/(book['id']+'.assets')/'references';refs.mkdir(parents=True)
    (refs/(sha+'.wav')).write_bytes(b'reference test')
    result=imp.commit(imp.preview(str(old))['import_id'])
    assert result['books']==1 and result['projects']==[]
    assert (new/'books'/(book['id']+'.assets')/'references'/(sha+'.wav')).read_bytes()==b'reference test'


def test_native_secret_is_required_for_arbitrary_folder_access(work):
    old,new,source,dest,imp=work
    p=create(source)
    r=dest.post('/api/legacy-import/preview',json={'folder':str(old)})
    assert r.status_code==403
    r=dest.post('/api/legacy-import/preview',json={'folder':str(old)},headers={'X-VoxStage-Native':'test-native-secret'})
    assert r.status_code==200,r.text
    assert 'folder' not in r.json()
    r=dest.post('/api/legacy-import/'+r.json()['import_id']+'/commit',json={})
    assert r.status_code==200,r.text
    assert r.json()['projects']==[p['id']]


def test_network_clients_cannot_preview_folders(work):
    old,new,source,dest,imp=work
    create(source)
    with TestClient(dest.app,base_url='http://127.0.0.1:8765',headers={**HEADERS,'X-VoxStage-Native':'test-native-secret'},client=('192.168.1.80',123)) as remote:
        assert remote.post('/api/legacy-import/preview',json={'folder':str(old)}).status_code==403


def test_book_with_missing_chapter_is_refused(work):
    old,new,source,dest,imp=work
    book=source.post('/api/master-books',json=dict(title='测试书',language='zh',script='第一章\n小雨：走吧。')).json()
    shutil.rmtree(old/'projects'/book['projects'][0]['id'])
    with pytest.raises(ValueError,match='缺少章节'):imp.preview(str(old))


def test_orphan_book_asset_folder_is_never_merged_or_overwritten(work):
    old,new,source,dest,imp=work
    book=source.post('/api/master-books',json=dict(title='测试书',language='zh',script='第一章\n小雨：走吧。')).json()
    asset=new/'books'/(book['id']+'.assets');asset.mkdir();(asset/'existing').write_text('preserve')
    plan=imp.preview(str(old));assert plan['conflicts']
    with pytest.raises(packages.Conflict):imp.commit(plan['import_id'])
    imp.commit(plan['import_id'],as_copy=True)
    assert (asset/'existing').read_text()=='preserve'


def test_unknown_or_expired_preview_is_refused(work):
    old,new,source,dest,imp=work
    with pytest.raises(ValueError,match='已过期'):imp.commit('invalid')
    create(source);plan=imp.preview(str(old));imp.previews[plan['import_id']]['created']=0
    with pytest.raises(ValueError,match='已过期'):imp.commit(plan['import_id'])


def test_project_with_long_undo_history_is_not_too_large(work):
    # Undo snapshots made a real 94-line project 31 MB; the old 16 MB cap refused the whole import.
    old,new,source,dest,imp=work
    p=create(source,'zh')
    path=old/'projects'/p['id']/'project.json'
    record=json.loads(path.read_text(encoding='utf-8'))
    record['history']=[dict(record,history=[],future=[],padding='检查'*1_200_000) for _ in range(3)]
    path.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
    assert path.stat().st_size > 16*1024**2
    plan=imp.preview(str(old))
    assert [x['id'] for x in plan['projects']]==[p['id']]
    assert imp.commit(plan['import_id'])['projects']==[p['id']]


def test_project_whose_voice_was_deleted_is_named_and_left_out(work):
    # Real development data: 11 deleted voices still referenced by 12 projects, some
    # only in undo history. Those using one now do not open in the old version either.
    old,new,source,dest,imp=work
    p=create(source,'zh')
    v=source.post('/api/voices/custom',json=dict(name='已删声线',language='zh',reference_text='雨点敲窗。',from_voice='Vivian')).json()
    p=source.patch('/api/projects/'+p['id'],json=dict(revision=p['revision'],speaker=p['segments'][0]['speaker'],voice='custom:'+v['id'])).json()
    only_history=create(source,'zh')
    path=old/'projects'/only_history['id']/'project.json'
    record=json.loads(path.read_text(encoding='utf-8'))
    record['history']=[dict(record,history=[],future=[],note='custom:'+v['id'])]
    path.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
    for item in (old/'voices').glob(v['id']+'.*'):item.unlink()
    assert source.get('/api/projects/'+p['id']).status_code==404
    plan=imp.preview(str(old))
    assert plan['skipped']==[p['name']] and plan['voices']==0
    assert [x['id'] for x in plan['projects']]==[only_history['id']]
    assert imp.commit(plan['import_id'])['projects']==[only_history['id']]
    assert dest.get('/api/projects/'+only_history['id']).status_code==200
    assert not (new/'projects'/p['id']).exists()

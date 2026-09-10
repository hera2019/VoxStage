"""Returning to the source: does an edit keep the audio it should keep?

The property that matters is not that a reslice works, but that a person who
fixes one typo does not lose two hundred generated sentences.
"""
import time

import pytest
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime.attribution import source_units, carry_labels, carry_state, project_segments
from runtime.script_check import inspect, apply_fix

HEADERS = {'X-VoxStage': '1'}
SOURCE = '雨点敲着窗。“你听见了吗？”小林问。“那只是风。”阿宁说。'


class Roles:
    ready = True
    def annotate(self, text, log_path):
        units = source_units(text)
        speakers = ['小林', '阿宁']
        used = 0
        labels = []
        for u in units:
            if u['text'].startswith(('“', '"')):
                labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': speakers[used % 2]})
                used += 1
            else:
                labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR'})
        return {'labels': labels, 'model_sha256': 'fixture'}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'projects', FixtureEngine(), role_engine=Roles()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        yield c


def make(client, source=SOURCE):
    draft = client.post('/api/attribution/draft', json={'script': source, 'language': 'zh'}).json()
    labels = [{k: u[k] for k in ('id', 'kind', 'speaker')} for u in draft['units']]
    project = client.post('/api/attribution/confirm',
                          json={'draft_id': draft['draft_id'], 'name': '改稿测试', 'labels': labels}).json()
    client.post(f"/api/projects/{project['id']}/render/start", json={'revision': project['revision']})
    return wait(client, project['id'])


def wait(client, project_id, limit=200):
    """Rendering is queued; the audio-preservation property needs real audio."""
    for _ in range(limit):
        state = client.get(f'/api/projects/{project_id}').json()
        if state['job']['status'] != 'running':
            return state
        time.sleep(0.05)
    raise AssertionError('渲染未在预期时间内结束')


# ── the check ────────────────────────────────────────────────────────────────

def test_unclosed_quote_is_an_error_because_it_swallows_the_rest():
    report = inspect('他说：“今天不营业。然后走开了。')
    assert report['blocking']
    assert report['findings'][0]['kind'] == 'unclosed_quote'


def test_clean_source_reports_nothing_blocking():
    assert not inspect(SOURCE)['blocking']


def test_fixes_are_idempotent_and_only_touch_their_own_kind():
    text = '他停住了……不，是...停住了--真的。'
    once = apply_fix(text, 'ellipsis_dots')
    assert apply_fix(once, 'ellipsis_dots') == once
    assert '--' in once, '省略号修正不应动破折号'
    assert '——' in apply_fix(once, 'dash_ascii')


def test_fix_never_invents_a_replacement_it_cannot_make():
    with pytest.raises(ValueError):
        apply_fix('文本', 'unclosed_quote')


# ── carrying work across a reslice ───────────────────────────────────────────

def test_unchanged_lines_keep_their_audio(client):
    project = make(client)
    before = {(s['speaker'], s['text']): s['audio'] for s in project['segments'] if s['audio']}
    assert before, '前置条件：先要有已生成的音频'

    edited = SOURCE.replace('雨点敲着窗。', '雨点轻轻敲着窗。')
    applied = client.post(f"/api/projects/{project['id']}/script",
                          json={'revision': project['revision'], 'source_script': edited,
                                'labels': carry_labels(project['segments'], edited, 'zh')})
    assert applied.status_code == 200, applied.text
    after = applied.json()

    kept = [s for s in after['segments'] if (s['speaker'], s['text']) in before]
    assert kept, '改一句不应让其余句子全部失配'
    for s in kept:
        assert s['audio'] == before[(s['speaker'], s['text'])], f'{s["text"]} 的音频丢了'
    changed = [s for s in after['segments'] if '轻轻' in s['text']]
    assert changed and changed[0]['audio'] is None, '改动的句子必须重新生成'


def test_preview_reports_the_cost_before_committing(client):
    project = make(client)
    edited = SOURCE + '“明天见。”'
    preview = client.post(f"/api/projects/{project['id']}/script",
                          json={'revision': project['revision'], 'source_script': edited}).json()
    assert preview['preview'] is True
    assert preview['kept'] >= 3 and preview['fresh'] >= 1
    assert [u['id'] for u in preview['unresolved']], '新增的对白必须要求指定角色'
    reloaded = client.get(f"/api/projects/{project['id']}").json()
    assert reloaded['revision'] == project['revision'], '预览不得改动工程'


def test_new_narration_resolves_itself_but_new_dialogue_asks():
    segments = project_segments(SOURCE, [
        {'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
         'speaker': '小林' if u['text'].startswith('“') else '旁白'}
        for u in source_units(SOURCE)], 'zh')
    grown = SOURCE + '夜色更深了。“还在吗？”'
    labels = carry_labels(segments, grown, 'zh')
    unresolved = [l for l in labels if l['speaker'].upper() == 'UNKNOWN']
    assert len(unresolved) == 1, '只有新增对白需要人工介入'
    assert all(l['speaker'] == '旁白' for l in labels if l['kind'] == 'narration')


def test_a_stale_revision_cannot_overwrite_newer_work(client):
    project = make(client)
    body = {'revision': project['revision'] - 1, 'source_script': SOURCE + '结束。',
            'labels': carry_labels(project['segments'], SOURCE + '结束。', 'zh')}
    assert client.post(f"/api/projects/{project['id']}/script", json=body).status_code >= 400


def test_rewrite_is_undoable(client):
    project = make(client)
    edited = SOURCE.replace('雨点敲着窗。', '风穿过走廊。')
    after = client.post(f"/api/projects/{project['id']}/script",
                        json={'revision': project['revision'], 'source_script': edited,
                              'labels': carry_labels(project['segments'], edited, 'zh')}).json()
    assert after['can_undo']
    back = client.post(f"/api/projects/{project['id']}/undo", json={'revision': after['revision']})
    assert back.status_code == 200, back.text
    assert '雨点敲着窗。' in ''.join(s['text'] for s in back.json()['segments'])


def test_audio_files_are_never_deleted_by_a_rewrite(client, tmp_path):
    project = make(client)
    folder = tmp_path/'projects'/project['id']/'audio'
    before = {p.name for p in folder.glob('*.wav')}
    edited = SOURCE.replace('雨点敲着窗。', '完全不同的开场白。')
    client.post(f"/api/projects/{project['id']}/script",
                json={'revision': project['revision'], 'source_script': edited,
                      'labels': carry_labels(project['segments'], edited, 'zh')})
    assert before <= {p.name for p in folder.glob('*.wav')}, '改稿不得删除任何已生成音频'

# 最后更新：2026-09-10 · Claude Hera


# ── slicing tidiness ─────────────────────────────────────────────────────────

def labels_for(source):
    return [{'id': u['id'], 'kind': 'dialogue' if u['text'][:1] in '“"' else 'narration',
             'speaker': '小林' if u['text'][:1] in '“"' else '旁白'} for u in source_units(source)]


def test_a_line_never_starts_with_the_previous_sentences_punctuation():
    source = '他写着“今天不营业”。\n陈默停下脚步。'
    for s in project_segments(source, labels_for(source), 'zh'):
        assert s['text'][0] not in '。！？，、；：… \n', f'字幕不该以 {s["text"][0]!r} 开头'


def test_slicing_still_reconstructs_the_source_exactly():
    for source in ['他写着“今天不营业”。\n陈默停下脚步。',
                   '“一。”\n\n“二。”  \n“三。”',
                   '开场。“甲。”“乙。”，收尾。']:
        segments = project_segments(source, labels_for(source), 'zh')
        assert ''.join(s['text'] for s in segments) == source
        assert all(s['text'] == source[s['source_start']:s['source_end']] for s in segments)


def test_blank_runs_are_carried_not_dropped():
    source = '“甲。”\n\n\n“乙。”'
    segments = project_segments(source, labels_for(source), 'zh')
    assert ''.join(s['text'] for s in segments) == source, '空白不能被丢掉，否则原稿对不上'


# ── deleting a line ──────────────────────────────────────────────────────────

def test_deleting_a_line_also_removes_it_from_the_script(client):
    project = make(client)
    target = next(s for s in project['segments'] if s['text'] == '苏晴说。') \
        if any(s['text'] == '苏晴说。' for s in project['segments']) else project['segments'][-1]
    after = client.post(f"/api/projects/{project['id']}/segments/{target['id']}/delete",
                        json={'revision': project['revision']})
    assert after.status_code == 200, after.text
    state = after.json()
    assert len(state['segments']) == len(project['segments']) - 1
    assert target['text'] not in state['source_script'] or state['source_script'].count(target['text']) < \
        project['source_script'].count(target['text'])
    assert ''.join(s['text'] for s in state['segments']) == state['source_script'], '删除后原稿与句子必须仍然一致'


def test_deleting_is_undoable_and_keeps_the_audio_on_disk(client, tmp_path):
    project = make(client)
    folder = tmp_path/'projects'/project['id']/'audio'
    before = {p.name for p in folder.glob('*.wav')}
    target = project['segments'][-1]
    after = client.post(f"/api/projects/{project['id']}/segments/{target['id']}/delete",
                        json={'revision': project['revision']}).json()
    assert before <= {p.name for p in folder.glob('*.wav')}, '删除不得清理音频'
    back = client.post(f"/api/projects/{project['id']}/undo", json={'revision': after['revision']}).json()
    assert len(back['segments']) == len(project['segments'])


def test_the_last_line_cannot_be_deleted(client):
    project = make(client)
    keep = project['segments'][0]['id']
    revision = project['revision']
    for s in project['segments'][1:]:
        revision = client.post(f"/api/projects/{project['id']}/segments/{s['id']}/delete",
                               json={'revision': revision}).json()['revision']
    assert client.post(f"/api/projects/{project['id']}/segments/{keep}/delete",
                       json={'revision': revision}).status_code >= 400


# ── error messages that name the rule they enforce ───────────────────────────

@pytest.mark.parametrize('value,expected', [
    ('第一行\n第二行', '换行'),
    ('字' * 61, '61'),
    ('   ', '删除这一句'),
])
def test_each_rejection_says_which_rule_it_broke(client, value, expected):
    project = make(client)
    response = client.patch(f"/api/projects/{project['id']}",
                            json={'revision': project['revision'],
                                  'segment_id': project['segments'][0]['id'], 'text': value})
    assert response.status_code >= 400
    assert expected in response.json()['detail'], response.text


# ── the script and the lines must keep telling the same story ────────────────

def test_editing_one_line_updates_the_script_behind_it(client):
    project = make(client)
    target = project['segments'][1]
    after = client.patch(f"/api/projects/{project['id']}",
                         json={'revision': project['revision'], 'segment_id': target['id'],
                               'text': '“你真的听见了吗？”'}).json()
    assert ''.join(s['text'] for s in after['segments']) == after['source_script'], \
        '逐句编辑后，原稿编辑里看到的必须是最新文字'
    assert all(s['text'] == after['source_script'][s['source_start']:s['source_end']]
               for s in after['segments']), '偏移量必须跟着移动'


def test_a_script_rewrite_after_line_edits_does_not_undo_them(client):
    project = make(client)
    edited = client.patch(f"/api/projects/{project['id']}",
                          json={'revision': project['revision'], 'segment_id': project['segments'][1]['id'],
                                'text': '“你真的听见了吗？”'}).json()
    preview = client.post(f"/api/projects/{edited['id']}/script",
                          json={'revision': edited['revision'],
                                'source_script': edited['source_script']}).json()
    assert preview['fresh'] == 0, '原稿未变时重新切分不应产生待生成的句子'
    assert '“你真的听见了吗？”' in edited['source_script']


def test_spoken_as_never_touches_the_script(client):
    project = make(client)
    before = project['source_script']
    after = client.patch(f"/api/projects/{project['id']}",
                         json={'revision': project['revision'], 'segment_id': project['segments'][0]['id'],
                               'spoken_as': '雨点敲着窗户'}).json()
    assert after['source_script'] == before, '朗读文本是读法覆盖，不是原文'

"""Sol 二 engineering checks; fake model only, no quality acceptance claim."""
from copy import deepcopy
import time

import pytest

from evals.speaker_attribution.source_units import source_units
from runtime.attribution_batches import (combined_labels, plan_batches, resume_plan,
                                         validate_batch_labels)
from runtime.capacity import role_batch_limits


TEXT = ''.join(f'阿宁说：“第{i}句。”\n' for i in range(36))


def small_limits():
    limits = role_batch_limits({'max_units': 12, 'max_chars': 500, 'max_context': 4096,
                                'max_tokens': 1024}, 32)
    limits['segments'] = 1000
    return limits


def labels_for(ids, units):
    by_id = {unit['id']: unit for unit in units}
    return [{'id': unit_id,
             'kind': 'dialogue' if by_id[unit_id]['text'].lstrip().startswith('“') else 'narration',
             'speaker': '阿宁' if by_id[unit_id]['text'].lstrip().startswith('“') else 'NARRATOR',
             'certain': True} for unit_id in ids]


def test_windows_keep_global_ids_cover_targets_once_and_budget_context():
    plan = plan_batches(TEXT, None, small_limits(), known_names=['阿宁'])
    units = [unit for unit in source_units(TEXT) if unit['text'].strip()]
    targets = [unit_id for batch in plan['batches'] for unit_id in batch['target_ids']]
    assert targets == [unit['id'] for unit in units]
    assert len(plan['batches']) > 1
    assert all(batch['estimate']['fits'] for batch in plan['batches'])
    assert all(set(batch['target_ids']).isdisjoint(batch['context_ids']) for batch in plan['batches'])
    assert any(batch['context_ids'] for batch in plan['batches'][1:])


def test_batch_validation_refuses_missing_duplicate_reordered_and_extra_ids():
    plan = plan_batches(TEXT, None, small_limits())
    batch = plan['batches'][0]
    units = source_units(TEXT)
    valid = labels_for(batch['sent_ids'], units)
    assert [row['id'] for row in validate_batch_labels(batch, valid)] == batch['target_ids']
    for bad in (valid[:-1], valid + [valid[-1]], list(reversed(valid))):
        with pytest.raises(ValueError, match='缺号、重号或顺序'):
            validate_batch_labels(batch, bad)


def test_resume_keeps_completed_batches_and_retries_running_or_failed():
    plan = plan_batches(TEXT, None, small_limits())
    plan['model_id'] = 'model-a'
    units = source_units(TEXT)
    first = plan['batches'][0]
    first.update(status='completed', labels=validate_batch_labels(
        first, labels_for(first['sent_ids'], units)))
    plan['batches'][1].update(status='running', error='interrupted')
    if len(plan['batches']) > 2:
        plan['batches'][2].update(status='failed', error='bad response')
    resumed = resume_plan(plan, TEXT, None, 'model-a')
    assert resumed['batches'][0] == first
    assert resumed['batches'][1]['status'] == 'pending' and resumed['batches'][1]['error'] is None
    if len(resumed['batches']) > 2:
        assert resumed['batches'][2]['status'] == 'pending'
    assert plan['batches'][1]['status'] == 'running'


def test_combined_result_has_every_source_unit_in_original_order():
    plan = plan_batches(TEXT, None, small_limits())
    units = source_units(TEXT)
    for batch in plan['batches']:
        batch.update(status='completed', labels=validate_batch_labels(
            batch, labels_for(batch['sent_ids'], units)))
    combined = combined_labels(TEXT, None, plan)
    assert [row['id'] for row in combined] == [unit['id'] for unit in units]
    assert len(combined) == len({row['id'] for row in combined})


class BatchRoles:
    model_id = 'qwen3-30b-a3b-instruct-2507-q4km'
    sha256 = 'f' * 64
    ready = True

    def installed(self):
        return [{'id': self.model_id, 'label': '测试模型', 'installed': True,
                 'loadable': True, 'minimum_memory_gb': 0, 'recommended': True}]

    def annotate(self, text, log_path, known_names=(), examples=(), cut=None,
                 units_override=None, strict_ids=False, limits_override=None):
        units = units_override or source_units(text, cut)
        rows = labels_for([unit['id'] for unit in units if unit['text'].strip()], units)
        return {'labels': rows, 'model_id': self.model_id, 'model_sha256': self.sha256,
                'prompt_sha256': 'e' * 64, 'seconds_measured': 0.001, 'repaired': None}


def test_project_batches_finish_review_and_confirmation_updates_same_project(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.engines import FixtureEngine

    headers = {'x-voxstage': '1'}
    script = '第一章\n' + ''.join(f'阿宁说：“第{i}句。”\n' for i in range(70))
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine(), role_engine=BatchRoles()),
                    base_url='http://127.0.0.1', headers=headers) as client:
        book = client.post('/api/master-books', json={
            'title': '分批测试', 'language': 'zh', 'script': script,
        }).json()
        project_id = book['projects'][0]['id']
        project = client.get('/api/projects/' + project_id).json()
        capacity = client.get(f'/api/projects/{project_id}/attribution/capacity')
        assert capacity.status_code == 200, capacity.text
        assert capacity.json()['batches'] > 1
        started = client.post(f'/api/projects/{project_id}/attribution/start', json={
            'revision': project['revision'], 'resume': True,
        })
        assert started.status_code == 200, started.text
        for _ in range(200):
            project = client.get('/api/projects/' + project_id).json()
            if project['job']['status'] in ('completed', 'failed'):
                break
            time.sleep(.01)
        assert project['job']['status'] == 'completed', project['job']
        draft_id = project['attribution_batch']['draft_id']
        draft = client.get('/api/attribution/draft/' + draft_id).json()
        assert draft['target_project_id'] == project_id
        labels = []
        for unit in draft['units']:
            if not unit['text'].strip():
                speaker, kind = 'NARRATOR', 'narration'
            elif unit['kind'] == 'dialogue':
                speaker, kind = ('阿宁' if unit['speaker'] in ('', 'UNKNOWN', 'NARRATOR') else unit['speaker']), 'dialogue'
            else:
                speaker, kind = 'NARRATOR', 'narration'
            labels.append({'id': unit['id'], 'kind': kind, 'speaker': speaker})
        confirmed = client.post('/api/attribution/confirm', json={
            'draft_id': draft_id, 'name': '分批测试 · 第一章', 'labels': labels,
            'expected_revision': draft['revision'],
        })
        assert confirmed.status_code == 200, confirmed.text
        result = confirmed.json()
        assert result['id'] == project_id and result['processing_state'] == 'processed'
        assert result['segments'] and result['settings_schema'] == 1


class SlowBatchRoles(BatchRoles):
    def annotate(self, *args, **kwargs):
        time.sleep(.15)
        return super().annotate(*args, **kwargs)


class FallbackBatchRoles(BatchRoles):
    primary = 'qwen3-30b-a3b-instruct-2507-q4km'
    fallback = 'qwen3-14b-q4km'

    def installed(self):
        return [{'id': model_id, 'label': model_id, 'installed': True,
                 'loadable': True, 'minimum_memory_gb': 0, 'recommended': False}
                for model_id in (self.primary, self.fallback)]

    def select(self, model_id):
        self.model_id = model_id
        self.sha256 = ('f' if model_id == self.primary else 'e') * 64
        self.ready = True

    def annotate(self, text, log_path, known_names=(), examples=(), cut=None,
                 units_override=None, strict_ids=False, limits_override=None):
        units = units_override or source_units(text, cut)
        if self.model_id == self.primary:
            rows = [{'id': unit['id'], 'kind': 'narration', 'speaker': 'NARRATOR',
                     'certain': True} for unit in units if unit['text'].strip()]
        else:
            rows = labels_for([unit['id'] for unit in units if unit['text'].strip()], units)
        return {'labels': rows, 'model_id': self.model_id, 'model_sha256': self.sha256,
                'prompt_sha256': 'd' * 64, 'seconds_measured': 0.001, 'repaired': None}


def test_a_balked_batch_uses_a_better_installed_fallback(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.engines import FixtureEngine

    headers = {'x-voxstage': '1'}
    roles = FallbackBatchRoles()
    script = ''.join(f'阿宁说：“第{i}句。”\n' for i in range(8))
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine(), role_engine=roles),
                    base_url='http://127.0.0.1', headers=headers) as client:
        record = client.post('/api/project-records', json={
            'name': '兜底', 'language': 'zh', 'script': script,
        }).json()
        response = client.post(f"/api/projects/{record['id']}/attribution/start", json={
            'revision': record['revision'],
        })
        assert response.status_code == 200, response.text
        for _ in range(200):
            record = client.get('/api/projects/' + record['id']).json()
            if record['job']['status'] in ('completed', 'failed'):
                break
            time.sleep(.01)
        assert record['job']['status'] == 'completed', record['job']
        batch = record['attribution_batch']['batches'][0]
        assert batch['fallback_model'] == roles.fallback
        assert batch['first_model_id'] == roles.primary
        assert sum(row['speaker'] == '阿宁' for row in batch['labels']) == len(batch['target_ids']) // 2


def test_same_book_second_chapter_is_refused_while_first_is_queued_or_running(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.engines import FixtureEngine

    headers = {'x-voxstage': '1'}
    script = ('第一章\n' + ''.join(f'阿宁说：“甲{i}。”\n' for i in range(60))
              + '第二章\n' + ''.join(f'阿宁说：“乙{i}。”\n' for i in range(60)))
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine(), role_engine=SlowBatchRoles()),
                    base_url='http://127.0.0.1', headers=headers) as client:
        book = client.post('/api/master-books', json={
            'title': '占用测试', 'language': 'zh', 'script': script,
        }).json()
        first_id, second_id = [row['id'] for row in book['projects']]
        first = client.get('/api/projects/' + first_id).json()
        second = client.get('/api/projects/' + second_id).json()
        assert client.post(f'/api/projects/{first_id}/attribution/start', json={
            'revision': first['revision'],
        }).status_code == 200
        blocked = client.post(f'/api/projects/{second_id}/attribution/start', json={
            'revision': second['revision'],
        })
        assert blocked.status_code == 409
        tasks = client.get('/api/model-tasks').json()
        assert book['id'] in tasks['busy_books']


def test_different_books_share_one_fifo_model_queue(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.engines import FixtureEngine

    headers = {'x-voxstage': '1'}
    script = '第一章\n' + ''.join(f'阿宁说：“第{i}句。”\n' for i in range(60))
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine(), role_engine=SlowBatchRoles()),
                    base_url='http://127.0.0.1', headers=headers) as client:
        books = [client.post('/api/master-books', json={
            'title': f'书{number}', 'language': 'zh', 'script': script,
        }).json() for number in range(2)]
        project_ids = [book['projects'][0]['id'] for book in books]
        for project_id in project_ids:
            project = client.get('/api/projects/' + project_id).json()
            response = client.post(f'/api/projects/{project_id}/attribution/start', json={
                'revision': project['revision'],
            })
            assert response.status_code == 200, response.text
        tasks = client.get('/api/model-tasks').json()
        assert len(tasks['tasks']) == 2
        assert sum(task['status'] == 'running' for task in tasks['tasks']) <= 1
        queued = [task for task in tasks['tasks'] if task['status'] == 'queued']
        assert queued and [task['queue_position'] for task in queued] == list(range(1, len(queued) + 1))
        assert set(tasks['busy_books']) == {book['id'] for book in books}

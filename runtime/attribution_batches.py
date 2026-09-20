"""Capacity-aware, resumable windows for production speaker attribution.

The model still receives the evaluated production prompt. Windows only bound
the amount of source sent at once; context labels are discarded and every
nonblank source unit is a target exactly once under its original global ID.
"""
from copy import deepcopy
import hashlib
import json
import math

from evals.speaker_attribution.source_units import source_units
from .capacity import estimate_role_batch

PLAN_VERSION = 1
CONTEXT_UNITS = 4


def source_fingerprint(text, cut=None):
    return hashlib.sha256(json.dumps({'text': text, 'cut': cut}, ensure_ascii=False,
                                     sort_keys=True).encode()).hexdigest()


def prompt_extra_tokens(known_names=(), examples=()):
    """Conservative allowance beyond the production prompt's calibrated base."""
    extra = ''
    if known_names:
        extra += 'Characters:' + '、'.join(known_names)
    if examples:
        extra += json.dumps(examples, ensure_ascii=False, sort_keys=True)
    return math.ceil(len(extra) * 1.1)


def _window(nonblank, start, end, context, limits, extra_prompt_tokens):
    left = max(0, start - context)
    right = min(len(nonblank), end + context)
    sent = nonblank[left:right]
    targets = nonblank[start:end]
    chars = sum(len(unit['text']) for unit in sent)
    estimate = estimate_role_batch(chars, len(sent), limits, extra_prompt_tokens)
    return {
        'target_ids': [unit['id'] for unit in targets],
        'context_ids': [unit['id'] for unit in sent if unit not in targets],
        'sent_ids': [unit['id'] for unit in sent],
        'source_start': sent[0]['start'],
        'source_end': sent[-1]['end'],
        'estimate': estimate,
    }


def plan_batches(text, cut, limits, *, known_names=(), examples=()):
    units = source_units(text, cut)
    nonblank = [unit for unit in units if unit['text'].strip()]
    if not nonblank:
        raise ValueError('原稿里没有可以分析的片段。')
    extra = prompt_extra_tokens(known_names, examples)
    batches = []
    start = 0
    while start < len(nonblank):
        best = None
        # Greedy longest target range. Estimates are monotonic as the range grows.
        for end in range(start + 1, len(nonblank) + 1):
            candidate = _window(nonblank, start, end, CONTEXT_UNITS, limits, extra)
            if not candidate['estimate']['fits']:
                break
            best = candidate
        if best is None:
            # Context may be the only reason a single target does not fit. Shrink
            # it explicitly; a target itself is never split or silently dropped.
            for context in range(CONTEXT_UNITS - 1, -1, -1):
                candidate = _window(nonblank, start, start + 1, context, limits, extra)
                if candidate['estimate']['fits']:
                    best = candidate
                    break
        if best is None:
            unit = nonblank[start]
            raise ValueError(f"片段 {unit['id']} 单独处理也超过当前模型与本机的安全上限。")
        best['index'] = len(batches)
        best['status'] = 'pending'
        best['labels'] = None
        best['error'] = None
        batches.append(best)
        start += len(best['target_ids'])
    targets = [unit_id for batch in batches for unit_id in batch['target_ids']]
    expected = [unit['id'] for unit in nonblank]
    if targets != expected or len(targets) != len(set(targets)):
        raise AssertionError('批次没有逐个覆盖全局单元。')
    return {
        'version': PLAN_VERSION,
        'source_sha256': source_fingerprint(text, cut),
        'limits': {key: limits[key] for key in ('chars', 'units', 'context', 'max_tokens', 'memory_gb')},
        'extra_prompt_tokens': extra,
        'total_units': len(nonblank),
        'batches': batches,
    }


def units_for_batch(text, cut, batch):
    by_id = {unit['id']: unit for unit in source_units(text, cut)}
    try:
        return [deepcopy(by_id[unit_id]) for unit_id in batch['sent_ids']]
    except KeyError as exc:
        raise ValueError('批次单元与当前原稿不一致。') from exc


def validate_batch_labels(batch, labels):
    if not isinstance(labels, list):
        raise ValueError('模型没有返回标签列表。')
    expected = batch['sent_ids']
    ids = [row.get('id') for row in labels if isinstance(row, dict)]
    if len(ids) != len(labels) or ids != expected or len(ids) != len(set(ids)):
        raise ValueError('本批标签缺号、重号或顺序与全局单元不一致。')
    allowed = {'narration', 'dialogue'}
    for row in labels:
        if row.get('kind') not in allowed or not isinstance(row.get('speaker'), str):
            raise ValueError('本批标签字段无效。')
        if row['kind'] == 'narration' and row['speaker'] != 'NARRATOR':
            raise ValueError('旁白标签与说话人不一致。')
    targets = set(batch['target_ids'])
    return [deepcopy(row) for row in labels if row['id'] in targets]


def combined_labels(text, cut, plan):
    if plan.get('version') != PLAN_VERSION or plan.get('source_sha256') != source_fingerprint(text, cut):
        raise ValueError('批次计划与当前原稿不一致。')
    labels = {}
    for batch in plan['batches']:
        if batch.get('status') != 'completed':
            raise ValueError('仍有批次尚未完成。')
        for row in batch.get('labels') or []:
            if row['id'] in labels:
                raise ValueError('同一全局单元被多个批次重复写入。')
            labels[row['id']] = deepcopy(row)
    result = []
    for unit in source_units(text, cut):
        if not unit['text'].strip():
            result.append({'id': unit['id'], 'kind': 'narration',
                           'speaker': 'NARRATOR', 'certain': True})
        elif unit['id'] in labels:
            result.append(labels[unit['id']])
        else:
            raise ValueError(f"批次结果缺少全局单元 {unit['id']}。")
    return result


def resume_plan(plan, text, cut, model_id):
    if (plan.get('version') != PLAN_VERSION
            or plan.get('source_sha256') != source_fingerprint(text, cut)
            or plan.get('model_id') != model_id):
        raise ValueError('原稿、切分方式或模型已经变化，不能沿用旧批次。')
    resumed = deepcopy(plan)
    for batch in resumed['batches']:
        if batch.get('status') in ('running', 'failed'):
            batch.update(status='pending', error=None)
    return resumed


def progress(plan):
    statuses = [batch.get('status') for batch in plan.get('batches', [])]
    return {'completed': statuses.count('completed'), 'running': statuses.count('running'),
            'pending': statuses.count('pending'), 'failed': statuses.count('failed'),
            'total': len(statuses)}

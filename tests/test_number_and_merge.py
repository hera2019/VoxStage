"""Checks supplied by Claude Hera; no subjective model scoring."""
import hashlib
import pytest
from runtime.numbers import integer_value, BASIS
from runtime.content_check import compare_text
from runtime.attribution import project_segments, source_units, carry_labels
from test_script_rewrite import client, make

@pytest.mark.parametrize('text,value',[
 ('三百二',320),('一千零八十',1080),('三百零二',302),('一千八',1800),('两千五',2500),
 ('十五',15),('九十九',99),('一百',100),('一千八十',1080),('一千零三百二',1320),('零',0),
 ('九千九百九十九',9999)])
def test_integer_values(text,value):
    assert integer_value(text)==value
    r=compare_text(text,str(value),'zh');assert r['status']=='match'
    assert r['equivalences']==[{'expected':text,'recognized':str(value),'basis':BASIS}]
    assert r['compatibility_notices']

@pytest.mark.parametrize('text',['','第三','三百二元','一万','一亿','一万三千','一二三','二〇二四','十百','一百百','零十','一百零','3百','3.2','10000','001'])
def test_unknown_strings_are_not_guessed(text):
    assert integer_value(text) is None

@pytest.mark.parametrize('expected,recognized',[
 ('三百二','三百五'),('第三','第3'),('一万','10000'),('二〇二四','2024'),('三点二','3.2'),('三百二','32'),('三百二','3.20'),('三百二','3,200')])
def test_real_difference_and_unsupported_not_normalized(expected,recognized):
    assert compare_text(expected,recognized,'zh')['status']=='review'

def test_visible_equivalence_and_existing_homophones():
    r=compare_text('他只花了三百二，剩下一千零八十。','他只花了320，剩下1080。','zh')
    assert r['status']=='match' and len(r['equivalences'])==2
    assert r['expected_text']=='他只花了三百二，剩下一千零八十。'
    assert compare_text('三百二。','320.','zh')['status']=='match'
    assert compare_text('吃的好，睡的香，花了三百二元。','吃得好睡得香花了320元','zh')['status']=='match'
    r=compare_text('一千零八十','一千八十','zh')
    assert r['status']=='match' and r['equivalences'][0]['basis']==BASIS and r['compatibility_notices']

def test_saved_asr_digit_chunks_keep_real_word_error():
    r=compare_text('“押金三百二，机器一千零八十。”','销\n金\n3\n20\n机\n器\n10\n80','zh')
    assert r['status']=='review'
    assert r['differences']==[{'kind':'replace','expected':'押','recognized':'销'}]
    assert [(e['expected'],e['recognized'],e['basis']) for e in r['equivalences']]==[
        ('三百二','320',BASIS),('一千零八十','1080',BASIS)]


def test_english_comparison_unchanged():
    r=compare_text('three hundred twenty','320','en')
    assert r['status']=='review' and not r['equivalences']
    assert compare_text('Netherfield','Nether field','en')['status']=='match'

def labels(source,roles=None,kinds=None):
    return [{'id':u['id'],'speaker':roles[i] if roles else 'NARRATOR','kind':kinds[i] if kinds else 'narration'} for i,u in enumerate(source_units(source))]

def test_quoted_word_merges_and_rebuilds_source():
    source='只剩下半个“雪”字。'
    segments=project_segments(source,labels(source),'zh')
    assert len(segments)==1 and segments[0]['text']==source
    assert segments[0]['source_start']==0 and segments[0]['source_end']==len(source)
    assert project_segments(source,carry_labels(segments,source,'zh'),'zh')[0]['text']==source
    assert all(x['kind']=='narration' for x in carry_labels(segments,source,'zh'))

def test_different_roles_and_kinds_stay_separate():
    source='“甲。”旁白。“乙。”'
    segments=project_segments(source,labels(source,['甲','NARRATOR','乙'],['dialogue','narration','dialogue']),'zh')
    assert len(segments)==3 and ''.join(s['text'] for s in segments)==source
    source='前言“对白”'
    segments=project_segments(source,labels(source,['Narrator','Narrator'],['narration','dialogue']),'en')
    assert len(segments)==2

@pytest.mark.parametrize('language,limit',[('zh',60),('en',240)])
def test_merge_respects_limit_and_offsets(language,limit):
    source='字'*(limit-2)+'“雪”字。'
    segments=project_segments(source,labels(source),language)
    assert len(segments)>1 and all(len(s['text'])<=limit for s in segments)
    assert ''.join(s['text'] for s in segments)==source
    assert all(s['text']==source[s['source_start']:s['source_end']] for s in segments)

def test_existing_project_unchanged_until_explicit_reslice(client):
    # Legacy separately generated quote fragments; read/open must never rewrite them.
    source='只剩下半个“雪”字。'
    p=make(client,source);store=client.app.state.store;directory=store.directory(p['id']);url='/api/projects/'+p['id']
    saved=store.read(p['id'])
    for s in saved['segments']:s.update(speaker='旁白',kind='narration')
    store.write(saved)
    before=(directory/'project.json').read_bytes()
    originals={a.name:(hashlib.sha256(a.read_bytes()).hexdigest(),a.stat().st_mtime_ns) for a in (directory/'audio').glob('*.wav')}
    assert len(client.get(url).json()['segments'])==3
    assert (directory/'project.json').read_bytes()==before
    preview=client.post(url+'/script',json={'revision':p['revision'],'source_script':source}).json()
    assert preview['segments']==1 and preview['fresh']==1 and preview['kept_audio']==0
    assert (directory/'project.json').read_bytes()==before
    result=client.post(url+'/script',json={'revision':p['revision'],'source_script':source,'labels':preview['labels']})
    assert result.status_code==200,result.text
    updated=result.json();assert len(updated['segments'])==1
    assert updated['segments'][0]['status']=='pending' and updated['segments'][0]['audio'] is None
    assert updated['source_script']==source
    assert originals=={a.name:(hashlib.sha256(a.read_bytes()).hexdigest(),a.stat().st_mtime_ns) for a in (directory/'audio').glob('*.wav')}
    undo=client.post(url+'/undo',json={'revision':updated['revision']}).json()
    assert len(undo['segments'])==3

# 最后更新：2026-09-11 · Astra


def test_merging_stops_short_of_the_slicing_limit():
    """A merged run must stay readable as a subtitle, not just as speech.

    Merging up to the full 60-character slicing limit produced a 58-character
    cue held on screen for 12 seconds. The cap is two thirds of the limit.
    """
    from runtime.attribution import project_segments
    from evals.speaker_attribution.source_units import source_units
    source = ('门上贴着一张纸，写着“今日盘点，暂停营业”。'
              '林小雪把伞收起来，抖了抖水。她抬头看了看招牌，又低头核对手机上的地址。')
    labels = [{'id': u['id'], 'kind': 'narration', 'speaker': ''} for u in source_units(source)]
    segments = project_segments(source, labels, 'zh')
    assert all(len(s['text']) <= 40 for s in segments), [len(s['text']) for s in segments]
    assert ''.join(s['text'] for s in segments) == source

    # The stranded quoted fragment is still repaired.
    xue = '周远点点头。林小雪凑过去看那本子。上面一行字被水洇开了，只剩下半个“雪”字。'
    labels = [{'id': u['id'], 'kind': 'narration', 'speaker': ''} for u in source_units(xue)]
    merged = project_segments(xue, labels, 'zh')
    assert len(merged) == 1 and merged[0]['text'] == xue

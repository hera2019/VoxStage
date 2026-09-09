"""Scoring must not hide malformed answers, changed source, or alias errors. Astra 2026-09-09."""
import importlib.util,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'evals/speaker_attribution'))
spec=importlib.util.spec_from_file_location('attribution_eval',Path(__file__).resolve().parents[1]/'evals/speaker_attribution/evaluate.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
def case():
    return {'id':'x','language':'en','split':'heldout','tags':[],'text':'Sam said: "Hi."','aliases':{'Samuel':'Sam'},'gold':[{'text':'Sam said: ','kind':'narration','speaker':'NARRATOR'},{'text':'"Hi."','kind':'dialogue','speaker':'Sam'}]}
def test_exact_text_and_alias():
    c=case();parts=[{**p,'speaker':'Samuel' if p['speaker']=='Sam' else p['speaker']} for p in c['gold']]
    row=e.score(c,json.dumps({'segments':parts}));assert row['text_preserved'] and all(x['speaker_correct'] for x in row['units'])
def test_rewrite_or_invalid_not_removed_from_denominator():
    c=case();rows=[e.score(c,'no json'),e.score(c,json.dumps({'segments':[{'text':'Hi.','kind':'dialogue','speaker':'Sam'}]}))]
    s=e.summarize(rows);assert s['cases']==2 and s['known_dialogue_correct']==[0,2] and s['text_preserved']==0
def test_split_narration_equivalent_and_wrong_speaker_flagged():
    c=case();parts=[{'text':'Sam ','kind':'narration','speaker':'NARRATOR'},{'text':'said: ','kind':'narration','speaker':'NARRATOR'},{'text':'"Hi."','kind':'dialogue','speaker':'Pat'}]
    row=e.score(c,json.dumps({'segments':parts}));assert row['text_preserved'] and row['units'][0]['speaker_correct'] and not row['units'][1]['speaker_correct']
# 最后更新：2026-09-09 · Astra


def test_source_units_preserve_nested_quotes_whitespace_and_unclosed():
    from source_units import source_units
    for text in ['甲说：“他说‘明天’。”\n乙点头。','A said "hello".\n',"She can't go.",'“没有闭合','', 'a\\"b']:
        units=source_units(text);assert ''.join(x['text'] for x in units)==text
        assert all(text[x['start']:x['end']]==x['text'] for x in units)
    assert len(source_units('甲说：“他说‘明天’。”'))==2

def test_source_binding_rejects_missing_duplicate_unknown_and_preserves_order():
    import pytest
    from source_units import source_units,bind_labels
    text='Sam said: "Hi."';units=source_units(text);labels=[{'id':u['id'],'kind':'narration','speaker':'NARRATOR'} for u in units]
    bound=json.loads(bind_labels(text,json.dumps({'labels':list(reversed(labels))})));assert ''.join(p['text'] for p in bound['segments'])==text
    for bad in [labels[:-1],[labels[0]]*len(labels),[{**x,'id':'wrong'} for x in labels]]:
        with pytest.raises(ValueError):bind_labels(text,json.dumps({'labels':bad}))
# 最后更新：2026-09-09 · Astra

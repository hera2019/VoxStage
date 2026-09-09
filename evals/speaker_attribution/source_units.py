"""Split by generic quotation boundaries; never read a gold label. Astra 2026-09-09."""
import json
PAIRS={'“':'”','‘':'’','「':'」','『':'』','"':'"'}
def source_units(text):
    spans=[];start=0;close=None;escaped=False
    for i,char in enumerate(text):
        if escaped:escaped=False;continue
        if char=='\\':escaped=True;continue
        if close is None and char in PAIRS:
            if i>start:spans.append((start,i))
            start=i;close=PAIRS[char]
        elif close is not None and char==close:
            spans.append((start,i+1));start=i+1;close=None
    if start<len(text):spans.append((start,len(text)))
    return [{'id':f'u{i}','text':text[a:b],'start':a,'end':b} for i,(a,b) in enumerate(spans)]
def bind_labels(text,content):
    units=source_units(text);labels=json.loads(content)['labels']
    expected={u['id'] for u in units}
    if not isinstance(labels,list) or len(labels)!=len(units):raise ValueError('Missing or extra unit labels')
    if any(not isinstance(x,dict) or x.get('id') not in expected or x.get('kind') not in ('narration','dialogue') or not isinstance(x.get('speaker'),str) for x in labels):raise ValueError('Invalid unit label')
    by_id={x['id']:x for x in labels}
    if len(by_id)!=len(units):raise ValueError('Duplicate unit labels')
    return json.dumps({'segments':[{'text':u['text'],'kind':by_id[u['id']]['kind'],'speaker':by_id[u['id']]['speaker']} for u in units]},ensure_ascii=False)
# 最后更新：2026-09-09 · Astra

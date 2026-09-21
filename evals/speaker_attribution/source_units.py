"""Split by generic quotation boundaries; never read a gold label. Astra 2026-09-09."""
import json
PAIRS={'“':'”','‘':'’','「':'」','『':'』','"':'"'}
def source_units(text,cut=None):
    # A text with no quotation marks at all — one line per utterance, as a
    # coloured or marked manuscript is written — is cut at line breaks
    # instead, each line a unit (Claude Hera 2026-09-16); a quoted text keeps
    # the boundaries below, so nothing already labelled moves. cut='lines'
    # asks for line cutting whatever the text holds: a coloured manuscript
    # whose colours, not its quotation marks, say who speaks (本人 2026-09-17,
    # a document with one quoted paragraph among sixty-eight coloured lines —
    # the two stretches around the quote were each one unit, and no colour
    # could reach inside them).
    if cut=='lines' or (not any(c in text for c in PAIRS) and not any(c in text for c in PAIRS.values())):
        spans=[];start=0
        for i,char in enumerate(text):
            if char=='\n':
                if i>start:spans.append((start,i))
                spans.append((i,i+1));start=i+1
        if start<len(text):spans.append((start,len(text)))
        return [{'id':f'u{i}','text':text[a:b],'start':a,'end':b} for i,(a,b) in enumerate(spans)]
    # A quote inside a quote — 叫道：“阿Q！同去同去！” inside a thought Lu Xun
    # sets in the same double marks — is part of the outer unit: depth is
    # counted, and the unit ends when it returns to zero. A line break inside
    # an open quote ends it (an unclosed mark must not swallow the chapter:
    # 2026-09-22, a novel with single line breaks and one stray mark came out
    # as a 756,000-character unit; a speech over several paragraphs opens each
    # with its own mark anyway, and the rules join them). Claude Hera
    # 2026-09-16, 阿Q chapter 7; 2026-09-22 any line break, not only a blank line.
    spans=[];start=0;close=None;depth=0;escaped=False
    for i,char in enumerate(text):
        if escaped:escaped=False;continue
        if char=='\\':escaped=True;continue
        if close is None and char in PAIRS:
            if i>start:spans.append((start,i))
            start=i;close=PAIRS[char];depth=1;opener=char
        elif close is not None:
            if char==opener and opener!=close:
                depth+=1
            elif char==close:
                depth-=1
                if depth==0:
                    spans.append((start,i+1));start=i+1;close=None
            elif char=='\n':
                spans.append((start,i));start=i;close=None;depth=0
    if start<len(text):spans.append((start,len(text)))
    return [{'id':f'u{i}','text':text[a:b],'start':a,'end':b} for i,(a,b) in enumerate(spans)]
def bind_labels(text,content,cut=None):
    units=source_units(text,cut);labels=json.loads(content)['labels']
    expected={u['id'] for u in units}
    if not isinstance(labels,list) or len(labels)!=len(units):raise ValueError('Missing or extra unit labels')
    if any(not isinstance(x,dict) or x.get('id') not in expected or x.get('kind') not in ('narration','dialogue') or not isinstance(x.get('speaker'),str) for x in labels):raise ValueError('Invalid unit label')
    by_id={x['id']:x for x in labels}
    if len(by_id)!=len(units):raise ValueError('Duplicate unit labels')
    return json.dumps({'segments':[{'text':u['text'],'kind':by_id[u['id']]['kind'],'speaker':by_id[u['id']]['speaker']} for u in units]},ensure_ascii=False)
# 最后更新：2026-09-09 · Astra ／ 2026-09-16 · Claude Hera（无引号文本按行切）／ 2026-09-17 · Claude Hera（cut='lines'）／ 2026-09-22 · Claude Hera（引号到换行为止）

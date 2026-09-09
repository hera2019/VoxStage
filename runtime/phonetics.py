"""Auditable Chinese homophone tolerance, not acoustic pronunciation truth. Astra, 2026-09-09."""
from pypinyin import Style, lazy_pinyin

# Bounded exceptions to the grammatical de equivalence. This is intentionally
# conservative for common lexical readings; it is not a complete syntax parser.
PROTECTED_WORDS = (
    '土地','大地','地面','地下','地上','地球','地理','地区','地方','地位','地点','地图',
    '地震','地铁','地板','地狱','地址','基地','当地','本地','外地','内地','天地',
    '目的','的确','的士','得意','得到','获得','取得','所得','值得','难得','记得','觉得',
    '得分','得奖','得胜','得失','得罪','不得','得以','得出','得知','得力','得病',
    '得走','得去','得来','得回','得做','得吃','得说','得等','得先','得要','得赶',
)


def chinese_keys(units):
    text=''.join(units)
    pronunciations=lazy_pinyin(text,style=Style.TONE3,neutral_tone_with_five=True,
                              errors=lambda value:list(value))
    if len(pronunciations)!=len(units):
        return [('literal',unit) for unit in units]
    protected=set()
    for word in PROTECTED_WORDS:
        start=text.find(word)
        while start!=-1:
            protected.update(i for i in range(start,start+len(word)) if text[i] in '的地得')
            start=text.find(word,start+1)
    keys=[]
    for i,(unit,reading) in enumerate(zip(units,pronunciations)):
        if unit in '的地得' and i not in protected:
            keys.append(('grammatical-de','de'))
        elif '\u3400'<=unit<='\u9fff' and reading!=unit:
            keys.append(('pinyin',reading))
        else:
            keys.append(('literal',unit))
    return keys

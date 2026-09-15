"""Who talks like this? A suggestion for an unresolved line from the way each
character has spoken in lines a person already confirmed — the same book's
other chapters. Catchphrases, particles, the wave dash, a form of address:
character unigrams and bigrams, compared by cosine. A character named in the
line is not its speaker (people do not address themselves).

Measured 2026-09-14 on a private two-chapter text of the author's: trained
on chapter one's 31 confirmed lines, tested on chapter two's 35 — top guess
right 24/35 (69%, majority class 49%); with a margin of at least 0.05 between
the best and the second candidate, 17/21 (81%) and 14 lines left alone. Small numbers, so the
guess is only ever a yellow pre-fill the reviewer can overwrite, never a
decision, and below the margin it is a hint in the placeholder.
"""
import math
import re
from collections import Counter, defaultdict

MARGIN = 0.05
STRIP = re.compile(r'[\s“”"「」『』]')


def grams(text):
    text = STRIP.sub('', text)
    counts = Counter(text)
    counts.update(text[i:i + 2] for i in range(len(text) - 1))
    return counts


def profiles(lines):
    """lines: iterable of (text, speaker) confirmed by a person -> speaker -> gram counts."""
    out = defaultdict(Counter)
    for text, speaker in lines:
        out[speaker].update(grams(text))
    return out


def _cos(a, b):
    num = sum(v * b.get(k, 0) for k, v in a.items())
    da = math.sqrt(sum(v * v for v in a.values())); db = math.sqrt(sum(v * v for v in b.values()))
    return num / (da * db) if da and db else 0.0


_VOCATIVE_AFTER = '～~，,！!、：:？?。'


def addressed(text, name):
    """Is the character spoken to by name in the line — 老板娘～, 小雪，你…?
    The name must stand as a call: at the start or after punctuation, and
    followed by a pause mark or the end. A bare mention inside a phrase
    (给娘看看, 娘的话) is not an address: a character may call herself 娘."""
    if not name:
        return False
    clean = STRIP.sub('', text)
    i = clean.find(name)
    while i >= 0:
        before = clean[i - 1] if i > 0 else ''
        after = clean[i + len(name)] if i + len(name) < len(clean) else ''
        if (before == '' or before in _VOCATIVE_AFTER) and (after == '' or after in _VOCATIVE_AFTER):
            return True
        i = clean.find(name, i + 1)
    return False


SPEECH_VERBS = ('说道', '笑道', '叫道', '喊道', '骂道', '问道', '答道', '回道', '低声道', '轻声道', '嚷道', '吼道', '哼道',
                '说', '道', '问', '答', '叫', '喊', '骂', '回', '嚷', '吼', '哼', '应', '继续', '接着', '开口', '插嘴', '补充')


# A name right after one of these is the person spoken to, looked at or taken
# hold of, not the speaker: 对我说道, 见了我，又说道, 望着小雪说. (Kong Yiji,
# 2026-09-16: 有一回对我说道 gave the line to 我.)
_OBJECT_MARKS = '对向跟朝冲同和与替给见问着住到把了望瞧盯找拉扶推指叫喊'


_VERB_RE = re.compile('|'.join(sorted(SPEECH_VERBS, key=len, reverse=True)))
_CLAUSE_MARKS = '，、；：,;:'
_OTHER_SUBJECTS = ('他', '她', '它', '我', '你', '您', '大家', '众人', '有的', '有人', '旁人', '别人', '那人', '此人', '一人', '一个', '几个', '那个', '这个', '对方')


def _subject_with_verb(sentence, mentions):
    """The one character who opens a clause of `sentence` and is followed, in
    the sentence's last clause, by a speech verb — with no other character,
    pronoun or 有的/旁人 opening a clause in between. None otherwise."""
    sentence = sentence.rstrip(_CLAUSE_MARKS)
    if not sentence or len(sentence) > 60:
        return None
    clauses = re.split('[' + re.escape(_CLAUSE_MARKS) + ']', sentence)
    last = clauses[-1] if clauses else ''
    verb = _VERB_RE.search(last)
    if not verb:
        return None
    verb_at = len(sentence) - len(last) + verb.start()
    if any(w in last[:verb.start()] for w in ('要', '想', '没', '不', '未', '才', '刚')):   # 刚要开口: did not get to
        return None
    found = []
    for name, forms in mentions.items():
        for f in forms:
            for m in re.finditer(re.escape(f), sentence):
                i = m.start()
                if i > 0 and sentence[i - 1] not in _CLAUSE_MARKS:          # not at a clause start
                    continue
                if i > 0 and sentence[i - 1] in _OBJECT_MARKS:
                    continue
                if m.end() > verb_at:
                    continue
                between = sentence[m.end():verb_at]
                # Another character between name and verb competes only as a
                # subject (opening a clause); as an object (望着老板娘说) it does not.
                if any(k == 0 or between[k - 1] in _CLAUSE_MARKS for n2, fs in mentions.items() if n2 != name
                       for g in fs for k in [between.find(g)] if k >= 0):
                    continue
                if any(c.startswith(_OTHER_SUBJECTS) for c in re.split('[' + re.escape(_CLAUSE_MARKS) + ']', between)[1:]):
                    continue
                found.append(name)
                break
    found = list(dict.fromkeys(found))
    return found[0] if len(found) == 1 else None


def opening_tag(before, mentions):
    """The name the narration before a line introduces it with — 小雪笑道：,
    掌柜也伸出头去，一面说：, 孔乙己便涨红了脸，额上的青筋条条绽出，争辩道： —
    or None. A narration whose last sentence is closed (吴迪嚷起来。) and then
    breaks the paragraph closes the line before it and introduces nothing
    (measured 2026-09-16: six of the old rule's wrong answers were closing
    tags read as opening ones); closed but in the same paragraph — 一面说。“…”
    — it still introduces the line."""
    raw = (before or '')
    clean = STRIP.sub('', raw)
    if not clean:
        return None
    if clean[-1] in '。！？!?':
        last_mark = max(raw.rfind(c) for c in '。！？!?')
        if '\n' in raw[last_mark + 1:]:            # closed, then a paragraph break: it closed the line before
            return None
    return _subject_with_verb(re.split(r'[。！？!?]', clean.rstrip('。！？!?'))[-1], mentions)


def closing_tag(after, mentions):
    """The name the narration after a line closes it with — ”小雪说。, ”赵太爷
    踱开去，眼睛打量着他的全身，一面说。 — or None. The name opens the first
    sentence, which must not itself introduce the next line (小雪说：)."""
    clean = STRIP.sub('', after or '')
    if not clean or clean.rstrip('。！？!?').endswith(('：', ':', '，', ',')):
        return None
    first = re.split(r'[。！？!?]', clean)[0]
    if len(first) > 40:
        return None
    head = re.split('[' + re.escape(_CLAUSE_MARKS) + ']', first)[0]
    if not any(head.startswith(f) or (0 < head.find(f) <= 2) for forms in mentions.values() for f in forms):
        return None
    return _subject_with_verb(first, mentions)

def comma_beat(after, mentions):
    """The one character a beat joined to the quote by a comma is about —
    ”，赵太爷却不甚热心了。 — without a speech verb (with one it is a closing
    tag, handled by speech_tag). None otherwise."""
    clean = STRIP.sub('', after or '')
    if not clean.startswith(('，', ',')):
        return None
    first = re.split(r'[。！？!?\n]', clean[1:])[0]
    if not first or len(first) > 30 or _VERB_RE.search(first):
        return None
    found = []
    for name, forms in mentions.items():
        for f in forms:
            k = first.find(f)
            if k >= 0 and not (k > 0 and first[k - 1] in _OBJECT_MARKS):
                found.append(name); break
    return found[0] if len(found) == 1 else None


def speech_tag(before, after, mentions):
    """The name a speech tag beside a line gives it, or None: an opening tag in
    the narration before it, or a closing tag in the narration after it;
    exactly one character must fit."""
    found = {n for n in (opening_tag(before, mentions), closing_tag(after, mentions)) if n}
    return next(iter(found)) if len(found) == 1 else None


# A speech tag whose subject is nobody in particular. The story never names
# these speakers, so no model can, and the reviewer was left to pick a name for
# each line by hand (Kong Yiji, 2026-09-16: ten crowd lines — 有的叫道, 旁人便又
#问道, 他们便接着说道, 一个喝酒的人说道 — all left orange). The line gets a
# stand-in name instead, yellow: 众人 for a group, 某人 for one unnamed person.
# Renaming the stand-in once on the review page carries every line along.
_VERB_ALT = '|'.join(sorted(SPEECH_VERBS, key=len, reverse=True))
_GROUP = (r'(?:有的人?|旁人|他们|她们|众人|人们|大家伙?儿?|别人|别的人|其他人|其余的人|旁边的人|周围的人|那些人|这些人|一些人|'
          r'几个人|一群[^，。！？：；、]{0,4}?|大伙儿?|看客们?|人群|所有[^，。！？：；、]{0,6}?人|有几个人?)')
_ONE = (r'(?:有人|有个人|有一个人|某人|那人|那个人|这人|一个人|一人|不知是?谁|有谁|一个声音|有个声音|'
        r'一个[^，。！？：；、]{1,6}?(?:人|声音)|一位[^，。！？：；、]{1,4}?)')
_ANON_TAG = re.compile(r'(?:^|[，。！？：；、])(?:(?P<group>' + _GROUP + r')|(?P<one>' + _ONE + r'))[^，。！？：；、]{0,8}?(?:' + _VERB_ALT + r')[：:，,]?$')
_ANON_HEAD = re.compile(r'^(?:(?P<group>' + _GROUP + r')|(?P<one>' + _ONE + r'))[^，。！？：；、]{0,8}?(?:' + _VERB_ALT + ')')
_VOICE = re.compile(r'(?:听得|听见|听到|传来|响起|飘来)[^，。！？：；、]{0,6}?(?:声音|声)[：:，,]?$')
STAND_INS = {'group': '众人', 'one': '某人'}


def anonymous_tag(before, after='', with_phrase=False):
    """The stand-in name for a line whose tag names nobody in particular —
    '众人' (有的叫道, 旁人便又问道, 他们嚷道) or '某人' (有人说, 一个喝酒的人说道,
    忽然听得一个声音) — or None. With `with_phrase`, (name, phrase): the words
    the narration used, so two strangers in one exchange (有人 and 一个喝酒的人)
    are told apart (Astra 2026-09-16)."""
    def answer(kind, phrase):
        return (STAND_INS[kind], phrase) if with_phrase else STAND_INS[kind]
    tail = STRIP.sub('', before or '')[-24:]
    m = _ANON_TAG.search(tail)
    if m:
        return answer('group' if m.group('group') else 'one', m.group('group') or m.group('one'))
    v = _VOICE.search(tail)
    if v:
        return answer('one', '声音')
    head = STRIP.sub('', after or '')
    if head and not head.rstrip('。！？!?').endswith(('：', ':', '，', ',')):    # a closing tag, not one introducing the next line
        m = _ANON_HEAD.match(head[:20])
        if m:
            return answer('group' if m.group('group') else 'one', m.group('group') or m.group('one'))
    return None


PRONOUNS = {'他', '她', '它', '我', '你', '您', '他们', '她们', '我们', '你们', '大家', '众人', '有人', '那人', '此人', '一人', '男人', '女人',
            '那个', '这个', '对方', '那位', '这位', '两人', '几人', '一个'}
_TAG_TAIL = re.compile(r'(?:^|[，。！？：；、])([^，。！？：；、“”"\s]{1,4}?)(' + '|'.join(sorted(SPEECH_VERBS, key=len, reverse=True)) + r')[：:，,]?$')


FUNCTION_STARTS = ('又', '便', '就', '才', '也', '都', '却', '忙', '正', '只', '还', '再', '一', '有的', '有人', '别人', '旁人', '对', '向', '朝', '跟', '和',
                   '于是', '然后', '接着', '连忙', '点头', '摇头', '笑着', '哭着', '低声', '大声', '高声', '轻声', '冷冷', '慢慢')


def names_from_tags(narrations, whole_text=''):
    """Names the speech tags themselves reveal — 小雪说： — so a text with no
    earlier chapters still has a cast. A candidate must look like a name:
    two to four characters, not a pronoun or a manner word (又说, 点头说,
    有的叫道 are not people), and — since a character recurs — found at
    least three times in a long text (a short passage cannot be asked that)."""
    out = []
    for text in narrations:
        m = _TAG_TAIL.search(STRIP.sub('', text or ''))
        if not m:
            continue
        name = m.group(1)
        # 阿宁又说 / 陈小雪便道: the adverb between the name and the verb is not part of the name.
        while len(name) >= 3 and name[-1] in '又便就也都才却忙再还正只先':
            name = name[:-1]
        if len(name) < 2 or name in SPEECH_VERBS or any(v in name for v in ('说', '道', '问', '答')):
            continue
        if name in PRONOUNS or any(name.startswith(pro) and len(name) - len(pro) <= 1 for pro in PRONOUNS):
            continue
        if any(name.startswith(w) for w in FUNCTION_STARTS):
            continue
        if whole_text and len(whole_text) >= 1500 and whole_text.count(name) < 3:
            continue
        if name not in out:
            out.append(name)
    return out


SEX_MARGIN = 0.03


def sex_profiles(lines):
    """lines: (text, sex) with sex 'f' or 'm' -> {'f': grams, 'm': grams}. Measured
    2026-09-15 on the author's book, chapter one → two: at a margin of 0.03 the
    line's sex was read right 27 of 28 times, 7 lines undecided."""
    out = {'f': Counter(), 'm': Counter()}
    for text, sex in lines:
        if sex in out:
            out[sex].update(grams(text))
    return out


def sex_of_line(text, profiles):
    """('f' | 'm' | None, margin): which sex's lines this one resembles, when clearly."""
    if not profiles or not profiles.get('f') or not profiles.get('m'):
        return None, 0.0
    g = grams(text)
    f, m = _cos(g, profiles['f']), _cos(g, profiles['m'])
    if abs(f - m) < SEX_MARGIN:
        return None, abs(f - m)
    return ('f' if f > m else 'm'), abs(f - m)


def rank(text, profile):
    """Every candidate with its score, best first — for choosing among the rest
    once some are ruled out."""
    g = grams(text)
    return sorted(((sp, _cos(g, pr)) for sp, pr in profile.items()), key=lambda kv: -kv[1])


def mentioned(text, name):
    """A character a line speaks of or to is not its speaker. A full name
    counts wherever it stands (你去问老板娘 is not 老板娘's line); a
    one-character form such as 娘 counts only as a call, since a character
    may call herself 娘."""
    if not name:
        return False
    return name in STRIP.sub('', text) if len(name) >= 2 else addressed(text, name)


_SELF = r'(?:我|本人|在下|小人|小的|鄙人|老子|老娘|奴家|俺|吾|咱)'
_COPULA = r'(?:叫|是|就是|便是|乃是|乃|名叫|姓|，?名)'


def self_introduced(text, name):
    """我叫张三 / 我是张三 / 我张三又回来了: the line's speaker names himself —
    the pronoun opens the clause and the name follows it directly or through
    是/叫/就是. 我带张三一起去 does not (本人 2026-09-16: think of the many
    forms; a verb between the two makes the name someone else). A mention,
    but the opposite evidence from a call (Astra 2026-09-15)."""
    if not name:
        return False
    clean = STRIP.sub('', text)
    return re.search(r'(?:^|[，。！？；：、])' + _SELF + _COPULA + '?' + re.escape(name) + r'(?!们)', clean) is not None


def romanized(name):
    """The pinyin readings a Chinese name can have, one set per character —
    to match a name a model wrote in letters (ZHANG XIAO WEI) to the name in
    the text (张小伟)."""
    from pypinyin import pinyin, Style
    return [{r.replace('ü', 'v') for r in readings} | {r.replace('ü', 'u') for r in readings}
            for readings in pinyin(name, style=Style.NORMAL, heteronym=True)]


def same_name_in_letters(latin, name):
    """Does a name written in letters spell this Chinese name — in full, or its
    given name (XIAO WEI for 张小伟)? Case, spaces, dots and hyphens ignored."""
    letters = re.sub(r'[^a-z]', '', (latin or '').lower().replace('ü', 'v').replace('u:', 'v'))
    if not letters or not name:
        return False
    for start in (0, 1) if len(name) >= 3 else (0,):
        parts = romanized(name[start:])
        def fits(i, rest):
            if i == len(parts):
                return rest == ''
            return any(rest.startswith(r) and fits(i + 1, rest[len(r):]) for r in parts[i])
        if fits(0, letters):
            return True
    return False


def name_in_letters_for(latin, candidates, text=''):
    """The one candidate the lettered name spells — or, failing the candidates,
    the one run of two or more characters in the text that spells it (the
    model names 张小伟 as ZHANG XIAO WEI though no tag ever says 张小伟说). None
    when nothing or several things do."""
    hits = [c for c in candidates if same_name_in_letters(latin, c)]
    if len(hits) == 1:
        return hits[0]
    if hits or not text:
        return None
    letters = re.sub(r'[^a-z]', '', (latin or '').lower().replace('ü', 'v').replace('u:', 'v'))
    if len(letters) < 2:
        return None
    from pypinyin import pinyin, Style
    chars = [ch for ch in text if '一' <= ch <= '鿿']
    readings = {}
    for ch in set(chars):
        rs = pinyin(ch, style=Style.NORMAL, heteronym=True)[0]
        readings[ch] = {r.replace('ü', 'v') for r in rs} | {r.replace('ü', 'u') for r in rs}
    found = set()
    clean = STRIP.sub('', text)
    for start in range(len(clean)):
        i, rest = start, letters
        while rest and i < len(clean) and clean[i] in readings:
            r = next((r for r in readings[clean[i]] if rest.startswith(r)), None)
            if r is None:
                break
            rest = rest[len(r):]; i += 1
        if not rest and i - start >= 2:
            found.add(clean[start:i])
    return next(iter(found)) if len(found) == 1 else None


# Where one exchange ends and another begins: narration long enough to carry
# the reader elsewhere, or that opens with a change of time or place. A short
# beat between two lines (他笑了笑。/ 阿宁说：) keeps the exchange going.
# Astra 2026-09-15: turn-taking must not relay across scenes.
SCENE_CUT_LENGTH = 30
_SCENE_START = re.compile(r'(?:^|[。！？；\n])\s*(?:第二天|第三天|次日|翌日|隔天|这天|那天|那晚|当晚|夜里|深夜|半夜|清晨|早上|中午|下午|傍晚|晚上|后来|过了|从此|此后|自此|一个月|几天|几年|多年|回到|到了|来到|走进|出了|离开|另一|换了)')


def scene_cut(narration):
    """Does this stretch of narration between two lines end the exchange?"""
    clean = STRIP.sub('', narration or '')
    if len(clean) >= SCENE_CUT_LENGTH:
        return True
    return _SCENE_START.search(narration or '') is not None


def suggest(text, profile):
    """(best speaker, margin) for a line, or (None, 0) when there is nothing to
    compare with. Characters the line calls by name are excluded (老板娘～ is
    not the 老板娘's line); a bare mention is not (我叫陈小雪 is 陈小雪's)."""
    candidates = {sp: _cos(grams(text), pr) for sp, pr in profile.items() if not addressed(text, sp)}
    if not candidates:
        return None, 0.0
    ranked = sorted(candidates.items(), key=lambda kv: -kv[1])
    best, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return best, score - second


# 最后更新：2026-09-16 · Claude Hera（对话块、自报家门、称呼与提及分开——按 Astra 2026-09-15 审阅）

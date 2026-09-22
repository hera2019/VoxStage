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
                '想道', '心想', '暗想', '心里想', '寻思', '念道', '自言自语',          # a thought in quotation marks is read in its thinker's voice (阿Q 想：)
                '说', '道', '问', '答', '叫', '喊', '骂', '回', '嚷', '吼', '哼', '应', '继续', '接着', '开口', '插嘴', '补充')
# Bare 想 counts only right before the quote (阿Q想：), never as 想要 / 想了想.
# 道 inside 知道 / 难道 / 味道 / 街道 is not "said"; bare 想 counts only right before the quote.
_VERB_ALT_ALL = '|'.join('(?<![知难味街大])道' if v == '道' else re.escape(v) for v in sorted(SPEECH_VERBS, key=len, reverse=True)) + '|想(?=[：:，,]|$)'


# A name right after one of these is the person spoken to, looked at or taken
# hold of, not the speaker: 对我说道, 见了我，又说道, 望着小雪说. (Kong Yiji,
# 2026-09-16: 有一回对我说道 gave the line to 我.)
_OBJECT_MARKS = '对向跟朝冲同和与替给见问着住到把了望瞧盯找拉扶推指叫喊'


_VERB_RE = re.compile(_VERB_ALT_ALL)
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
                if sentence[m.end():].startswith('们'):
                    continue                    # the group is not the single named person
                if any(len(g) > len(f) and g.startswith(f) and sentence.startswith(g, i)
                       for fs in mentions.values() for g in fs):
                    continue                    # a shorter name inside another name
                if i > 0 and sentence[i - 1] not in _CLAUSE_MARKS:          # not at a clause start
                    continue
                if i > 0 and sentence[i - 1] in _OBJECT_MARKS:
                    continue
                if m.end() > verb_at:
                    continue
                between = sentence[m.end():verb_at]
                # A perception can introduce another actor; an unnamed noun
                # phrase can be a new subject too. The distant named subject
                # is not enough evidence to overwrite the model's answer.
                if re.search(r'看见|见到|发现|听见|听得|听到', between):
                    continue
                if re.search(r'(?:^|[，、；])[^，。！？；：、]{1,12}的人', between):
                    continue
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


_PRONOUN_SUBJECT = re.compile(r'(?:^|[，。！？；：、,])(他|她)(?:又|便|就|也|才|却|忙|正|只|还|再|先|于是|然后|接着|连忙)?[^，。！？；：、]{0,8}?(?:' + _VERB_ALT_ALL + r')[：:，,]?$')


def pronoun_tag(before, mentions=None):
    """'他' or '她' when the narration before a line introduces it with a pronoun
    as the subject — 他想：, 她笑着说： — else None. Who the pronoun is falls to
    the exchange: the most recent character of that sex named in it."""
    raw = before or ''
    clean = STRIP.sub('', raw)
    if not clean:
        return None
    if clean[-1] in '。！？!?':
        last_mark = max(raw.rfind(c) for c in '。！？!?')
        if '\n' in raw[last_mark + 1:]:
            return None
    sentence = re.split(r'[。！？!?]', clean.rstrip('。！？!?'))[-1]
    m = _PRONOUN_SUBJECT.search(sentence[-30:])
    if m:
        return m.group(1)
    # The pronoun that opened the sentence carries to the verb in its last
    # clause when nothing else takes the subject in between — 他脸上黑而且瘦，
    # 已经不成样子；穿一件破夹袄，……见了我，又说道， (孔乙己, 2026-09-17).
    clauses = re.split('[' + re.escape(_CLAUSE_MARKS) + ']', sentence.rstrip(_CLAUSE_MARKS))
    if len(clauses) < 2 or len(clauses) > 8 or len(sentence) > 80:
        return None
    last = clauses[-1]
    verb = _VERB_RE.search(last)
    if not verb or any(w in last[:verb.start()] for w in ('要', '想', '没', '不', '未', '才', '刚')):
        return None
    for c in reversed(clauses[:-1]):
        m = re.match(r'(?:但|而|可|却|于是|然后|接着|只|便)?(他|她)(?!们)', c)
        if m:
            return m.group(1)
        if c.startswith(_OTHER_SUBJECTS) or any(f and c.startswith(f) for forms in (mentions or {}).values() for f in forms):
            return None
    return None


_PRONOUN_CLOSING = re.compile(r'^[，,]?(他|她)(?:又|便|就|也|才|却|忙|正|只|还|再|先|于是|然后|接着|连忙)?[^，。！？；：、]{0,8}?(?:' + _VERB_ALT_ALL + r')')


def pronoun_closing(after):
    """'他' or '她' when the narration right after a line closes it with a pronoun
    as the subject — ”他想：, ”她笑着说。 — else None. Between two quotes such a
    tag serves both: “A”他说：“B” are one person's."""
    clean = STRIP.sub('', after or '')
    m = _PRONOUN_CLOSING.match(clean[:24])
    return m.group(1) if m else None


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
    """A completed attribution after the quote, in the same paragraph.

    An unfinished tag (阿宁点头，说道) may introduce the next quote;
    a tag in a new paragraph belongs to that paragraph, not this quote.
    """
    raw = (after or '').lstrip(' \t”"」』')
    if raw.startswith(('\n', '\r')):
        return None
    clean = STRIP.sub('', raw)
    if clean.rstrip('。！？!?').endswith(('：', ':', '，', ',')):
        # “A”，阿Q想，“B” — a tag joined by commas to the quote before and the
        # quote after is both lines' (阿Q chapter 7, 2026-09-17).
        if clean.startswith(('，', ',')) and clean.endswith(('，', ',')) and len(clean) <= 20 and not re.search(r'[。！？!?：:]', clean):
            return _subject_with_verb(clean.strip('，,'), mentions)
        return None
    end = re.search(r'[。！？!?]', clean)
    if not end:
        return None
    first = clean[:end.start()]
    if len(first) > 40 or '：' in first or ':' in first or first.endswith(('，', ',')):
        return None
    head = re.split('[' + re.escape(_CLAUSE_MARKS) + ']', first)[0]
    if not any(head.startswith(f) or (0 < head.find(f) <= 2) for forms in mentions.values() for f in forms):
        return None
    return _subject_with_verb(first, mentions)


def colon_lead(before, mentions):
    """The character (a name from `mentions`, or 他/她) whose clause ends the
    narration with a colon and no verb of saying — 阿Q的思想也迸跳起来了：——,
    他的意思是： — introducing the quote; None otherwise. Weaker than a tag
    (no verb), so the caller keeps it yellow."""
    clean = STRIP.sub('', before or '').rstrip('—-')
    if clean.endswith(('，', ',')):
        # A clause left open before the quote — 赵太爷却又没有话，“现在……
        # 发财么？” — when it is the whole of the narration: its subject speaks.
        if len(clean) > 30 or re.search(r'[。！？!?：:；;]', clean) or clean.startswith(('，', ',')):
            return None
        last = re.split('[' + re.escape(_CLAUSE_MARKS) + ']', clean.rstrip('，,'))[0]
    elif clean.endswith(('：', ':')):
        sentence = re.split(r'[。！？!?]', clean.rstrip('：:'))[-1]
        if not sentence or len(sentence) > 40:
            return None
        last = re.split('[' + re.escape(_CLAUSE_MARKS) + ']', sentence)[-1]
    else:
        return None
    for name, forms in mentions.items():
        for f in forms:
            if last.startswith(f) and not last.startswith(f + '们'):
                return name
    m = re.match(r'(他|她)(?!们)', last)
    return m.group(1) if m else None


def outer_speech(text):
    """A line with its inner quotations cut out: in 阿Q's fantasy — 叫道：“阿Q！
    同去同去！” — the name called is called by the people he imagines, not by
    whoever hears his line (阿Q chapter 7, 2026-09-17). Only the outer line
    says who it is addressed to."""
    t = (text or '').strip()
    if len(t) >= 2 and t[0] in '“"「『':
        inner = t[1:-1] if t[-1] in '”"」』' else t[1:]
        return t[0] + re.sub(r'[“「『][^“”「」『』]*[”」』]', '', inner) + (t[-1] if t[-1] in '”"」』' else '')
    return t


# A verb of saying that ends its clause (争辩道：, 说，); 收回袖中 is not one.
_TAG_VERB = re.compile(r'(?:' + _VERB_ALT_ALL + r')(?=[：:，,。！？!?]|$)')


def action_after(after, mentions):
    """The character whose action follows the quote in the same paragraph
    without a verb of saying — “是。”陈小雪将账本重新收回袖中 — or None.
    Textual, but weaker than a tag: the caller only confirms an answer that
    agrees with it, or suggests it where the line is empty."""
    raw = (after or '').lstrip(' \t”"」』')
    if not raw or raw[0] in '\n\r，,':
        return None
    clean = STRIP.sub('', raw)
    first = re.split(r'[。！？!?；;\n]', clean)[0]
    head = re.split('[' + re.escape(_CLAUSE_MARKS) + ']', first)[0]
    # A sentence that leads into the next line — 孔乙己便涨红了脸，……争辩道：
    # — is that line's tag, not this line's action.
    if not head or len(head) > 30 or _TAG_VERB.search(first) or clean[len(first):len(first) + 1] in ('：', ':'):
        return None
    found = []
    for name, forms in mentions.items():
        for f in forms:
            if head.startswith(f) and not head.startswith(f + '们') and len(head) > len(f):
                if any(len(g) > len(f) and head.startswith(g) for fs in mentions.values() for g in fs):
                    continue                    # a shorter name inside a longer one (王伯 in 王伯母)
                found.append(name); break
    found = list(dict.fromkeys(found))
    return found[0] if len(found) == 1 else None


def run_on(text):
    """A quoted unit opened but not closed — the first paragraph of a speech
    that runs over several, each opened with “ and closed only at the last."""
    t = (text or '').strip()
    return len(t) >= 2 and t[0] in '“"「『' and t[-1] not in '”"」』'


def quoted_citation(text, before='', after=''):
    """Chinese quoted words need a citation cue; brevity alone is not one.

    These narrow forms identify a written label, a term, or a retrospective
    reference. Ambiguous short quotes keep their model classification.
    """
    text = text.strip()
    if len(text) < 2 or text[0] not in '“"「『' or text[-1] not in '”"」』':
        return False
    inner = text[1:-1]
    # An ellipsis counts as a sentence: the reviewer read 他那“女……”的思想
    # in 阿Q's voice (chapter 4) — a fragment of thought, not a term.
    if not inner or any(c in inner for c in '。！？…；!?～~，、—'):
        return False
    left = before.rstrip()[-60:]
    right = after.lstrip()
    if re.match(r'(?:这|那)(?:句)?话(?:以后|之后|以前|之前|后|前)', right):
        return True
    if re.search(r'(?:什么|所谓|写着|写的是|写有|印着|挂着|标着|题着|叫做|称为|纸上的|书上的|牌上的)$', left):
        return True
    if re.match(r'(?:这个字|这个词|一词|二字|两字|几个字|之类|字[。，；])', right):
        return True
    if len(inner) <= 10 and re.search(r'(?:骂[^，。！？；]{0,16}是|(?:叫|称|唤)(?:他|她|它|我|他们|她们)(?:作|做|为)?)$', left):
        return True
    # A quote the sentence runs straight on from — 几乎“魂飞魄散”了, “行状”上的
    # 一个污点, 还是“手执钢鞭将你打”罢, “无师自通”的说出 — sits inside the
    # narrator's own clause: recited, not spoken (阿Q chapter 9, 2026-09-16).
    # Speech is followed by punctuation, a line break, or a tag (”他说).
    if len(inner) <= 12 and re.match(r'(?:的|地|了|上|里|中|之|也|罢|吧|是|来|去|着|过|似的|一般|般|两字|二字|三字|四字|话|者|字|词|之说|之类|云云|等等)', right):
        return True
    # ...and the clause that leads into it: 也就立刻是“小鬼见阎王”, 秀才听了这
    # “庭训”, 村人对于阿Q的“敬而远之”者, 还记得“忘八蛋” (阿Q chapters 4 and
    # 6, 2026-09-17; on the eleven reviewed texts these cues met no line a
    # person called speech). A verb of saying before the quote is not here.
    if len(inner) <= 12 and re.search(r'(?:是|这|那|的|记得|想起|记起|所谓|谓|即)$', left):
        return True
    # 本人 2026-09-22: a quoted word or two with nothing else in it, set inside
    # the narrator's own line — 觉得很“过瘾”, 俗称为“白喉”的疫情 — is a term
    # cited, not a line spoken, unless a verb of saying or a colon leads into
    # it (说了一声“好”, 道：“好”), a tag follows it (”他说), or the quote opens
    # its line (“老Q”，赵太爷怯怯的迎着低声的叫 — 阿Q chapter 7). The reviewer
    # can still make it a line; as narration it joins the prose around it.
    if len(inner) <= 4:
        line_before = (before or '').rsplit('\n', 1)[-1]
        line_after = (after or '').split('\n', 1)[0]
        embedded = bool(line_before.strip())        # prose before it on its line; a quote opening the line (“老Q”，赵太爷…叫) is a line spoken
        led_by_speech = bool(re.search(r'(?:' + _VERB_ALT_ALL + r')[^，。！？；]{0,4}[：:]?$|[：:]$', line_before.rstrip()[-12:]))
        tag_after = bool(re.match(r'\s*[，,]?\s*[^，。！？!?\s]{0,6}(?:' + _VERB_ALT_ALL + r')', line_after[:14]))
        if embedded and not led_by_speech and not tag_after:
            return True
    return False


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
_VERB_ALT = _VERB_ALT_ALL
_GROUP = (r'(?:有的人?|旁人|他们|她们|众人|人们|大家伙?儿?|别人|别的人|其他人|其余的人|旁边的人|周围的人|那些人|这些人|一些人|'
          r'几个人|一群[^，。！？：；、]{0,4}?|大伙儿?|看客们?|人群|所有[^，。！？：；、]{0,6}?人|有几个人?)')
_ONE = (r'(?:有人|有个人|有一个人|某人|那人|那个人|这人|这个人|此人|来人|一个人|一人|不知是?谁|有谁|一个声音|有个声音|'
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


PRONOUNS = {'他', '她', '它', '我', '你', '您', '他们', '她们', '我们', '你们', '自己', '大家', '众人', '有人', '那人', '此人', '这人', '一人', '男人', '女人',
            '那个', '这个', '对方', '那位', '这位', '两人', '几人', '一个', '那个人', '这个人', '来人', '此人'}

# What a model may write in the speaker field that names nobody: pronouns and
# demonstratives (那人, 这个) — not 众人/男人/女人, which a text uses as names
# for people it never names (the gold of 阿Q chapter 5 calls a speaker 男人).
NOT_SPEAKERS = frozenset({'他', '她', '它', '你', '您', '他们', '她们', '你们', '自己', '那人', '此人', '这人', '那个', '这个', '那位', '这位',
                          '对方', '一人', '一个', '两人', '几人', '那个人', '这个人', '来人'})       # not 我: a story told in the first person has 我 speaking

def book_name(name):
    """A name worth telling the model about from a book's other chapters: not a
    pronoun, not a stand-in the page made (某人, 某人甲, 众人), not a placeholder
    (角色2, 酒客2) — those belong to one chapter's review, not to the cast."""
    name = (name or '').strip()
    if not name or name in NOT_SPEAKERS or (name in PRONOUNS and name not in ('我', '我们')):
        return False
    if name.startswith(tuple(STAND_INS.values())) or re.match(r'^(?:角色|人物|说话人|speaker)\s*[0-9０-９一二三四五六七八九十甲乙丙丁]*$', name, re.I):
        return False
    if re.search(r'[0-9０-９]$', name):
        return False
    return True


# Manner words a tag puts before its verb — 陈小雪苦笑道, 王伯喃喃道, 她缓缓道,
# 微笑着说 — are not part of the name (本人 2026-09-22: 缓缓, 喃喃, 微笑着 and
# 王伯苦 (from 王伯苦笑道) had become people). A candidate loses them from its tail; one
# that was nothing but manner is no name.
_MANNER_TAIL = re.compile(r'(?:苦笑|冷笑|微笑|干笑|大笑|轻笑|讪笑|狞笑|惨笑|嗤笑|嘿嘿|哈哈|嘻嘻|呵呵|缓缓|喃喃|淡淡|轻轻|慢慢|冷冷|悠悠|徐徐|幽幽|微微|默默|暗暗|连连|急急|忙忙|'
                          r'沉声|低声|高声|大声|小声|轻声|厉声|朗声|柔声|怒|笑|哭|叹|点头|摇头|皱眉|沉吟|喘息|苦|冷|微|干|轻|讪|狞|急|忙)?(?:着|地|了)?$')
_TAG_TAIL = re.compile(r'(?:^|[，。！？：；、])([^，。！？：；、“”"\s]{1,7}?)(' + _VERB_ALT_ALL + r')[：:，,]?$')   # room for a manner word after the name (阿宁冷冷地说)


FUNCTION_STARTS = ('又', '便', '就', '才', '也', '都', '却', '忙', '正', '只', '还', '再', '一', '有的', '有人', '别人', '旁人', '对', '向', '朝', '跟', '和',
                   '于是', '然后', '接着', '连忙', '点头', '摇头', '笑着', '哭着', '低声', '大声', '高声', '轻声', '冷冷', '慢慢')
# Words a speech tag may open with that are not anybody: 阿Q很以为奇，而且想：
# gave the model a character called 而且 (本人 2026-09-16, 阿Q chapter 5).
NOT_NAMES = frozenset('而且 并且 但是 可是 只是 不过 因此 所以 因为 虽然 然而 于是 后来 忽然 突然 随即 立刻 马上 终于 竟然 居然 果然 只好 只得 '
                      '便是 就是 也是 还是 都是 正是 又是 却是 不是 这时 那时 此时 当时 一面 一边 一时 一会 不禁 不由 不觉 索性 仍旧 依旧 照例 仍然 依然 '
                      '果真 大约 似乎 好像 仿佛 显然 当然 自然 甚至 更加 越发 格外 不免 未免 不妨 何况 接着 然后 于是 总是 老是 已经 曾经 刚才 方才 '
                      '同时 顿时 登时 立时 随后 从此 此后 以后 以前 之后 之前 先是 起初 最后 结果 其实 反正 究竟 到底 简直 几乎 差点 险些 幸而 幸亏 '
                      '或者 或是 要么 也许 大概 可能 恐怕 未必 一定 必定 务必 只要 只有 除非 无论 不管 尽管 即使 哪怕 假如 如果 倘若 要是 既然 由于'.split())


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
        stripped = _MANNER_TAIL.sub('', name)
        if stripped != name:
            name = stripped
            while len(name) >= 3 and name[-1] in '又便就也都才却忙再还正只先':
                name = name[:-1]
        if len(name) > 4:
            continue                         # a clause, not a name (陈小雪看着窗外说)
        if len(name) < 2 or name in SPEECH_VERBS or any(v in name for v in ('说', '道', '问', '答')):
            continue
        if name in PRONOUNS or any(name.startswith(pro) and len(name) - len(pro) <= 1 for pro in PRONOUNS):
            continue
        if re.search(r'[对向跟朝冲](?:我|你|他|她|您|它)(?:们)?$', name):
            continue                         # 阿宁对我 is a phrase, not a longer name
        if name in NOT_NAMES or any(name.startswith(w) for w in FUNCTION_STARTS):
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


_EN_TITLE = r'(?:Mr|Mrs|Ms|Miss|Dr|Sir|Lady|Lord|Professor|Captain)'
_EN_SPEECH = r'(?:said|asked|replied|answered|added|cried|remarked|continued|whispered|exclaimed|observed|returned|repeated|interrupted|muttered|shouted|declared|inquired|demanded|insisted|protested|laughed|sighed|began|called)'


def english_tag(before, after, mentions):
    """The one character an English speech tag beside a line names — ” said
    Darcy, / Elizabeth replied, “ — matched to the cast by a whole word of the
    name (Darcy → Mr. Darcy; Elizabeth → Elizabeth Bennet), or None."""
    tag = None
    m = re.match(r'\s*[,;]?\s*' + _EN_SPEECH + r'\s+(?:(?:' + _EN_TITLE + r')\.?\s+)?([A-Z][\w\']+)', after or '')
    if m:
        tag = m.group(1)
    else:
        m = re.match(r'\s*[,;]?\s*(?:(?:' + _EN_TITLE + r')\.?\s+)?([A-Z][\w\']+)\s+' + _EN_SPEECH + r'\b', after or '')
        if m:
            tag = m.group(1)
        else:
            tail = (before or '').rstrip()[-60:]
            m = re.search(r'(?:(?:' + _EN_TITLE + r')\.?\s+)?([A-Z][\w\']+)\s+' + _EN_SPEECH + r'[,:]?\s*$', tail)
            if m:
                tag = m.group(1)
    if not tag:
        return None
    found = {name for name, forms in mentions.items()
             if any(re.search(r'(?<!\w)' + re.escape(tag) + r'(?!\w)', f) for f in forms)}
    return next(iter(found)) if len(found) == 1 else None


def english_name_support(name, text):
    """2: a whole name occurs; 1: its bare form occurs in a speech tag.

    A bare surname supports a review suggestion, not an identity merge:
    Mr. Finch and Miss Finch remain separate cast entries. Never accept a
    surname substring or strip another character's title to create evidence.
    """
    titled = re.fullmatch('(' + _EN_TITLE + r')\.?\s+(.+)', name)
    pattern = (re.escape(titled[1]) + r'\.?\s+' + re.escape(titled[2])) if titled else re.escape(name)
    if re.search(r'(?<!\w)' + pattern + r'(?!\w)', text):
        return 2
    if not titled:
        return 0
    bare = re.escape(titled[2])
    # A direct tag avoids treating "Miss Finch" elsewhere as "Mr. Finch".
    after = re.search(r'\b' + _EN_SPEECH + r'\s+' + bare + r'(?!\w)', text)
    if after:
        return 1
    for m in re.finditer(r'(?<!\w)' + bare + r'\s+' + _EN_SPEECH + r'\b', text):
        prefix = text[:m.start()]
        if not re.search(_EN_TITLE + r'\.?\s+$', prefix):
            return 1
    return 0

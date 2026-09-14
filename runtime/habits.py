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
                '说', '道', '问', '答', '叫', '喊', '骂', '笑', '回', '嚷', '吼', '哼', '应', '继续', '接着', '开口', '插嘴', '补充')


def speech_tag(before, after, mentions):
    """The name a speech tag beside a line gives it, or None. `mentions` maps each
    character to the forms it is known by. Looks at the tail of the narration
    before the line (小雪笑道：) and the head of the narration after it
    (”小雪说。); exactly one character must fit."""
    tail = STRIP.sub('', before or '')[-16:]
    after_clean = STRIP.sub('', after or '')
    # A narration that ends by introducing a quote (小雪说：) tags the line
    # after it, not the one before; only a closing tag (小雪说。) counts here.
    head = '' if after_clean.rstrip('。！？!?').endswith(('：', ':', '，', ',')) else after_clean[:16]
    found = set()
    for name, forms in mentions.items():
        for f in forms:
            i = tail.rfind(f)
            if i >= 0 and any(v in tail[i + len(f):i + len(f) + 6] for v in SPEECH_VERBS):
                found.add(name)
            j = head.find(f)
            if 0 <= j <= 4 and any(v in head[j + len(f):j + len(f) + 6] for v in SPEECH_VERBS):
                found.add(name)
    return next(iter(found)) if len(found) == 1 else None


PRONOUNS = {'他', '她', '它', '我', '你', '您', '他们', '她们', '我们', '你们', '大家', '众人', '有人', '那人', '此人', '一人', '男人', '女人',
            '那个', '这个', '对方', '那位', '这位', '两人', '几人', '一个'}
_TAG_TAIL = re.compile(r'(?:^|[，。！？：；、])([^，。！？：；、“”"\s]{1,4}?)(' + '|'.join(sorted(SPEECH_VERBS, key=len, reverse=True)) + r')[：:，,]?$')


def names_from_tags(narrations):
    """Names the speech tags themselves reveal — 小雪说： — so a text with no
    earlier chapters still has a cast. Pronouns are not names."""
    out = []
    for text in narrations:
        m = _TAG_TAIL.search(STRIP.sub('', text or ''))
        if m:
            name = m.group(1)
            if name in SPEECH_VERBS or any(v in name for v in ('说', '道', '问', '答')):
                name = ''
            for pro in sorted(PRONOUNS, key=len, reverse=True):
                if name.startswith(pro) and len(name) - len(pro) <= 1:
                    name = ''
                    break
            if name and name not in out:
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


def suggest(text, profile):
    """(best speaker, margin) for a line, or (None, 0) when there is nothing to
    compare with. Characters the line addresses by name are excluded."""
    candidates = {sp: _cos(grams(text), pr) for sp, pr in profile.items() if not mentioned(text, sp)}
    if not candidates:
        return None, 0.0
    ranked = sorted(candidates.items(), key=lambda kv: -kv[1])
    best, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return best, score - second


# 最后更新：2026-09-14 · Claude Hera（按说话习惯建议说话人；本人 2026-09-14 提出）

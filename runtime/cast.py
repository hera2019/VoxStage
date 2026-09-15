"""The cast: who is in a story, apart from what they are called.

A character is an opaque id with a display name, the other names the text
uses for them (aliases), the colours an author gave them, a sex when the
reviewer set one, where they first appeared, and how the entry came to be
— the reviewer's word, a mark in the manuscript, a tag in the narration,
the model, or a rule (Astra 2026-09-16: 角色编号独立于名字; renaming is not
replacing, and a renamed 陈小雪 followed by a new 陈小雪 must not collide).

Projects still key their voices, colours and sexes by name; the cast is
the book's (or, for a draft made outside a book, the draft's) record of
which name is whose, and the adapter between the two is `find`.
"""
import uuid

SOURCES = ('person', 'mark', 'tag', 'model', 'rule', 'alias', 'template')
RESERVED = ('', 'UNKNOWN', 'NARRATOR', '旁白', 'NARRATION')


def new_entry(name, source='model', introduced=None, aliases=(), colours=(), sex=''):
    return {'id': uuid.uuid4().hex, 'name': name.strip(), 'aliases': [a for a in aliases if a and a != name],
            'colours': list(colours), 'sex': sex or '', 'source': source if source in SOURCES else 'model', 'introduced': introduced}


def find(cast, name):
    """The entry a name belongs to — its own name or one of its aliases — or None."""
    name = (name or '').strip()
    if not name or name.upper() in RESERVED:
        return None
    for entry in cast:
        if entry['name'] == name:
            return entry
    for entry in cast:
        if name in entry['aliases']:
            return entry
    return None


def by_id(cast, cast_id):
    return next((e for e in cast if e['id'] == cast_id), None)


def ensure(cast, name, source='model', introduced=None, colours=()):
    """The entry for a name, made if there is none. Returns (entry, created)."""
    entry = find(cast, name)
    if entry:
        for c in colours:
            if c not in entry['colours']:
                entry['colours'].append(c)
        return entry, False
    entry = new_entry(name, source, introduced, colours=colours)
    cast.append(entry)
    return entry, True


def rename(cast, cast_id, new_name):
    """A new display name for the same character. Refused when another
    character already has that name (the reviewer must merge or pick another)."""
    new_name = (new_name or '').strip()
    entry = by_id(cast, cast_id)
    if not entry or not new_name or new_name.upper() in RESERVED:
        raise ValueError('名字无效。')
    other = find(cast, new_name)
    if other and other['id'] != cast_id:
        raise ValueError(f'已经有一个「{new_name}」了；要合并的话，先把这个人的句子改成那个名字。')
    if entry['name'] != new_name:
        if entry['name'] not in entry['aliases']:
            entry['aliases'].append(entry['name'])       # the old name stays as a way of calling them
        entry['aliases'] = [a for a in entry['aliases'] if a != new_name]
        entry['name'] = new_name
    return entry


def add_alias(cast, cast_id, alias, source='person'):
    """老板娘 is also 陈小雪. An alias that is another character's name or alias
    is moved to this one only when the reviewer says so (source person)."""
    alias = (alias or '').strip()
    entry = by_id(cast, cast_id)
    if not entry or not alias or alias == entry['name'] or alias.upper() in RESERVED:
        return entry
    other = find(cast, alias)
    if other and other['id'] != cast_id:
        if source != 'person':
            return entry
        if other['name'] == alias:
            cast.remove(other)                            # the whole entry was that one name; it is this character now
            for a in other['aliases']:
                if a not in entry['aliases'] and a != entry['name']:
                    entry['aliases'].append(a)
            for c in other['colours']:
                if c not in entry['colours']:
                    entry['colours'].append(c)
        else:
            other['aliases'].remove(alias)
    if alias not in entry['aliases']:
        entry['aliases'].append(alias)
    return entry


def split(cast, alias):
    """The reviewer gave an alias's lines and its character's lines to two
    different people: the alias becomes a character of its own. Returns the
    new entry (or the existing one when nothing was joined)."""
    alias = (alias or '').strip()
    holder = next((e for e in cast if alias in e['aliases']), None)
    if holder is None:
        return find(cast, alias)
    holder['aliases'].remove(alias)
    entry = new_entry(alias, 'person', holder.get('introduced'))
    entry['split_from'] = holder['id']
    cast.append(entry)
    return entry


def unsplit(cast, entry_id):
    """Undo a split: the character made from an alias goes back to being an alias."""
    entry = by_id(cast, entry_id)
    if not entry or not entry.get('split_from'):
        return None
    holder = by_id(cast, entry['split_from'])
    if holder is None:
        return None
    cast.remove(entry)
    if entry['name'] not in holder['aliases']:
        holder['aliases'].append(entry['name'])
    return holder


def alias_table(cast):
    """{alias: name} — the view the draft rules and the book have always used."""
    return {a: e['name'] for e in cast for a in e['aliases']}


def from_names(names, source='person'):
    """A cast from plain names — the sibling projects of a book made before the
    cast existed, in the order the names are given."""
    cast = []
    for name in names:
        ensure(cast, name, source)
    return cast


# 最后更新：2026-09-16 · Claude Hera（按 Astra 的定案：id 不透明、名字只是称呼）

"""The English interface stays complete (本人 2026-09-24: 英文界面是一定要做的):
every piece of interface text passed to tr() has an English entry, and so does
every message the server raises or sends for display, with the same {0}-style
placeholders. A new Chinese sentence without its English fails here, not in
front of an English-speaking user. Claude Hera."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CJK = re.compile('[㐀-鿿＀-￯　-〿]')
SLOTS = re.compile(r'\{\d+\}')
DISPLAY_KEYS = {'basis', 'detail', 'message', 'reason', 'label', 'note', 'warning', 'hint', 'title', 'summary', 'error',
                'notice', 'description', 'stale_reasons', 'blocked', 'problem'}


def interface_keys():
    keys = set()
    for path in (ROOT / 'frontend/src').glob('*.tsx'):
        for raw in re.findall(r'\btr\("((?:[^"\\]|\\.)*)"', path.read_text(encoding='utf-8')):
            keys.add(json.loads('"' + raw + '"'))
    return keys


def server_messages():
    """Chinese text the server raises, or puts in a field the page shows, as
    templates: an f-string's {…} becomes {0}, {1}…"""
    def template(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            out, n = '', 0
            for part in node.values:
                if isinstance(part, ast.Constant):
                    out += part.value
                else:
                    out += '{%d}' % n
                    n += 1
            return out
        return None

    def pieces(node):
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            text = template(node)
            if text and CJK.search(text):
                yield text
        elif isinstance(node, ast.BinOp):
            yield from pieces(node.left)
            yield from pieces(node.right)
        elif isinstance(node, ast.IfExp):
            yield from pieces(node.body)
            yield from pieces(node.orelse)
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                yield from pieces(value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('join', 'format'):
            yield from pieces(node.func.value)
            for arg in node.args:
                yield from pieces(arg)
        elif isinstance(node, (ast.List, ast.Tuple)):
            for element in node.elts:
                yield from pieces(element)

    found = set()
    for path in (ROOT / 'runtime').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                for arg in node.exc.args:
                    found.update(pieces(arg))
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in DISPLAY_KEYS:
                        found.update(pieces(value))
    return found


def test_every_interface_text_has_its_english():
    table = json.loads((ROOT / 'frontend/src/locales/en.json').read_text(encoding='utf-8'))
    keys = interface_keys()
    assert len(keys) > 900
    missing = sorted(k for k in keys if k not in table)
    assert not missing, f'{len(missing)} without English, e.g. {missing[:5]}'
    uneven = [k for k in keys if set(SLOTS.findall(table[k])) - set(SLOTS.findall(k))]
    assert not uneven, uneven[:5]


def test_every_server_message_has_its_english():
    table = json.loads((ROOT / 'frontend/src/locales/en-server.json').read_text(encoding='utf-8'))
    messages = server_messages()
    assert len(messages) > 400
    missing = sorted(m for m in messages if m not in table)
    assert not missing, f'{len(missing)} without English, e.g. {missing[:5]}'
    uneven = [m for m in messages if set(SLOTS.findall(table[m])) != set(SLOTS.findall(m))]
    assert not uneven, uneven[:5]

# 最后更新：2026-09-24 · Claude Hera

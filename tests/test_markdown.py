"""Markdown manuscripts come in as prose; their headings become chapters. Claude Hera, 2026-09-15."""
from runtime.markdown import to_text
from runtime.books import split_chapters
from tests.test_workflow import client  # noqa: F401


def test_marks_go_and_words_stay():
    text, heads = to_text('# 序\n\n她说：“**来**了。”\n\n[链接](http://x)、![图](a.png)、`代码`、~~删~~、_斜_。\n\n---\n\n## 第二章\n\n> 引用的话。\n\n- 一\n- 二\n')
    assert text == '序\n\n她说：“来了。”\n\n链接、、代码、删、斜。\n\n第二章\n\n引用的话。\n\n一\n二\n'
    assert [text.split('\n')[h] for h in heads] == ['序', '第二章']
    assert '#' not in text and '*' not in text


def test_a_markdown_book_is_cut_at_its_own_headings_even_when_they_do_not_say_chapter(client):
    md = '# 开张\n\n' + '她推开门。\n' * 40 + '\n# 生意\n\n' + '他数着钱。\n' * 40
    r = client.post('/api/import/markdown', json={'text': md}).json()
    assert [r['text'].split('\n')[h] for h in r['headings']] == ['开张', '生意']
    chapters = split_chapters(r['text'], r['headings'])
    assert [c['title'] for c in chapters] == ['开张', '生意'] and ''.join(c['text'] for c in chapters) == r['text']
    book = client.post('/api/books', json={'title': '小店', 'language': 'zh', 'script': r['text'], 'headings': r['headings']}).json()
    assert [c['title'] for c in book['chapters']] == ['开张', '生意']
    # Without the hint the same text is one headingless chapter.
    assert len(split_chapters(r['text'])) == 1

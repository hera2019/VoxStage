"""A long text kept as a book, one chapter at a time into the ordinary flow."""
from runtime.books import split_chapters, CHAPTER_LIMIT
from tests.test_workflow import client, create  # noqa: F401


def test_chapters_are_found_by_their_headings_and_reassemble_exactly():
    book = '序言\n开头的一段。\n\n第一章 到镇上去\n' + '林小雪走在路上。' * 30 + '\n\n第二回 雨\n雨点敲着窗。\n第三卷 尾声\n结束了。\n'
    chapters = split_chapters(book)
    assert [c['title'] for c in chapters] == ['（开头）', '第一章 到镇上去', '第二回 雨', '第三卷 尾声']
    assert ''.join(c['text'] for c in chapters) == book
    assert chapters[1]['text'].startswith('第一章 到镇上去\n')


def test_a_headingless_text_is_cut_at_paragraphs_never_inside_a_sentence():
    text = '雨点敲着窗。她抬头看了看。\n\n' * 400
    chapters = split_chapters(text)
    assert len(chapters) > 1 and all(len(c['text']) <= CHAPTER_LIMIT for c in chapters)
    assert all(c['text'].endswith('\n\n') for c in chapters)          # cut at paragraph breaks
    assert ''.join(c['text'] for c in chapters) == text


def test_a_single_overlong_paragraph_is_cut_after_sentence_ends():
    text = '第一章 很长\n' + '这是一个非常长的段落，没有空行。' * 400 + '\n'
    chapters = split_chapters(text)
    assert all(len(c['text']) <= CHAPTER_LIMIT for c in chapters)
    assert all(c['text'].rstrip('\n').endswith('。') for c in chapters)
    assert [c['title'] for c in chapters][:2] == ['第一章 很长 · 1', '第一章 很长 · 2']
    assert ''.join(c['text'] for c in chapters) == text


def test_a_short_text_is_one_chapter_and_short_flow_is_unchanged():
    assert split_chapters('小雪看着窗外。') == [{'title': '', 'text': '小雪看着窗外。'}]


def test_a_book_hands_out_chapters_with_names_from_its_other_chapters(client):
    book = client.post('/api/books', json={'title': '孔乙己', 'language': 'zh',
                                           'script': '第一章 酒店\n' + '鲁镇的酒店。' * 300 + '\n第二章 伙计\n我从十二岁起。\n'}).json()
    assert [c['title'] for c in book['chapters']] == ['第一章 酒店', '第二章 伙计']
    assert 'text' not in book['chapters'][0]                           # listing carries no bodies
    assert client.get('/api/books').json()[0]['chapters'] == 2
    # A project made from chapter one contributes its names to chapter two.
    create(client, 'zh', script='掌柜：还欠十九个钱呢。\n孔乙己：下回还清罢。')
    p = client.get('/api/projects').json()[0]
    client.patch('/api/projects/' + p['id'], json={'revision': 0, 'name': '孔乙己 · 第一章 酒店'})
    second = client.get(f"/api/books/{book['id']}/chapters/2").json()
    assert second['project_name'] == '孔乙己 · 第二章 伙计'
    assert second['text'].startswith('第二章 伙计')
    assert set(second['known_names']) == {'掌柜', '孔乙己'}
    assert client.get(f"/api/books/{book['id']}/chapters/9").status_code == 400
    assert client.get('/api/books/' + 'f' * 32).status_code == 400


def test_english_chapter_headings_are_found_too():
    book = 'CHAPTER I\n\nIt is a truth universally acknowledged.\n\nChapter Two\n\n"My dear Mr. Bennet," said his lady.\n\nChapter 3\n\nThe end.\n'
    chapters = split_chapters(book)
    assert [c['title'] for c in chapters] == ['CHAPTER I', 'Chapter Two', 'Chapter 3']
    assert ''.join(c['text'] for c in chapters) == book
    # A sentence that merely contains the word is not a heading.
    assert len(split_chapters('He read the chapter twice.\n')) == 1

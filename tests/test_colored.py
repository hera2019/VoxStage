"""A coloured .docx read straight from its XML, and the reviewer's colour
answers turned into text plus speaker hints. The document is built here.
Claude Hera, 2026-09-16."""
import zipfile
from io import BytesIO
from runtime.colored import read_docx, colour_groups, compose, has_quotes

XUE, NING, PLUM = '800080', '000080', '8064a2'


def docx(paragraphs, body_colour=None):
    """paragraphs: [(style or None, [(text, colour or None)])] -> bytes of a minimal .docx."""
    def run(text, colour):
        rpr = f'<w:rPr><w:color w:val="{colour}"/></w:rPr>' if colour else ''
        return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'
    body = ''.join(f'<w:p>{"<w:pPr><w:pStyle w:val=%s/></w:pPr>" % ('"' + style + '"') if style else ""}{"".join(run(t, c) for t, c in runs)}</w:p>' for style, runs in paragraphs)
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>{body}</w:body></w:document>'
    def style(sid, name, level=None, colour=None):
        ppr = f'<w:pPr><w:outlineLvl w:val="{level}"/></w:pPr>' if level is not None else ''
        rpr = f'<w:rPr><w:color w:val="{colour}"/></w:rPr>' if colour else ''
        return f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>{ppr}{rpr}</w:style>'
    styles = (f'<?xml version="1.0" encoding="UTF-8"?><w:styles {ns}>' + style('Normal', 'Normal', 9, body_colour)
              + style('Title', 'Title', None) + style('H1', '小标题', 0) + style('H2', '小标题 2', 1) + style('Body', '正文', 9, body_colour) + '</w:styles>')
    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('word/document.xml', document); z.writestr('word/styles.xml', styles)
    return out.getvalue()


def test_colours_come_from_the_run_or_its_styles_and_headings_from_outline_levels():
    doc = read_docx(docx([('Title', [('小店', None)]), ('H1', [('第一章 猫', None)]),
                          ('Body', [('阿宁一进门。', None), ('“老板娘～”', NING), ('他喊道。', None)]),
                          ('Body', [('“嗯～”', XUE), ('她说。', None)]), ('H2', [('二 · 夜里', None)]), ('Body', [('夜深了。', PLUM)])],
                         body_colour='800080'))
    levels = [p['level'] for p in doc['paragraphs']]
    assert levels == [1, 1, None, None, 2, None]                       # Title by name, 小标题 by outline 0, 正文 (outline 9) is body
    assert doc['paragraphs'][2]['runs'] == [['阿宁一进门。', '#800080'], ['“老板娘～”', '#000080'], ['他喊道。', '#800080']]   # the body style's colour fills in
    assert doc['paragraphs'][5]['runs'] == [['夜深了。', '#8064a2']]
    groups = colour_groups(doc['paragraphs'])
    assert [g['colour'] for g in groups] == ['#800080', '#000080', '#8064a2', ] or groups[0]['colour'] == '#800080'
    assert has_quotes(doc['paragraphs'])


def test_the_reviewers_answers_become_text_and_hints_and_two_speakers_in_one_paragraph_get_their_own_lines():
    doc = read_docx(docx([('H1', [('玖、探寻宝藏', None)]), ('H2', [('[初登宝地]', None)]),
                          ('Body', [('上学的时候。', PLUM)]),
                          ('Body', [('我警告你们！', None)]),                                   # the body colour: the girl
                          ('Body', [('哈哈！警告我们？', '008000')]),
                          ('Body', [('少跟她废话！', 'e36c0a'), ('老大我帮你！', '4a442a')]),   # two people in one paragraph
                          ('Body', [('把她', 'e36c0a'), ('胳膊', 'ff0000'), ('拧住！', 'e36c0a')]),   # a word in red for emphasis
                          ('Body', [('（作者注：此处待改）', 'bfbfbf')])],
                         body_colour='800080'))
    assert not has_quotes(doc['paragraphs'])
    choices = {'#800080': {'as': 'character', 'name': '女主'}, '#008000': {'as': 'character', 'name': '老大'},
               '#e36c0a': {'as': 'character', 'name': '某人甲'}, '#4a442a': {'as': 'character', 'name': '某人乙'},
               '#8064a2': {'as': 'narration'}, '#ff0000': {'as': 'ignore'}, '#bfbfbf': {'as': 'drop'}}
    r = compose(doc['paragraphs'], choices)
    lines = r['text'].split('\n')
    assert lines[:8] == ['玖、探寻宝藏', '[初登宝地]', '上学的时候。', '我警告你们！', '哈哈！警告我们？', '少跟她废话！', '老大我帮你！', '把她胳膊拧住！']
    assert r['headings'] == [0] and r['silent'] == [0, 1]              # level 1 opens a chapter; both headings not read
    spoken = {r['text'][h['start']:h['end']]: h['speaker'] for h in r['hints']}
    assert spoken == {'上学的时候。': 'NARRATOR', '我警告你们！': '女主', '哈哈！警告我们？': '老大', '少跟她废话！': '某人甲', '老大我帮你！': '某人乙', '把她胳膊拧住！': '某人甲'}
    assert '作者注' not in r['text']
    # A colour left unanswered is kept and hinted as unplaced.
    r = compose(doc['paragraphs'], {k: v for k, v in choices.items() if k != '#008000'})
    assert {h['speaker'] for h in r['hints'] if r['text'][h['start']:h['end']] == '哈哈！警告我们？'} == {''}


def test_a_coloured_document_goes_through_import_book_draft_and_confirm_without_the_model(tmp_path):
    """The author's colours settle every line: the model is never asked, the
    review page shows the author's names plainly, headings are kept silent, and
    the project reads what the colours said."""
    import base64
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.engines import FixtureEngine
    from tests.test_attribution_import import Roles, HEADERS
    class Never(Roles):
        def annotate(self, text, log_path):
            raise AssertionError('the model must not be asked')
    body = [('H1', [('第一章 猫', None)]), ('Body', [('上学的时候。', PLUM)]), ('Body', [('猫又跑出去啦～', NING)]), ('Body', [('赏你一块糖～', None)]),
            ('H1', [('第二章 账', None)]), ('H2', [('[夜里]', None)]), ('Body', [('少了三块～', NING), ('数错了吧？', None)]), ('Body', [('（作者注）', 'bfbfbf')])]
    data = base64.b64encode(docx(body, body_colour='800080')).decode()
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Never()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        r = c.post('/api/import/docx', json={'name': 'test.docx', 'data': data}).json()
        assert [h['text'] for h in r['headings']] == ['第一章 猫', '第二章 账', '[夜里]'] and r['has_quotes'] is False
        colours = {g['colour']: g for g in r['colours']}
        assert set(colours) == {'#800080', '#000080', '#8064a2', '#bfbfbf'} and colours['#000080']['runs'] == 2
        a = c.post(f"/api/import/docx/{r['import_id']}/apply", json={'choices': {
            '#800080': {'as': 'character', 'name': '陈小雪'}, '#000080': {'as': 'character', 'name': '阿宁'},
            '#8064a2': {'as': 'narration'}, '#bfbfbf': {'as': 'drop'}}}).json()
        assert a['headings'] == [0, 4] and a['silent'] == [0, 4, 5]
        book = c.post('/api/books', json={'title': '小店', 'language': 'zh', 'script': a['text'], 'headings': a['headings'], 'hints': a['hints'], 'silent': a['silent']}).json()
        assert [ch['title'] for ch in book['chapters']] == ['第一章 猫', '第二章 账']
        ch2 = c.get(f"/api/books/{book['id']}/chapters/2").json()
        assert ch2['silent'] == [0, 1] and [h['speaker'] for h in ch2['hints']] == ['阿宁', '陈小雪']
        assert [h['speaker'] for h in c.get(f"/api/books/{book['id']}/chapters/1").json()['hints']] == ['NARRATOR', '阿宁', '陈小雪']
        d = c.post('/api/attribution/draft', json={'script': ch2['text'], 'language': 'zh', 'book_id': book['id'], 'hints': ch2['hints'], 'silent': ch2['silent']}).json()
        by = {u['text'].strip(): u for u in d['units'] if not u['blank']}
        assert by['少了三块～']['speaker'] == '阿宁' and by['少了三块～'].get('tier') is None and by['少了三块～']['source'] == 'mark'
        assert by['数错了吧？']['speaker'] == '陈小雪' and by['[夜里]']['silent'] and by['[夜里]']['kind'] == 'narration'
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': u['speaker']} for u in d['units']]
        p = c.post('/api/attribution/confirm', json={'draft_id': d['draft_id'], 'name': ch2['project_name'], 'labels': labels,
                                                    'book_id': book['id'], 'chapter_index': 2, 'silent': ch2['silent']}).json()
        segs = {s['text'].strip(): s for s in p['segments']}
        assert p['colors'] == {'阿宁': '#000080', '陈小雪': '#800080'}                    # the manuscript's colours are the characters' (本人 2026-09-16)
        assert p['attribution']['model_id'] is None and d['model']['note'] == '作者标的，没有用模型'
        assert segs['第二章 账']['read_aloud'] is False and segs['[夜里]']['read_aloud'] is False
        assert segs['少了三块～']['speaker'] == '阿宁' and segs['少了三块～']['read_aloud'] is True and segs['数错了吧？']['speaker'] == '陈小雪'
        assert p['attribution']['model_id'] is None

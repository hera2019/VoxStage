"""The default voice pack: fourteen designed voices installed on a fresh
machine once, with their tags; a deleted one is not forced back unless asked;
a pack entry not marked synthetic is refused (D5). Claude Hera, 2026-09-23."""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime import voicepack

HEADERS = {'x-voxstage': '1'}
PACK = Path(__file__).resolve().parents[1] / 'voicepack' / 'default'


@pytest.mark.skipif(not (PACK / 'manifest.json').is_file(), reason='音色包还没导出')
def test_a_fresh_machine_starts_with_the_default_pack_and_its_tags(tmp_path):
    manifest = voicepack.read(PACK)
    assert len(manifest['voices']) == 14 and all(v['synthetic_audio'] is True for v in manifest['voices'])
    assert all(v['english_name'] for v in manifest['voices'])
    app = create_app(tmp_path / 'projects', FixtureEngine(), voicepack_dir=PACK)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as c:
        voices = c.get('/api/voices/custom').json()
        assert sorted(v['name'] for v in voices) == sorted(v['name'] for v in manifest['voices'])
        assert all(v['pack'] == 'default' and v['synthetic_audio'] is True and v['source'] == 'generated' for v in voices)
        tags = c.get('/api/settings').json()['voice_tags']
        narrator = next(v for v in voices if v['pack_role']['narrator'] and v['pack_role']['rank'] == 1)
        assert '旁白' in tags['custom:' + narrator['id']]
        gone = voices[0]
        assert c.delete('/api/voices/custom/' + gone['id']).status_code == 200
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine(), voicepack_dir=PACK), base_url='http://127.0.0.1', headers=HEADERS) as c:
        assert len(c.get('/api/voices/custom').json()) == 13                  # installed once: a deleted voice stays deleted
        assert c.post('/api/voices/pack/install').json()['installed'] == [gone['name']]
        assert len(c.get('/api/voices/custom').json()) == 14                  # …until asked for


def test_a_pack_entry_not_marked_synthetic_is_refused(tmp_path):
    folder = tmp_path / 'pack'; folder.mkdir()
    shutil.copy(PACK / '01.flac', folder / '01.flac') if (PACK / '01.flac').is_file() else pytest.skip('音色包还没导出')
    entry = dict(voicepack.read(PACK)['voices'][0]); entry['synthetic_audio'] = False
    (folder / 'manifest.json').write_text(json.dumps({'pack': 'default', 'version': 1, 'voices': [entry]}, ensure_ascii=False))
    from runtime.voices import VoiceLibrary
    with pytest.raises(ValueError, match='合成'):
        voicepack.install(VoiceLibrary(tmp_path / 'voices'), folder, marker_root=tmp_path)
    assert VoiceLibrary(tmp_path / 'voices').list() == []

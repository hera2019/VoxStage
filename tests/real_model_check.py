"""Recorded preset-speech integration; never a human listening pass. Astra, 2026-09-09."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from runtime.app import create_app

root=Path(__file__).resolve().parent.parent
app=create_app()
records=[]
with TestClient(app,base_url='http://127.0.0.1:8765',headers={'X-VoxStage':'1'}) as client:
    for language in ('zh','en'):
        p=client.post('/api/projects',json={'name':'雨夜 · 中文实测' if language=='zh' else 'A rainy evening · English test',
               'language':language,'script':(root/'examples'/f'{language}.txt').read_text()}).json()
        r=client.post(f'/api/projects/{p["id"]}/render/start',json={'revision':p['revision']})
        if r.status_code!=200:raise RuntimeError(r.text)
        deadline=time.monotonic()+1200
        while time.monotonic()<deadline:
            p=client.get('/api/projects/'+p['id']).json()
            if p['job']['status']!='running':break
            time.sleep(.5)
        if p['job']['status']=='running':raise RuntimeError('Generation exceeded 20 minute deadline')
        export=client.post(f'/api/projects/{p["id"]}/export/create',json={'revision':p['revision']})
        records.append({'language':language,'project_id':p['id'],'job':p['job'],
                        'segments':[{'id':s['id'],'text':s['text'],'speaker':s['speaker'],
                                     'status':s['status'],'error':s['error'],'audio':s['audio']} for s in p['segments']],
                        'export_status':export.status_code})
        print(language, p['job'], 'export:', export.status_code, flush=True)
payload={'model':app.state.engine.identity,'synthetic_audio':True,'results':records,
         'quality_acceptance':'not judged; human listening and content verification pending'}
(root/'results/real-model-check.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
passed=all(r['export_status']==200 and all(s['status']=='ready' for s in r['segments']) for r in records)
lines=['# Preset voice integration', '', 'Technical workflow: '+('PASS' if passed else 'FAIL'),
       '', 'Human voice quality and content completeness: NOT YET ACCEPTED.',
       'Measurements below belong to this CustomVoice run, not the earlier Base cloning experiment.', '',
       '| Language | Ready sentences | Export HTTP status |','|---|---:|---:|']
for r in records:lines.append(f'| {r["language"]} | {sum(s["status"]=="ready" for s in r["segments"])} | {r["export_status"]} |')
lines+=['','See real-model-check.json for per-sentence measurements, model revision and failures.','', '最后更新：2026-09-09 · Astra']
(root/'results/real-model-check.md').write_text('\n'.join(lines)+'\n')
sys.exit(0 if passed else 1)

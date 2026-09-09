"""Actual local model through application routes. Astra, 2026-09-09."""
import hashlib,json,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import MlxEngine

def main():
    report={'synthetic_audio':True,'checks':[],'quality':'Integration only; new render requires listening. Prior experiment acceptance remains scoped.'}
    try:
        engine=MlxEngine(ROOT/'user-data/models/qwen-customvoice')
        with TestClient(create_app(engine=engine),base_url='http://127.0.0.1:8765',headers={'X-VoxStage':'1'}) as client:
            def request(url,body):
                r=client.post(url,json=body);assert r.status_code==200,r.text
                return r.json()
            def render(p,**extra):
                p=request(f'/api/projects/{p["id"]}/render/start',{'revision':p['revision'],**extra})
                for _ in range(1200):
                    p=client.get('/api/projects/'+p['id']).json()
                    if p['job']['status']!='running':break
                    time.sleep(.2)
                assert p['job']['status']=='completed',p
                return p
            p=request('/api/projects',{'name':'固定声线 · 英文集成','script':(ROOT/'examples/en.txt').read_text(),'language':'en'})
            report['project_id']=p['id']
            p=render(p)
            original={s['id']:s['audio']['fingerprint'] for s in p['segments']}
            report['preset_generation']=p['segments']
            p=request(f'/api/projects/{p["id"]}/voice/fix',{'revision':p['revision'],'segment_id':p['segments'][0]['id'],'synthetic_reference_consent':True})
            profile=p['voice_profiles']['Narrator']
            p=render(p)
            assert all(s['status']=='ready' for s in p['segments'])
            assert all(s['audio']['reference_sha256']==profile['sha256'] for s in (p['segments'][0],p['segments'][-1]))
            assert all(s['audio']['fingerprint']==original[s['id']] for s in p['segments'][1:3])
            report['checks'].append('Fix narrator, generate both lines through Base, retain other roles unchanged')
            report['fixed_generation']=p['segments']
            p=render(p,segment_id=p['segments'][-1]['id'],force=True)
            restored=client.get('/api/projects/'+p['id']).json()
            assert restored['voice_profiles']['Narrator']==profile
            ref=ROOT/'user-data/projects'/p['id']/'references'/(profile['sha256']+'.wav')
            assert hashlib.sha256(ref.read_bytes()).hexdigest()==profile['sha256']
            report['checks'].append('Single-line retake uses unchanged preserved reference and survives reload')
            report['retake']=p['segments'][-1]
            links=request(f'/api/projects/{p["id"]}/export/create',{'revision':p['revision']})
            for path in links.values():assert client.get(path).status_code==200
            report['checks'].append('WAV, subtitles and timeline export succeed')
            report['exports']=links
            report['profile']=profile
        report['status']='PASS'
    except Exception as exc:
        traceback.print_exc();report['status']='FAIL';report['error']=str(exc)
    (ROOT/'results/fixed-voice-integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (ROOT/'results/fixed-voice-integration.md').write_text('# 固定角色声线：真实模型集成\n\n技术检查：'+report['status']+'\n\n'+ '\n'.join('- '+s for s in report['checks'])+'\n\n逐句指标、模型及参考来源、工程编号见同名 JSON。仅本轮集成检查，不将新音频冒充已经人耳验收的旧实验音频。日志保留在 user-data/fixed-voice-integration.log。\n\n最后更新：2026-09-09 · Astra\n')
    print(report['status'],report.get('project_id'),flush=True)
    return 0 if report['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())

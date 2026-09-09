"""Read back existing synthetic bilingual samples through app routes. Astra, 2026-09-09."""
import json,shutil,sys,time,uuid,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.content_check import compare_text

def main():
    records=[];sources=['c138d1570f40447fa65e4a0b7f1d00bc','2f65ff7451c94cb1a26360e9b4e513f2']
    previous=ROOT/'results/content-check-integration.json'
    if previous.exists():
        old=json.loads(previous.read_text())
        records=[{'id':r['project_id'],'language':r['language']} for r in old.get('results',[])]
        if len(records)==len(sources):sources=[]
    for sid in sources:
        source=ROOT/'user-data/projects'/sid
        p=json.loads((source/'project.json').read_text())
        p['id']=uuid.uuid4().hex;p['name']='回读检查 · '+('中文' if p['language']=='zh' else 'English')
        p['history']=[];p['future']=[];p['job']={'status':'idle'}
        for s in p['segments']:s.pop('content_check',None)
        destination=ROOT/'user-data/projects'/p['id'];destination.mkdir()
        for name in ('audio','references'):
            if (source/name).exists():shutil.copytree(source/name,destination/name)
        (destination/'project.json').write_text(json.dumps(p,ensure_ascii=False,indent=2))
        records.append({'id':p['id'],'language':p['language']})
    report={'date':'2026-09-09','synthetic_audio':True,'results':[],'status':'PASS'}
    try:
        with TestClient(create_app(),base_url='http://127.0.0.1:8765',headers={'X-VoxStage':'1'}) as client:
            report['checker_id']=client.app.state.checker.identity
            report['model']=client.app.state.checker.provenance
            for entry in records:
                p=client.get('/api/projects/'+entry['id']).json()
                assert all(s['status']=='ready' for s in p['segments'])
                originals={s['id']:s['audio']['fingerprint'] for s in p['segments']}
                r=client.post(f'/api/projects/{p["id"]}/checks/start',json={'revision':p['revision']})
                assert r.status_code==200,r.text
                for _ in range(1800):
                    p=client.get('/api/projects/'+p['id']).json()
                    if p['job']['status']!='running':break
                    time.sleep(.3)
                assert p['job']['status']=='completed',p['job']
                assert all(s['audio']['fingerprint']==originals[s['id']] for s in p['segments'])
                output={'project_id':p['id'],'language':p['language'],'job':p['job'],
                        'segments':[{'text':s['text'],'speaker':s['speaker'],'status':s['check_status'],
                                     'result':s['content_check']} for s in p['segments']]}
                links=client.post(f'/api/projects/{p["id"]}/export/create',json={'revision':p['revision']})
                assert links.status_code==200,links.text
                exported=client.get(links.json()['content-check.json'])
                assert exported.status_code==200
                output['exported_report']=exported.json()
                report['results'].append(output)
                print(entry['language'],[(s['status'],s['result']['recognized_text']) for s in output['segments']],flush=True)
            en=next(r for r in report['results'] if r['language']=='en')
            negative=compare_text('Rain never tapped against the window.',en['segments'][0]['result']['recognized_text'],'en')
            assert negative['status']=='review'
            report['controlled_negative']={'purpose':'Expected text deliberately includes an absent negation; not a measured synthesis failure',**negative}
    except Exception as exc:
        traceback.print_exc();report['status']='FAIL';report['error']=str(exc)
    (ROOT/'results/content-check-integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    lines=['# 中英文声音回读检查','',f'技术流程：{report["status"]}。差异只作复核提示，不判定为已经确认的漏读。','',
           '| 语言 | 台词 | 识别结果 | 状态 |','|---|---|---|---|']
    for r in report['results']:
        for s in r['segments']:lines.append('| '+' | '.join([r['language'],s['text'],s['result']['recognized_text'],s['status']])+' |')
    lines+=['','在独立副本中检查既有合成音，原始工程未修改；未把台词作为识别提示。逐句音频 SHA、识别模型和规则身份、差异与实测耗时见 JSON。完整日志保存在各副本的 checks 子目录。',
            '负向控制仅把对照文本加上音频中原本没有的 never，验证差异会标出；不是冒充真实的 TTS 漏读案例。',
            '未用本组样例估计检出率、误报率或语音生成正确率。仍需本人确认真实读音，以及更广样本与实际遗漏音频。','','最后更新：2026-09-09 · Astra']
    (ROOT/'results/content-check-integration.md').write_text('\n'.join(lines))
    return int(report['status']!='PASS')
if __name__=='__main__':sys.exit(main())

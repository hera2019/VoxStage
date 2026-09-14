"""Frozen bilingual attribution evaluation; no product/user project mutation. Astra 2026-09-09."""
import argparse, hashlib, json, os, platform, socket, subprocess, time, urllib.request, uuid
from pathlib import Path
from source_units import source_units,bind_labels


def speaker_pattern(text):
    """Same rule as runtime/attribution.py: a name in the text's own script, or UNKNOWN / NARRATOR."""
    import re
    if re.search('[一-鿿]', text):
        return '^([A-Za-z0-9·]{0,3}[一-鿿][一-鿿A-Za-z0-9·]{0,7}|UNKNOWN|NARRATOR)$'
    return "^([A-Za-z][A-Za-z .'\\-]{0,30}|UNKNOWN|NARRATOR)$"
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SCHEMA={'type':'object','properties':{'segments':{'type':'array','minItems':1,'items':{'type':'object','properties':{'text':{'type':'string'},'kind':{'type':'string','enum':['narration','dialogue']},'speaker':{'type':'string'}},'required':['text','kind','speaker'],'additionalProperties':False}}},'required':['segments'],'additionalProperties':False}


def score(case, content):
    result={'case':case['id'],'language':case['language'],'split':case['split'],'tags':case['tags'],'schema_valid':False,'text_preserved':False,'units':[]}
    try:
        obj=json.loads(content);parts=obj['segments']
        valid=isinstance(parts,list) and bool(parts) and all(isinstance(p,dict) and isinstance(p.get('text'),str) and p.get('kind') in ('narration','dialogue') and isinstance(p.get('speaker'),str) for p in parts)
        result['schema_valid']=valid
        if not valid:raise ValueError('Invalid segments')
        result['text_preserved']=''.join(p['text'] for p in parts)==case['text']
    except (ValueError,KeyError,TypeError):parts=[]
    labels=[]
    if result['text_preserved']:
        for part in parts:
            speaker=case.get('aliases',{}).get(part['speaker'],part['speaker'])
            labels.extend([(part['kind'],speaker)]*len(part['text']))
    offset=0
    for gold in case['gold']:
        end=offset+len(gold['text']);observed=labels[offset:end]
        kind_ok=bool(observed) and all(k==gold['kind'] for k,s in observed)
        speaker_ok=bool(observed) and all((k,s)==(gold['kind'],gold['speaker']) for k,s in observed)
        result['units'].append({'text':gold['text'],'kind':gold['kind'],'expected':gold['speaker'],'observed':sorted(set(s for k,s in observed)),'kind_correct':kind_ok,'speaker_correct':speaker_ok})
        offset=end
    return result


def summarize(rows):
    units=[u for r in rows for u in r['units']];dialogue=[u for u in units if u['kind']=='dialogue'];known=[u for u in dialogue if u['expected']!='UNKNOWN'];unknown=[u for u in dialogue if u['expected']=='UNKNOWN']
    recurring=[]
    for r in rows:
        speakers={u['expected'] for u in r['units'] if u['kind']=='dialogue' and u['expected']!='UNKNOWN'}
        for speaker in speakers:
            turns=[u for u in r['units'] if u['kind']=='dialogue' and u['expected']==speaker]
            if len(turns)>1:recurring.append(all(u['speaker_correct'] for u in turns))
    return {'cases':len(rows),'schema_valid':sum(r['schema_valid'] for r in rows),'text_preserved':sum(r['text_preserved'] for r in rows),'kind_correct':[sum(u['kind_correct'] for u in units),len(units)],'known_dialogue_correct':[sum(u['speaker_correct'] for u in known),len(known)],'unknown_correct':[sum(u['speaker_correct'] for u in unknown),len(unknown)],'recurring_speakers_all_turns_correct':[sum(recurring),len(recurring)],'strict_case_pass':sum(all(u['speaker_correct'] for u in r['units']) for r in rows)}


def run(args):
    corpus_bytes=(HERE/'corpus.json').read_bytes();digest=hashlib.sha256(corpus_bytes).hexdigest();assert digest==(HERE/'corpus.sha256').read_text().split()[0]
    corpus=json.loads(corpus_bytes);prompt=(HERE/(args.prompt or ('prompt-anchored.txt' if args.anchored else 'prompt.txt'))).read_text();
    if args.anchored:corpus['cases']+=json.loads((HERE/'fresh-holdout.json').read_text())['cases']
    out=ROOT/'results/speaker-attribution'/args.label;out.mkdir(parents=True,exist_ok=True)
    if (out/'summary.json').exists():raise ValueError('Run already exists; use a new label rather than overwrite evidence')
    with open(args.model,'rb') as f:model_sha=hashlib.file_digest(f,'sha256').hexdigest()
    key=uuid.uuid4().hex
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    settings={'temperature':0,'seed':260909,'max_tokens':4096,'top_p':1,'frequency_penalty':0,'presence_penalty':0}
    logdir=ROOT/'user-data/speaker-attribution';logdir.mkdir(parents=True,exist_ok=True)
    log=(logdir/(args.label+'.log')).open('w')
    cmd=[args.server,'-m',args.model,'--alias',args.label,'-ngl','all','-c','16384','-np','1','--jinja','--reasoning','off','--host','127.0.0.1','--port',str(port),'--no-webui','--api-key',key]
    started=time.monotonic();proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT);rows=[];rss=[]
    def request(path,payload=None,timeout=180):
        req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)
    try:
        for _ in range(300):
            if proc.poll() is not None:raise RuntimeError('Model server failed; inspect local log')
            try:
                request('/health',timeout=1);break
            except Exception:time.sleep(.2)
        else:raise TimeoutError('Model load exceeded 60 seconds')
        load_seconds=time.monotonic()-started;print(args.label,'loaded',round(load_seconds,2),flush=True)
        for case in corpus['cases']:
            schema=SCHEMA;user_text=case['text']
            if args.anchored:
                units=source_units(case['text']);user_text=json.dumps([{'id':u['id'],'text':u['text']} for u in units],ensure_ascii=False)
                certain=bool(args.prompt and 'guess' in args.prompt)   # the best-judgement prompt adds a certainty flag
                schema={'type':'object','properties':{'labels':{'type':'array','minItems':len(units),'maxItems':len(units),'items':{'type':'object','properties':{**{'id':{'type':'string','enum':[u['id'] for u in units]},'kind':{'type':'string','enum':['narration','dialogue']},'speaker':{'type':'string','pattern':speaker_pattern(case['text'])}},**({'certain':{'type':'boolean'}} if certain else {})},'required':['id','kind','speaker']+(['certain'] if certain else []),'additionalProperties':False}}},'required':['labels'],'additionalProperties':False}
            payload={**settings,'model':args.label,'messages':[{'role':'system','content':prompt},{'role':'user','content':user_text}],'response_format':{'type':'json_schema','json_schema':{'name':'speaker_segments','schema':schema}}}
            start=time.monotonic();response={};error=None;content=''
            try:
                response=request('/v1/chat/completions',payload);content=response['choices'][0]['message']['content'] or ''
            except Exception as exc:error=type(exc).__name__+': '+str(exc)
            bound=content
            if args.anchored:
                try:bound=bind_labels(case['text'],content)
                except (ValueError,KeyError,TypeError):bound=''
            row=score(case,bound);row['seconds']=time.monotonic()-start;row['error']=error;row['finish_reason']=response.get('choices',[{}])[0].get('finish_reason');rows.append(row)
            (out/(case['id']+'.json')).write_text(json.dumps({'input':case['text'],'response':response,'score':row},ensure_ascii=False,indent=2))
            sampled=subprocess.run(['ps','-o','rss=','-p',str(proc.pid)],capture_output=True,text=True)
            if sampled.stdout.strip():rss.append(int(sampled.stdout.strip())*1024)
            print(args.label,case['id'],round(row['seconds'],2),'text',row['text_preserved'],'units',sum(u['speaker_correct'] for u in row['units']),len(row['units']),flush=True)
    finally:
        proc.terminate()
        try:proc.wait(timeout=15)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        log.close()
    result={'mode':'source_bound' if args.anchored else 'free_text','extra_corpus_sha256':hashlib.sha256((HERE/'fresh-holdout.json').read_bytes()).hexdigest() if args.anchored else None,'label':args.label,'model_file':Path(args.model).name,'model_sha256':model_sha,'corpus_sha256':digest,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'llama_cpp_commit':args.build_commit,'platform':platform.platform(),'settings':settings,'context':8192,'json_schema_constrained':True,'load_seconds_measured':load_seconds,'max_rss_sample_after_requests_bytes':max(rss,default=0),'memory_note':'Sampled process RSS, not GPU allocation or full machine peak.','request_seconds_measured':sum(r['seconds'] for r in rows),'all':summarize(rows),'by_language':{lang:summarize([r for r in rows if r['language']==lang]) for lang in ('zh','en')},'by_split':{split:summarize([r for r in rows if r['split']==split]) for split in ('development','heldout','fresh_holdout')},'rows':rows}
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:result[k] for k in ('label','all','request_seconds_measured')},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--anchored',action='store_true');p.add_argument('--prompt',default=None,help='prompt file name under evals/speaker_attribution (default: prompt-anchored.txt / prompt.txt)');p.add_argument('--model',required=True);p.add_argument('--server',required=True);p.add_argument('--label',required=True);p.add_argument('--build-commit',required=True);run(p.parse_args())
# 最后更新：2026-09-09 · Astra

"""Prepare pinned local voices or verify offline. Astra, 2026-09-09."""
import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOKENIZER_SHA='836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258'
MODELS={
    'preset':{'folder':'qwen-customvoice','repo':'mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16',
              'revision':'6415d95f88be018ff9e46813119dc3bc12261328',
              'sha256':{'model.safetensors':'e6eb20e645c5a28ee66bf8434edb5b67a5f151530dab63afe22787d71bcf5382',
                        'speech_tokenizer/model.safetensors':TOKENIZER_SHA}},
    'base':{'folder':'qwen-base','repo':'mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16',
            'revision':'1eccf1cb2519b5a4e8a95b5f0544f3303568164f',
            'sha256':{'model.safetensors':'d7c7ed3e3464e3e59de0f955b3755891fa8319ff061c3f0307fe2e1343bc122d',
                      'speech_tokenizer/model.safetensors':TOKENIZER_SHA}},
}
REQUIRED=['config.json','tokenizer_config.json','vocab.json','merges.txt',
          'speech_tokenizer/config.json','speech_tokenizer/configuration.json']


def verify_files(folder, spec):
    problems=[]
    for name in REQUIRED:
        if not (folder/name).is_file():problems.append('缺少文件：'+name)
    for name,expected in spec['sha256'].items():
        path=folder/name
        if not path.is_file():
            problems.append('缺少权重：'+name)
            continue
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:
                problems.append('权重校验不一致：'+name)
    return problems


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)


def prepare(kind, root=ROOT, verify_only=False, downloader=None):
    spec=MODELS[kind]
    folder=Path(root)/'user-data/models'/spec['folder']
    problems=verify_files(folder,spec)
    provenance={k:spec[k] for k in ('repo','revision','sha256')}
    record=folder/'voxstage-model.json'
    registered=True
    if kind=='preset':
        try:
            data=json.loads(record.read_text())
            registered=all(data.get(k)==v for k,v in provenance.items())
        except (OSError,ValueError,AttributeError):
            registered=False
    if verify_only:
        if not registered:problems.append('预设模型记录未就绪，请运行不带 --verify-only 的设置命令。')
        return {'model':kind,'ready':not problems,'problems':problems,'downloaded':False,'read_only':True}
    # The development Base model is shared: never repair or download into a link target.
    if folder.is_symlink() and (problems or not registered):
        raise ValueError('共享模型链接不完整或登记不匹配，请修复共享来源；未覆盖链接或目标。\n'+'\n'.join(problems))
    downloaded=False
    if problems:
        os.environ['HF_HOME']=str(Path(root)/'user-data/hf-cache')
        if downloader is None:
            from huggingface_hub import snapshot_download
            downloader=snapshot_download
        print('正在准备 '+kind+' 固定版本模型，文件只下载到本机。',flush=True)
        downloader(spec['repo'],revision=spec['revision'],local_dir=folder,
                   ignore_patterns=['*.md','.gitattributes'],
                   force_download=any(x.startswith('权重校验不一致') for x in problems))
        downloaded=True
        problems=verify_files(folder,spec)
        if problems:raise ValueError('模型未通过校验，未登记为可用：\n'+'\n'.join(problems))
    if kind=='preset' and not folder.is_symlink():write_json(record,provenance)
    # Registry stays in this checkout even when weights are in a shared directory.
    write_json(Path(root)/'user-data/model-installations'/(kind+'.json'),provenance)
    return {'model':kind,'ready':True,'problems':[],'downloaded':downloaded,'read_only':False}


def main():
    parser=argparse.ArgumentParser(description='准备预设/固定声线模型，或仅离线校验已有文件')
    parser.add_argument('--model',choices=['preset','base','all'],default='preset')
    parser.add_argument('--verify-only',action='store_true',help='只检查，不下载或修改任何文件')
    args=parser.parse_args()
    failed=False
    for kind in (['preset','base'] if args.model=='all' else [args.model]):
        try:
            result=prepare(kind,verify_only=args.verify_only)
            print(json.dumps(result,ensure_ascii=False),flush=True)
            failed=failed or not result['ready']
        except (OSError,ValueError) as exc:
            print(str(exc),flush=True);failed=True
    return int(failed)


if __name__=='__main__':
    raise SystemExit(main())

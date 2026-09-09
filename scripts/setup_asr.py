"""Install pinned local transcription weights and register an existing CLI. Astra, 2026-09-09."""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPO='ggerganov/whisper.cpp'
REVISION='5359861c739e955e79d9a303bcbc70fb988958b1'
NAME='ggml-large-v3-turbo-q5_0.bin'
SHA='394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2'
def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cli',default=shutil.which('whisper-cli'))
    args=parser.parse_args()
    if not args.cli:parser.error('Provide the path to an installed whisper.cpp whisper-cli using --cli.')
    cli=Path(args.cli).expanduser().resolve()
    if not cli.is_file() or not os.access(cli,os.X_OK):parser.error('The CLI is not executable.')
    version=subprocess.run([str(cli),'--version'],capture_output=True,text=True,timeout=20)
    if version.returncode:parser.error('The CLI version check failed.')
    folder=ROOT/'user-data/models/whisper';folder.mkdir(parents=True,exist_ok=True)
    model=folder/NAME
    if not model.exists():
        os.environ['HF_HOME']=str(ROOT/'user-data/hf-cache')
        from huggingface_hub import hf_hub_download
        hf_hub_download(REPO,NAME,revision=REVISION,local_dir=folder)
    if digest(model)!=SHA:raise SystemExit('Model checksum mismatch; installation was not registered.')
    (folder/'provenance.json').write_text(json.dumps({'repo':REPO,'revision':REVISION,'file':NAME,'sha256':SHA},indent=2))
    settings=ROOT/'user-data/asr-settings.json'
    temp=settings.with_suffix('.tmp')
    temp.write_text(json.dumps({'cli':str(cli),'model':str(model),'cli_version':(version.stdout+version.stderr).strip(),'cli_sha256':digest(cli)},indent=2))
    temp.replace(settings)
    print('Offline content checking is configured. User audio was not uploaded.')
if __name__=='__main__':main()

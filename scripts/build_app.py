#!/usr/bin/env python3
"""Build the unsigned, self-contained Apple Silicon app (stage 3; sign with sign_app.py)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MIN_MACOS = '26.2'
NATIVE_MIN_MACOS = '14.0'


def run(args, cwd=None, env=None):
    print('build: '+str(args[0])+' '+str(args[1] if len(args)>1 else ''), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def download(cache, name, spec):
    target = cache/'downloads'/(name+('.tar.xz' if name=='ffmpeg' else '.tar.gz'))
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix+'.partial')
        with urllib.request.urlopen(urllib.request.Request(spec['url'], headers={'User-Agent':'VoxStage-build'}), timeout=60) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source, output)
        temporary.rename(target)
    with target.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != spec['sha256']:
        raise RuntimeError('Source checksum mismatch: '+name)
    return target


def unpack(archive, target):
    if target.exists():
        return
    temporary = target.with_name(target.name+'.extracting')
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    with tarfile.open(archive) as source:
        source.extractall(temporary, filter='data')
    entries = list(temporary.iterdir())
    if len(entries)!=1 or not entries[0].is_dir():
        raise RuntimeError('Unexpected source archive layout')
    entries[0].rename(target)
    temporary.rmdir()


def native_tools(cache, sources, jobs):
    prefix = cache/'native'
    prefix.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET=NATIVE_MIN_MACOS,
               CC='/usr/bin/clang', CXX='/usr/bin/clang++',
               PKG_CONFIG_LIBDIR=str(prefix/'lib/pkgconfig'))
    cmake = shutil.which('cmake')
    if not cmake:
        raise RuntimeError('CMake is required on the build machine')
    records = {}
    for name, target in [('lame',None), ('ffmpeg','ffmpeg'), ('llama','llama-server'), ('whisper','whisper-cli')]:
        source = cache/'sources'/name
        unpack(download(cache,name,sources[name]),source)
        key = hashlib.sha256(json.dumps([sources[name],NATIVE_MIN_MACOS,'static-audio-v2' if name=='llama' else 'static-audio-v1'],sort_keys=True).encode()).hexdigest()
        marker = prefix/(name+'.build.json')
        if marker.exists() and json.loads(marker.read_text()).get('key')==key:
            records[name]=json.loads(marker.read_text());continue
        if name=='lame':
            flags=['--prefix='+str(prefix),'--disable-shared','--enable-static','--disable-frontend',
                   '--disable-dependency-tracking','--build=aarch64-apple-darwin','--host=aarch64-apple-darwin']
            run([source/'configure',*flags],cwd=source,env=dict(env,CFLAGS='-O2 -mmacosx-version-min='+NATIVE_MIN_MACOS))
            run(['/usr/bin/make','-j'+str(jobs)],cwd=source,env=env)
            run(['/usr/bin/make','install'],cwd=source,env=env)
        elif name=='ffmpeg':
            flags=['--prefix='+str(prefix),'--disable-autodetect','--disable-shared','--enable-static',
              '--disable-gpl','--disable-nonfree','--disable-network','--disable-doc','--disable-debug',
              '--disable-everything','--disable-avdevice','--disable-swscale','--disable-programs','--enable-ffmpeg',
              '--enable-libmp3lame','--enable-protocol=file,pipe',
              '--enable-demuxer=wav,mp3,flac,mov,ogg,aac,aiff',
              '--enable-decoder=aac,mp3,mp3float,flac,alac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,vorbis,opus',
              '--enable-encoder=libmp3lame,pcm_f32le,pcm_s16le,flac,aac',
              '--enable-muxer=wav,mp3,flac,adts,ipod,ogg',
              '--enable-parser=aac,aac_latm,mpegaudio,flac,opus,vorbis',
              '--enable-filter=atempo,aresample,aformat,anull,atrim,asetpts,concat,volume,abuffer,abuffersink',
              '--extra-cflags=-I'+str(prefix/'include')+' -mmacosx-version-min='+NATIVE_MIN_MACOS,
              '--extra-ldflags=-L'+str(prefix/'lib')+' -mmacosx-version-min='+NATIVE_MIN_MACOS]
            run([source/'configure',*flags],cwd=source,env=env)
            run(['/usr/bin/make','-j'+str(jobs)],cwd=source,env=env)
            (prefix/'bin').mkdir(exist_ok=True)
            shutil.copy2(source/'ffmpeg',prefix/'bin/ffmpeg')
        else:
            build = cache/'cmake'/name
            flags=['-DCMAKE_BUILD_TYPE=Release','-DBUILD_SHARED_LIBS=OFF',
              '-DCMAKE_OSX_ARCHITECTURES=arm64','-DCMAKE_OSX_DEPLOYMENT_TARGET='+NATIVE_MIN_MACOS,
              '-DGGML_METAL=ON','-DGGML_METAL_EMBED_LIBRARY=ON','-DGGML_NATIVE=OFF',
              '-DGGML_OPENMP=OFF','-DGGML_BLAS=OFF','-DGGML_RPC=OFF']
            if name=='llama':
                flags += ['-DLLAMA_BUILD_TESTS=OFF','-DLLAMA_BUILD_EXAMPLES=OFF',
                          '-DLLAMA_BUILD_SERVER=ON','-DLLAMA_CURL=OFF','-DLLAMA_OPENSSL=OFF',
                          '-DLLAMA_BUILD_COMMIT='+sources[name]['revision'][:7],'-DLLAMA_BUILD_NUMBER=0']
            else:
                flags += ['-DWHISPER_BUILD_TESTS=OFF','-DWHISPER_BUILD_EXAMPLES=ON',
                          '-DWHISPER_COREML=OFF','-DWHISPER_SDL2=OFF']
            run([cmake,'-S',source,'-B',build,*flags],env=env)
            run([cmake,'--build',build,'--target',target,'--parallel',str(jobs)],env=env)
            (prefix/'bin').mkdir(exist_ok=True)
            shutil.copy2(build/'bin'/target,prefix/'bin'/target)
        record={'key':key,'source':sources[name],'configure':flags}
        marker.write_text(json.dumps(record,indent=2)+'\n');records[name]=record
    return prefix,records


def application_sources(resources):
    app = resources/'app'
    app.mkdir()
    for name in ('runtime','scripts'):
        dest=app/name;dest.mkdir()
        paths=(ROOT/name).glob('*.py') if name=='runtime' else [ROOT/'scripts/setup_model.py',ROOT/'scripts/setup_asr.py']
        for source in paths:
            shutil.copy2(source,dest/source.name)
    target=app/'evals/speaker_attribution';target.mkdir(parents=True)
    for name in ('source_units.py','context_windows.py','prompt-anchored-guess.txt'):
        shutil.copy2(ROOT/'evals/speaker_attribution'/name,target/name)
    shutil.copytree(ROOT/'frontend/dist',app/'frontend/dist')
    # Only the explicitly published synthetic default pack, never the user's library.
    manifest=json.loads((ROOT/'voicepack/default/manifest.json').read_text())
    dest=app/'voicepack/default';dest.mkdir(parents=True)
    for name in ['manifest.json',*[f'{i:02d}.flac' for i in range(1,15)]]:
        shutil.copy2(ROOT/'voicepack/default'/name,dest/name)
    return app


def licenses(resources,python,cache,sources,records):
    folder=resources/'licenses';folder.mkdir()
    shutil.copy2(ROOT/'LICENSE',folder/'VoxStage-AGPL-3.0.txt')
    for name in ('llama','whisper','ffmpeg','lame'):
        archive=download(cache,name,sources[name])
        shutil.copy2(archive,folder/(name+'-source'+''.join(archive.suffixes)))
        source=cache/'sources'/name
        for pattern in ('LICENSE*','COPYING*'):
            for item in source.glob(pattern):
                if item.is_file():shutil.copy2(item,folder/(name+'-'+item.name))
    (folder/'native-build.json').write_text(json.dumps(records,indent=2)+'\n')
    with tarfile.open(folder/'VoxStage-source.tar.gz','w:gz') as archive:
        for name in ('runtime','native','scripts','frontend/src','frontend/package.json','frontend/package-lock.json','frontend/tsconfig.json','frontend/index.html','frontend/vite.config.ts','evals/speaker_attribution/source_units.py','evals/speaker_attribution/context_windows.py','evals/speaker_attribution/prompt-anchored-guess.txt','requirements.lock.txt','LICENSE'):
            source=ROOT/name
            if source.exists():archive.add(source,arcname=name,filter=lambda info: None if '__pycache__' in info.name else info)
    code="""import importlib.metadata,json
print(json.dumps([{'name':d.metadata['Name'],'version':d.version,'license':d.metadata.get('License-Expression') or d.metadata.get('License'),'license_files':[str(f) for f in (d.files or []) if 'license' in str(f).lower() or 'copying' in str(f).lower()]} for d in importlib.metadata.distributions()],ensure_ascii=False,indent=2))"""
    info=subprocess.check_output([python,'-I','-c',code],text=True)
    (folder/'python-packages.json').write_text(info)
    # Package license texts remain in site-packages; list makes them discoverable.
    for item in (resources/'python').rglob('LICENSE*'):
        if item.is_file() and 'site-packages' not in str(item):
            shutil.copy2(item,folder/('Python-'+item.name));break
    (folder/'README.txt').write_text('VoxStage: AGPL-3.0; source: https://github.com/hera2019/VoxStage\n'
      'FFmpeg is built without GPL/nonfree components; FFmpeg and LAME source archives and exact configure flags are included.\n'
      'llama.cpp and whisper.cpp: MIT; corresponding sources and licenses included.\n'
      'Python package license files: ../python/lib/python3.12/site-packages; index: python-packages.json.\n'
      'Models are not bundled; model licenses are shown on the download page.\n')


def relocate_wheels(resources):
    """Remove unused GCC build paths and fix SciPy's own library IDs.

    Their dependencies already point at sibling, bundled libraries. Changes
    are recorded and performed before Developer ID signing (stage 4).
    """
    scipy=resources/'python/lib/python3.12/site-packages/scipy'
    changes=[]
    extension=scipy/'linalg/_fblas.cpython-312-darwin.so'
    loads=subprocess.check_output(['/usr/bin/otool','-arch','arm64','-l',extension],text=True)
    for line in loads.splitlines():
        if not line.strip().startswith('path '):continue
        rpath=line.strip().split(' (')[0][5:]
        if rpath.startswith('/opt/homebrew/Cellar/gcc@13/'):
            run(['/usr/bin/install_name_tool','-delete_rpath',rpath,extension])
            changes.append({'file':str(extension.relative_to(resources)),'removed_unused_rpath':rpath})
    altered=[extension] if changes else []
    for name in ('libgfortran.5.dylib','libquadmath.0.dylib','libgcc_s.1.1.dylib'):
        path=scipy/'.dylibs'/name
        run(['/usr/bin/install_name_tool','-id','@rpath/'+name,path])
        changes.append({'file':str(path.relative_to(resources)),'install_name':'@rpath/'+name})
        altered.append(path)
    # Mach-O header edits invalidate the wheel's ad hoc signature on arm64.
    for path in altered:run(['/usr/bin/codesign','--force','--sign','-',path])
    return changes


def audit(app):
    """Fail packaging if a Mach-O needs libraries outside the app/system."""
    binaries=[];failures=[]
    for path in app.rglob('*'):
        if not path.is_file() or path.is_symlink():continue
        with path.open('rb') as stream:magic=stream.read(4)
        if magic not in (b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'):continue
        result=subprocess.check_output(['/usr/bin/otool','-arch','arm64','-L',path],text=True)
        dependencies=[]
        for line in result.splitlines()[1:]:
            dependency=line.strip().split(' (')[0];dependencies.append(dependency)
            if dependency.startswith('/') and not dependency.startswith(('/usr/lib/','/System/Library/')):
                failures.append({'file':str(path.relative_to(app)),'dependency':dependency})
        loads=subprocess.check_output(['/usr/bin/otool','-arch','arm64','-l',path],text=True)
        rpaths=[line.strip().split(' (')[0][5:] for line in loads.splitlines() if line.strip().startswith('path ')]
        for rpath in rpaths:
            if rpath.startswith('/') and not rpath.startswith(('/usr/lib/','/System/Library/')):
                failures.append({'file':str(path.relative_to(app)),'rpath':rpath})
        binaries.append({'file':str(path.relative_to(app)),'dependencies':dependencies})
    return {'binaries':binaries,'failures':failures}


def main():
    parser=argparse.ArgumentParser(description='Build unsigned VoxStage.app; no model download')
    parser.add_argument('--cache',type=Path,default=ROOT/'user-data/installer-build')
    parser.add_argument('--output',type=Path,default=ROOT/'user-data/installer-build/dist/VoxStage.app')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--native-only',action='store_true')
    args=parser.parse_args()
    if platform.system()!='Darwin' or platform.machine()!='arm64':parser.error('Build on an Apple Silicon Mac')
    if not 1<=args.jobs<=4:parser.error('Use 1–4 compile jobs')
    started=time.monotonic();sources=json.loads((ROOT/'scripts/installer-sources.json').read_text())
    prefix,records=native_tools(args.cache,sources,args.jobs)
    if args.native_only:return
    output=args.output.resolve()
    if output.name!='VoxStage.app' or output.exists():
        raise RuntimeError('Choose a new output path named VoxStage.app; existing output is never deleted')
    if shutil.disk_usage(args.cache).free < 3*1024**3:raise RuntimeError('Need 3 GB free to assemble the app')
    resources=output/'Contents/Resources';macos=output/'Contents/MacOS';macos.mkdir(parents=True);resources.mkdir()
    unpack(download(args.cache,'python',sources['python']),resources/'python')
    python=resources/'python/bin/python3'
    # Developer-only test dependencies are removed from the production lock.
    lock=resources/'requirements-runtime.txt'
    lock.write_text('\n'.join(line for line in (ROOT/'requirements.lock.txt').read_text().splitlines()
                              if line.strip() and line.split('==')[0] not in ('pytest','iniconfig','pluggy'))+'\n')
    run([python,'-I','-m','pip','install','--only-binary=:all:','--no-compile','-r',lock],
        env=dict(os.environ,PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_NO_INPUT='1'))
    run([python,'-I','-m','pip','check'])
    run(['npm','ci','--ignore-scripts'],cwd=ROOT/'frontend')
    run(['npm','run','build'],cwd=ROOT/'frontend')
    application_sources(resources)
    shutil.copytree(prefix/'bin',resources/'bin')
    run(['/usr/bin/xcrun','swiftc','-swift-version','5','-O','-target','arm64-apple-macos'+MIN_MACOS,
         ROOT/'native/VoxStage.swift','-o',macos/'VoxStage','-framework','Cocoa','-framework','WebKit'])
    shutil.copy2(ROOT/'native/Info.plist',output/'Contents/Info.plist')
    iconset=args.cache/'AppIcon.iconset'
    if iconset.exists():shutil.rmtree(iconset)
    run(['/usr/bin/xcrun','swift',ROOT/'native/AppIcon.swift',iconset])
    run(['/usr/bin/iconutil','-c','icns',iconset,'-o',resources/'AppIcon.icns'])
    licenses(resources,python,args.cache,sources,records)
    relocations=relocate_wheels(resources)
    # No first-run bytecode writes inside a signed app.
    run([python,'-I','-m','compileall','-q','-j','1',resources/'app'])
    report=audit(output)
    (args.cache/'binary-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['failures']:raise RuntimeError('Binary audit failed; see binary-audit.json')
    manifest={'stage':3,'signed_for_distribution':False,'minimum_macos':MIN_MACOS,'architecture':'arm64',
              'sources':sources,'build_seconds':round(time.monotonic()-started,2),
              'app_bytes':sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and not p.is_symlink()),
              'mach_o_count':len(report['binaries']),'binary_relocations':relocations}
    (resources/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(manifest,output=str(output)),indent=2),flush=True)


if __name__=='__main__':main()

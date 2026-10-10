"""User-selected old data import. Source stays read-only; restoration uses packages."""
import json
from pathlib import Path
import re
import shutil
import time
import uuid

from . import packages
from .project_settings import effective

ID = re.compile(r'[0-9a-f]{32}')
# project.json keeps up to 40 full undo snapshots, so an ordinary chapter with
# checks reaches tens of MB (a real 94-line project: 31 MB). This only guards
# against reading something that is not a VoxStage record. Claude Hera, 2026-10-10.
MAX_RECORD = 256*1024**2


def read_json(path):
    if path.stat().st_size > MAX_RECORD:
        raise ValueError('旧工程记录太大，无法导入。')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):
        raise ValueError('旧工程记录无法读取。')
    return value


def fingerprint(root):
    """Models, settings, access keys and logs are deliberately outside the import."""
    files={}
    for name in ('projects','books','voices','projects-role-drafts'):
        folder=root/name
        if folder.is_symlink():
            raise ValueError('旧数据含文件链接，请选择普通数据文件夹。')
        for path in folder.rglob('*') if folder.is_dir() else []:
            if path.is_symlink():
                raise ValueError('旧数据含文件链接，请选择普通数据文件夹。')
            if path.is_file():
                stat=path.stat();files[path.relative_to(root).as_posix()]=(stat.st_size,stat.st_mtime_ns)
    return files


class ReadOnlyVoices:
    def __init__(self,root):self.root=root
    def get(self,voice_id):
        if not ID.fullmatch(voice_id):raise ValueError('旧工程音色编号无效。')
        record=read_json(self.root/(voice_id+'.json'))
        if record.get('id')!=voice_id or record.get('sha256')!=packages._sha(self.audio_path(voice_id)):
            raise ValueError('旧音色记录与声音文件不一致，请先修复。')
        return record
    def audio_path(self,voice_id):
        if not ID.fullmatch(voice_id):raise ValueError('旧工程音色编号无效。')
        return self.root/(voice_id+'.wav')


class LegacyImporter:
    def __init__(self,store,books,library,drafts_root):
        self.store,self.books,self.library,self.drafts_root=store,books,library,Path(drafts_root)
        self.previews={}

    def preview(self,source):
        root=Path(source).expanduser().resolve()
        destination=self.store.root.parent.resolve()
        if root==destination or root.is_relative_to(destination) or destination.is_relative_to(root):
            raise ValueError('旧数据与当前数据目录不能相同或互相包含。')
        if not (root/'projects').is_dir():
            raise ValueError('请选择含 projects 文件夹的旧 user-data 文件夹。')
        files=fingerprint(root)
        total=sum(v[0] for v in files.values())
        if total>packages.MAX_BYTES:
            raise ValueError('旧数据超过 8 GB，请先在开发版按工程导出备份包。')
        projects={}
        for path in sorted((root/'projects').glob('*/project.json')):
            if not ID.fullmatch(path.parent.name):continue
            record=read_json(path)
            if record.get('id')!=path.parent.name or not isinstance(record.get('segments'),list):
                raise ValueError('旧工程编号或内容不匹配。')
            packages.upgrade('project',record)
            projects[record['id']]=record
        books={}
        for path in sorted((root/'books').glob('*.json')):
            if not ID.fullmatch(path.stem):continue
            record=read_json(path)
            if record.get('id')!=path.stem:raise ValueError('旧主工程编号不匹配。')
            packages.upgrade('book',record)
            members=record.get('members',[])
            if not isinstance(members,list) or len(set(members))!=len(members):
                raise ValueError('旧主工程章节清单无效。')
            if any(mid not in projects for mid in members):
                raise ValueError('旧主工程缺少章节，请先在开发版修复。')
            books[record['id']]=record
        if not projects and not books:raise ValueError('这个文件夹没有可导入的工程。')
        used=set();groups=[];views={}
        for bid,book in books.items():
            members=book.get('members',[])
            if any(mid in used or (projects[mid].get('book') or {}).get('id')!=bid for mid in members):
                raise ValueError('旧主工程与章节关联不一致。')
            used.update(members)
            groups.append(dict(kind='book',book=book,projects=[projects[mid] for mid in members]))
        for pid,project in projects.items():
            parent=books.get((project.get('book') or {}).get('id'))
            views[pid]=effective(project,parent)
            if pid not in used:groups.append(dict(kind='project',book=None,projects=[project]))
        source_library=ReadOnlyVoices(root/'voices')
        # A voice deleted from the old library cannot come back. A project whose
        # current lines use one does not open in the development version either,
        # so it is named and left out (its whole main project, if a chapter);
        # everything else imports. Undo history alone does not count.
        missing={vid for vid in packages._voice_ids(list(views.values()),list(books.values()))
                 if not (root/'voices'/(vid+'.json')).is_file() or not source_library.audio_path(vid).is_file()}
        broken={pid for pid,view in views.items()
                if missing & set(packages._voice_ids({k:v for k,v in view.items() if k not in ('history','future')}))}
        skipped=[(g['book'] or {}).get('title') or (g['projects'][0].get('name') or g['projects'][0]['id'])
                 for g in groups if any(p['id'] in broken for p in g['projects'])]
        groups=[g for g in groups if not any(p['id'] in broken for p in g['projects'])]
        kept={p['id'] for g in groups for p in g['projects']}
        projects={pid:p for pid,p in projects.items() if pid in kept}
        books={bid:b for bid,b in books.items() if any(g['book'] is b for g in groups)}
        views={pid:v for pid,v in views.items() if pid in kept}
        if not groups:raise ValueError('旧工程用到的音色已被删除，开发版也无法打开，没有可导入的工程。')
        voice_ids=[vid for vid in packages._voice_ids(list(views.values()),list(books.values())) if vid not in missing]
        provided=[]
        for vid in voice_ids:
            voice=source_library.get(vid)
            if voice.get('source')=='provided':provided.append(voice.get('name') or vid)
        conflicts=[p.get('name') or pid for pid,p in projects.items() if (self.store.root/pid).exists()]
        conflicts += [b.get('title') or bid for bid,b in books.items() if (self.books.root/(bid+'.json')).exists() or (self.books.root/(bid+'.assets')).exists()]
        for project in projects.values():
            for did in packages._draft_ids(project):
                source=root/'projects-role-drafts'/(did+'.json');target=self.drafts_root/(did+'.json')
                if source.is_file() and target.is_file() and source.read_bytes()!=target.read_bytes():
                    conflicts.append(project.get('name') or project['id'])
        # Reusing an existing voice ID is safe only if both references are identical.
        for vid in voice_ids:
            if (self.library.root/(vid+'.json')).exists():
                if self.library.get(vid).get('sha256') != source_library.get(vid).get('sha256'):
                    raise ValueError('同编号音色内容不同，请先在开发版重新建立音色。')
        now=time.time()
        self.previews={k:v for k,v in self.previews.items() if v['created']>now-1800}
        identifier=uuid.uuid4().hex
        self.previews[identifier]=dict(root=root,files=files,groups=groups,views=views,
             provided=provided,conflicts=conflicts,bytes=total,voices=voice_ids,created=now)
        return dict(import_id=identifier,projects=[dict(id=pid,name=p.get('name','')) for pid,p in projects.items()],
             books=len(books),bytes=total,voices=len(voice_ids),provided_recordings=provided,conflicts=conflicts,
             skipped=skipped)

    def commit(self,identifier,*,as_copy=False,consent=False):
        plan=self.previews.get(identifier)
        if not plan or time.time()-plan['created']>1800:
            raise ValueError('导入预览已过期，请重新选择文件夹。')
        if plan['conflicts'] and not as_copy:
            raise packages.Conflict(plan['conflicts'])
        if plan['provided'] and not consent:
            raise packages.NeedsConsent(plan['provided'])
        if fingerprint(plan['root'])!=plan['files']:
            raise ValueError('旧文件已改变，请重新选择文件夹。')
        if shutil.disk_usage(self.store.root).free < 2*plan['bytes']+512*1024**2:
            raise ValueError('导入需要更多磁盘空间，请释放空间后重试。')
        cache=self.store.root.parent/'legacy-import-cache'/uuid.uuid4().hex
        cache.mkdir(parents=True)
        paths=[];results=[];placed=[]
        source_library=ReadOnlyVoices(plan['root']/'voices')
        before_voices=set(self.library.root.glob('*'))
        before_drafts=set(self.drafts_root.glob('*'))
        try:
            # Validate every package before publishing any project.
            for i,group in enumerate(plan['groups']):
                book=group['book'];path=cache/(str(i)+'.voxstage')
                packages.build(path,kind=group['kind'],projects=group['projects'],book=book,
                  book_assets=plan['root']/'books'/((book or {}).get('id','')+'.assets'),
                  directory_of=lambda pid:plan['root']/'projects'/pid,library=source_library,
                  drafts_root=plan['root']/'projects-role-drafts',views=plan['views'],
                  reference_file=lambda project,sha: plan['root']/'books'/(((project.get('book') or {}).get('id') or '')+'.assets')/'references'/(sha+'.wav'))
                packages.read(path);paths.append(path)
            with self.store.lock:
                try:
                    for path in paths:
                        result=packages.restore(path,store=self.store,books=self.books,library=self.library,
                           drafts_root=self.drafts_root,as_copy=as_copy,consent=consent)
                        results.append(result)
                        placed.extend(self.store.root/pid for pid in result['projects'])
                        if result.get('book_id'):
                            placed += [self.books.root/(result['book_id']+'.json'),self.books.root/(result['book_id']+'.assets')]
                except Exception:
                    for path in reversed(placed):
                        if path.is_dir():shutil.rmtree(path)
                        else:path.unlink(missing_ok=True)
                    for path in set(self.library.root.glob('*'))-before_voices:path.unlink(missing_ok=True)
                    for path in set(self.drafts_root.glob('*'))-before_drafts:path.unlink(missing_ok=True)
                    raise
            self.previews.pop(identifier,None)
            return dict(projects=[pid for r in results for pid in r['projects']],
                        books=sum(g['book'] is not None for g in plan['groups']),copy=as_copy)
        finally:
            shutil.rmtree(cache)

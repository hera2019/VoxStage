"""Versioned settings resolution. Raw records are for writes, effective views for work.

No migration on read. Only newly opted-in projects inherit missing fields;
legacy projects preserve the defaults that their audio was generated with.
Resolve once at the operation boundary and pass the same view to consumers.
"""
from copy import deepcopy

SETTINGS_SCHEMA = 1
VIEW_KEY = '_effective_settings'
# Maps stay keyed by speaker NAME in v1. Lexicon is a whole-field override,
# not a speaker map. Empty maps/lists and zero are explicit, never inheritance.
ROLE_MAPS = ('voices', 'voice_profiles', 'colors', 'sexes', 'crowds')
LEGACY_DEFAULTS = {
    'preset_model': '0.6B', 'clone_model': '0.6B', 'pause_ms': 250,
    'speech_rate': 1.0, 'ellipsis_pause_ms': 0, 'color_scope': 'both',
    'lexicon': {}, 'muted_speakers': [], **{key: {} for key in ROLE_MAPS},
}
SETTING_KEYS = tuple(LEGACY_DEFAULTS)


def application_defaults(*, preset_model='0.6B', clone_model='0.6B'):
    """New-record defaults: caller supplies the installed-model choices."""
    return {**deepcopy(LEGACY_DEFAULTS), 'preset_model': preset_model,
            'clone_model': clone_model, 'ellipsis_pause_ms': 500}


def assert_raw(project):
    if VIEW_KEY in project:
        raise ValueError('有效工程视图不能写回；请保存原始工程及明确修改的设置。')


def _settings(mapping):
    unknown = set(mapping) - set(SETTING_KEYS)
    if unknown:
        raise ValueError('未知设置项：' + ', '.join(sorted(unknown)))
    for key in (*ROLE_MAPS, 'lexicon'):
        if key in mapping and not isinstance(mapping[key], dict):
            raise ValueError(f'{key} 必须是映射，清空请用空映射。')
    if any(value is None for value in mapping.values()):
        raise ValueError('继承请移除覆盖项；不要用 null 表示继承。')
    return deepcopy(mapping)


def effective(project, book=None, *, defaults=None):
    """Deep, detached dict for existing fingerprint/spoken_text/export consumers.

    Nonempty role maps overlay roles by name; an explicit empty map clears the
    whole inherited map. Other settings (including lexicon) replace wholesale.
    Provenance is carried in VIEW_KEY; it is never part of a persisted project.
    """
    assert_raw(project)
    schema = project.get('settings_schema')
    if schema not in (None, SETTINGS_SCHEMA):
        raise ValueError('不支持的工程设置版本。')
    view = deepcopy(project)
    sources = {}
    if schema is None:
        # A book link in an old project did not mean live inheritance.
        for key, value in LEGACY_DEFAULTS.items():
            view.setdefault(key, deepcopy(value))
            sources[key] = {'level': 'project' if key in project else 'legacy_default',
                            'id': project.get('id') if key in project else None}
        book_revision = None
    else:
        parent_id = (project.get('book') or {}).get('id')
        if parent_id and (not book or book.get('id') != parent_id):
            raise ValueError('找不到匹配的主工程；请恢复关联或先固化设置再脱离。')
        if book is not None and not parent_id:
            raise ValueError('独立工程不能读取无关主工程的设置。')
        base = application_defaults()
        base.update(_settings(defaults or {}))
        layers = [('application', None, base)]
        if book is not None:
            layers.append(('book', book['id'], _settings(book.get('settings', {}))))
        layers.append(('project', project.get('id'), _settings(
            {key: project[key] for key in SETTING_KEYS if key in project})))
        for level, owner, settings in layers:
            for key, value in settings.items():
                source = {'level': level, 'id': owner}
                if key in ROLE_MAPS:
                    if not value or key not in sources:
                        view[key] = {}
                        sources[key] = {**source, 'roles': {}}
                    # Copy before overlay; no sibling or book shares mutable values.
                    view[key] = {**view[key], **deepcopy(value)}
                    roles = sources[key]['roles']
                    roles.update({name: dict(source) for name in value})
                    sources[key] = {**source, 'roles': roles}
                else:
                    view[key] = deepcopy(value)
                    sources[key] = source
        book_revision = book.get('revision', 0) if book else None
    view[VIEW_KEY] = {'project_revision': project.get('revision', 0),
                      'book_revision': book_revision, 'sources': sources}
    return view


def initialize(project, *, book=None, defaults=None, copy_from=None):
    """Build a raw new-record settings state; no writes or resource copies.

    copy_from must be an already resolved view. Use reference_requirements()
    and copy/verify those assets in the transaction before publishing a record.
    """
    assert_raw(project)
    result = deepcopy(project)
    for key in SETTING_KEYS:
        result.pop(key, None)
    result['settings_schema'] = SETTINGS_SCHEMA
    if book:
        result['book'] = {'id': book['id'], 'title': book['title']}
    elif result.get('book'):
        raise ValueError('新工程关联了主工程，但未提供该主工程。')
    if copy_from is not None:
        if VIEW_KEY not in copy_from:
            raise ValueError('复制设置前必须解析来源工程的有效设置。')
        result.update({key: deepcopy(copy_from[key]) for key in SETTING_KEYS})
    elif not book:
        values = application_defaults()
        values.update(_settings(defaults or {}))
        result.update(values)
    return result


def reference_requirements(view):
    """Describe fixed-voice assets that adapters must retain/copy; never guess paths."""
    if VIEW_KEY not in view:
        raise ValueError('请先解析有效工程视图。')
    sources = view[VIEW_KEY]['sources']['voice_profiles']
    return [{'speaker': name, 'profile': deepcopy(profile),
             'owner': deepcopy(sources.get('roles', {}).get(name, sources))}
            for name, profile in view['voice_profiles'].items() if profile]

#!/usr/bin/env python3
"""Stage 4: Developer ID signing, notarization and DMG for a built VoxStage.app.

Signs every Mach-O inside-out with the Hardened Runtime and a secure timestamp,
then the bundle. With --notary-profile, the app is notarized and stapled before
it goes into the DMG, and the DMG is notarized and stapled too, so both work
offline on first open. Credentials are never read here: the profile must be
stored beforehand by the developer with `xcrun notarytool store-credentials`.
Claude Hera, 2026-10-10.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
ENTITLEMENTS = ROOT/'native/VoxStage.entitlements'
MACH_O = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}
MH_EXECUTE = 2


def run(args, **kwargs):
    print('sign: '+' '.join(map(str, args[:3]))+(' …' if len(args) > 3 else ''), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def mach_o_files(app):
    """(path, is_executable) for every regular Mach-O file, deepest first."""
    found = []
    for path in app.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            header = stream.read(16)
        if header[:4] not in MACH_O:
            continue
        if header[:4] == b'\xcf\xfa\xed\xfe':
            executable = struct.unpack('<I', header[12:16])[0] == MH_EXECUTE
        else:  # fat or big-endian: fall back to the file mode
            executable = os.access(path, os.X_OK) and path.suffix not in ('.so', '.dylib')
        found.append((path, executable))
    found.sort(key=lambda item: (-len(item[0].parts), str(item[0])))
    return found


def sign(paths, identity, entitlements=None):
    base = ['/usr/bin/codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', identity]
    if entitlements:
        base += ['--entitlements', entitlements]
    for start in range(0, len(paths), 40):
        run(base+paths[start:start+40])


def notarize(path, profile):
    result = run(['/usr/bin/xcrun', 'notarytool', 'submit', path, '--keychain-profile', profile,
                  '--wait', '--output-format', 'json'], capture_output=True, text=True)
    outcome = json.loads(result.stdout)
    if outcome.get('status') != 'Accepted':
        log = subprocess.run(['/usr/bin/xcrun', 'notarytool', 'log', outcome.get('id', ''),
                              '--keychain-profile', profile], capture_output=True, text=True).stdout
        raise RuntimeError('Notarization not accepted: '+json.dumps(outcome)+'\n'+log)
    return outcome


def verify(app):
    checks = {}
    for name, args in [('codesign', ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', app]),
                       ('spctl', ['/usr/sbin/spctl', '-a', '-vv', '-t', 'exec', app]),
                       ('stapler', ['/usr/bin/xcrun', 'stapler', 'validate', app])]:
        result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
        checks[name] = {'ok': result.returncode == 0, 'output': (result.stdout+result.stderr).strip()}
    return checks


def make_dmg(app, dmg):
    with tempfile.TemporaryDirectory(prefix='voxstage-dmg-') as folder:
        stage = Path(folder)/'VoxStage'
        stage.mkdir()
        run(['/usr/bin/ditto', app, stage/'VoxStage.app'])
        (stage/'Applications').symlink_to('/Applications')
        run(['/usr/bin/hdiutil', 'create', '-volname', 'VoxStage', '-srcfolder', stage,
             '-fs', 'HFS+', '-format', 'ULFO', '-ov', dmg])


def main():
    parser = argparse.ArgumentParser(description='Sign, notarize and package VoxStage.app as a DMG')
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--identity', default='Developer ID Application: HOUJUN CO., LTD. (B5BHSSN4W6)')
    parser.add_argument('--notary-profile', help='keychain profile stored with notarytool store-credentials')
    parser.add_argument('--dmg', type=Path, help='output DMG (must not exist); default next to the app')
    args = parser.parse_args()
    app = args.app.resolve()
    if app.name != 'VoxStage.app' or not (app/'Contents/Info.plist').exists():
        parser.error('Pass a built VoxStage.app')
    version = subprocess.check_output(['/usr/bin/defaults', 'read', app/'Contents/Info.plist',
                                       'CFBundleShortVersionString'], text=True).strip()
    dmg = (args.dmg or app.parent/f'VoxStage-{version}-arm64.dmg').resolve()
    if dmg.exists():
        parser.error('DMG already exists; existing output is never overwritten: '+str(dmg))
    started = time.monotonic()

    # Record the signing inside the bundle; sealed by the bundle signature below.
    manifest_path = app/'Contents/Resources/build-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest.update(stage=4, signed_for_distribution=True, signing_identity=args.identity,
                    hardened_runtime=True, notarized=bool(args.notary_profile))
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')

    files = mach_o_files(app)
    main_executable = app/'Contents/MacOS/VoxStage'
    libraries = [path for path, executable in files if not executable]
    tools = [path for path, executable in files if executable and path != main_executable]
    sign(libraries, args.identity)
    sign(tools, args.identity, ENTITLEMENTS)
    sign([app], args.identity, ENTITLEMENTS)
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])

    notarized = {}
    if args.notary_profile:
        with tempfile.TemporaryDirectory(prefix='voxstage-notary-') as folder:
            archive = Path(folder)/'VoxStage.zip'
            run(['/usr/bin/ditto', '-c', '-k', '--keepParent', app, archive])
            notarized['app'] = notarize(archive, args.notary_profile)
        run(['/usr/bin/xcrun', 'stapler', 'staple', app])

    make_dmg(app, dmg)
    sign([dmg], args.identity)
    if args.notary_profile:
        notarized['dmg'] = notarize(dmg, args.notary_profile)
        run(['/usr/bin/xcrun', 'stapler', 'staple', dmg])

    report = {'app': str(app), 'dmg': str(dmg), 'identity': args.identity,
              'signed_libraries': len(libraries), 'signed_executables': len(tools)+1,
              'entitlements': ENTITLEMENTS.read_text(), 'notarized': notarized or None,
              'dmg_bytes': dmg.stat().st_size, 'seconds': round(time.monotonic()-started, 1),
              'checks': verify(app)}
    report_path = dmg.with_suffix('.sign-report.json')
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'entitlements'}, indent=2, ensure_ascii=False))
    if not args.notary_profile:
        print('Not notarized: Gatekeeper will reject this DMG on other Macs until --notary-profile is used.')


if __name__ == '__main__':
    main()

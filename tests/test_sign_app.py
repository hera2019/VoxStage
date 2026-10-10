import importlib.util
from pathlib import Path
import plistlib
import struct

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sign_app', ROOT/'scripts/sign_app.py')
sign_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sign_app)


def mach_o(path, filetype, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\xcf\xfa\xed\xfe'+struct.pack('<III', 0x0100000c, 0, filetype)+b'\0'*16)
    path.chmod(mode)


def test_mach_o_files_are_classified_and_signed_deepest_first(tmp_path):
    app = tmp_path/'VoxStage.app'
    mach_o(app/'Contents/MacOS/VoxStage', sign_app.MH_EXECUTE, 0o755)
    mach_o(app/'Contents/Resources/python/lib/site-packages/pkg/_ext.so', 8, 0o755)  # MH_BUNDLE
    mach_o(app/'Contents/Resources/python/lib/libpython3.12.dylib', 6)  # MH_DYLIB
    mach_o(app/'Contents/Resources/bin/ffmpeg', sign_app.MH_EXECUTE, 0o755)
    (app/'Contents/Resources/app.py').write_text('print(1)\n')
    (app/'Contents/Resources/link').symlink_to('bin/ffmpeg')
    found = sign_app.mach_o_files(app)
    names = [path.name for path, _ in found]
    assert names[0] == '_ext.so' and 'app.py' not in names and 'link' not in names
    kinds = {path.name: executable for path, executable in found}
    assert kinds == {'_ext.so': False, 'libpython3.12.dylib': False, 'ffmpeg': True, 'VoxStage': True}


def test_entitlements_stay_empty_unless_a_need_is_shown():
    # Hardened Runtime ran MLX on Metal, ctypes callbacks, llama-server and
    # whisper-cli without exceptions (2026-10-10); each one added widens attack surface.
    assert plistlib.loads(sign_app.ENTITLEMENTS.read_bytes()) == {}


def test_info_plist_names_the_icon_the_build_produces():
    info = plistlib.loads((ROOT/'native/Info.plist').read_bytes())
    assert info['CFBundleIconFile'] == 'AppIcon'
    assert "'AppIcon.icns'" in (ROOT/'scripts/build_app.py').read_text()


def test_info_plist_declares_chinese_so_the_page_follows_the_system():
    # Without it a Chinese Mac got an English page and English file panels (2026-10-10).
    info = plistlib.loads((ROOT/'native/Info.plist').read_bytes())
    assert info['CFBundleLocalizations'] == ['en', 'zh-Hans']

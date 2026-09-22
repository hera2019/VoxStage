"""Reaching this machine's VoxStage from a phone or an iPad on the same network
(本人 2026-09-22: 局域网访问，口令保护 + 完整功能). Off unless the service is
started with `--lan`: then it listens on every interface and every request from
an address other than this machine must carry the key — typed once on a small
page, kept in a cookie afterwards. The key lives beside the work in
`user-data/lan-key.txt`, readable only by its owner, so a phone's bookmark keeps
working across restarts. Claude Hera."""
import hashlib
import hmac
import html
import secrets
import socket
from pathlib import Path

KEY_FILE = 'lan-key.txt'
COOKIE = 'voxstage_lan'
COOKIE_DAYS = 30
LOOPBACK = ('127.0.0.1', 'localhost', '::1', '[::1]')


def is_loopback(hostname):
    return hostname in LOOPBACK


def load_or_create_key(workspace, *, new=False):
    """The machine's LAN key: kept between runs so a bookmark keeps working;
    `new` throws the old one away (every device then signs in again)."""
    path = Path(workspace) / KEY_FILE
    if not new and path.is_file():
        key = path.read_text(encoding='utf-8').strip()
        if key:
            return key
    key = secrets.token_urlsafe(9)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + '\n', encoding='utf-8')
    path.chmod(0o600)
    return key


def cookie_value(key):
    """What the browser keeps: not the key itself."""
    return hashlib.sha256(('voxstage-lan:' + key).encode()).hexdigest()


def accepts(cookie, key):
    return bool(cookie) and hmac.compare_digest(cookie, cookie_value(key))


def addresses():
    """This machine's addresses on the local network, best effort."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.2)
            probe.connect(('192.0.2.1', 9))              # a reserved address: nothing is sent
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found and not address.startswith('127.'):
                found.append(address)
    except OSError:
        pass
    return found


PAGE = """<!doctype html><html lang="zh"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoxStage · 局域网访问</title>
<style>
 body{{font:16px/1.7 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;color:#26302f;background:#f6f5f1;margin:0;display:grid;place-items:center;min-height:100dvh;padding:24px}}
 form{{background:#fff;border:1px solid #dfe1d8;border-radius:14px;padding:24px;max-width:360px;width:100%;box-shadow:0 10px 40px #24352a14}}
 h1{{font-size:20px;margin:0 0 6px}} p{{color:#68786e;font-size:13px;margin:0 0 16px}}
 input{{width:100%;box-sizing:border-box;font:inherit;padding:10px;border:1px solid #cbd6cb;border-radius:8px;margin-bottom:12px}}
 button{{width:100%;font:inherit;padding:10px;border:0;border-radius:8px;background:#2e4939;color:#fff}}
 .bad{{color:#8a3b2f}}
</style>
<form method="post" action="/lan">
 <h1>VoxStage</h1>
 <p>这台 Mac 上的 VoxStage。输入启动时显示的访问口令；这台设备记住 30 天。</p>
 <input type="password" name="key" autocomplete="current-password" autofocus aria-label="访问口令" placeholder="访问口令">
 <button type="submit">进入</button>
 {message}
</form>
"""


def login_page(message=''):
    return PAGE.format(message=f'<p class="bad">{html.escape(message)}</p>' if message else '')

# 最后更新：2026-09-22 · Claude Hera

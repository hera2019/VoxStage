"""Local startup checks; no installation, uploads or model loading. Astra, 2026-09-09."""
import argparse
import hashlib
import http.client
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workspace_id(root):
    # D32: identify the checkout without returning its personal filesystem path.
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()


def service_state(port, root=ROOT, expected_pid=None):
    """Return ours/free/occupied. Never follow redirects or use HTTP proxies."""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            pass
    except ConnectionRefusedError:
        return 'free'
    except OSError:
        return 'occupied'
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request('GET', '/api/health')
        response = connection.getresponse()
        data = json.loads(response.read(4096)) if response.status == 200 else {}
        if (isinstance(data, dict) and data.get('app') == 'VoxStage'
                and data.get('workspace_id') == workspace_id(root) and data.get('ready') is True
                and (expected_pid is None or data.get('pid') == expected_pid)):
            return 'ours'
    except (OSError, ValueError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    return 'occupied'


def inspect_environment(root=ROOT, dependency_probe=True):
    root = Path(root)
    checks = []

    def add(name, state, detail):
        checks.append({'name': name, 'status': state, 'detail': detail})

    native = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    add('电脑', 'ok' if native else 'error',
        'Apple Silicon Mac' if native else '当前预览需要 Apple Silicon Mac 和原生 arm64 Python。')
    py_ok = sys.version_info[:2] == (3, 12)
    add('Python', 'ok' if py_ok else 'error', platform.python_version() if py_ok else
        '请按 README 使用 Python 3.12 建立项目独立环境。')
    if dependency_probe:
        try:
            result = subprocess.run([sys.executable, '-c',
                'import fastapi, uvicorn, numpy, soundfile, scipy.signal, mlx.core, mlx_audio.tts.utils, pypinyin'],
                capture_output=True, text=True, timeout=45, cwd=root)
            add('运行依赖', 'ok' if result.returncode == 0 else 'error',
                '依赖可载入（没有载入模型）。' if result.returncode == 0 else
                '依赖缺失或无法载入。请按 README 安装 requirements.lock.txt；详细错误见报告。')
            if result.returncode:
                checks[-1]['diagnostic'] = (result.stderr or result.stdout)[-4000:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            add('运行依赖', 'error', '依赖检查失败或超过 45 秒，请按 README 修复环境。')
            checks[-1]['diagnostic'] = str(exc)

    page = root/'frontend/dist/index.html'
    add('网页', 'ok' if page.is_file() else 'error', '网页文件已生成。' if page.is_file() else
        '缺少网页文件。请在 frontend 目录执行 npm ci 和 npm run build。')
    preset = Path(os.environ.get('VOXSTAGE_MODEL', root/'user-data/models/qwen-customvoice'))
    provenance = preset/'voxstage-model.json'
    if provenance.exists():
        try:
            data = json.loads(provenance.read_text())
            if not isinstance(data['repo'], str) or not isinstance(data['revision'], str):
                raise ValueError('Invalid model provenance')
            ready = all((preset/name).is_file() for name in
                        ['model.safetensors', 'config.json', 'speech_tokenizer/model.safetensors'])
            add('预设声音', 'ok' if ready else 'warning', '模型文件在位；启动自检不代表声音质量验收。' if ready else
                '模型文件不完整，暂不能生成预设声音。运行 scripts/setup_model.py 补齐。')
        except (OSError, ValueError, KeyError, TypeError):
            add('预设声音', 'error', '模型记录损坏。请运行 scripts/setup_model.py 修复后再启动。')
    else:
        add('预设声音', 'warning', '尚未安装。可先编辑稿件；生成声音前运行 scripts/setup_model.py。')
    base = preset.parent/'qwen-base'
    ready = all((base/name).is_file() for name in
                ['model.safetensors', 'config.json', 'speech_tokenizer/model.safetensors'])
    add('固定角色声线', 'ok' if ready else 'warning', '模型文件在位，首次生成时核验权重。' if ready else
        '模型未备齐或链接失效。请按 README 安装 Base 模型；预设声音仍可使用。')
    from .attribution import ROLE_MODELS, role_server
    server = role_server()
    role_ready = [m for m, spec in ROLE_MODELS.items() if any(Path(x).is_file() for x in spec.get('paths', []))]
    add('分角色模型', 'ok' if server.is_file() and role_ready else 'warning',
        '识别说话人的模型和 llama-server 在位。' if server.is_file() and role_ready else
        ('缺少 llama-server（brew install llama.cpp）。' if not server.is_file() else '') +
        ('尚未安装分角色模型（scripts/setup_model.py --model role-14b）。' if not role_ready else '') +
        '没有它也能导入已标好说话人的剧本。')
    from .tempo import ffmpeg_path
    add('FFmpeg', 'ok' if ffmpeg_path() else 'warning', '在位：可调语速，可导入 mp3/m4a 录音。' if ffmpeg_path() else
        '未找到（brew install ffmpeg）：语速只能原速，录音只收 WAV。')
    settings_path = root/'user-data/asr-settings.json'
    if not settings_path.exists():
        add('文字检查', 'warning', '尚未设置；生成与试听仍可使用。请按 README 设置本地识别。')
    else:
        try:
            settings = json.loads(settings_path.read_text())
            cli, model = Path(settings['cli']), Path(settings['model'])
            prov = model.parent/'provenance.json'
            available = cli.is_file() and os.access(cli, os.X_OK) and model.is_file() and prov.is_file()
            if available:
                sha = json.loads(prov.read_text())['sha256']
                if not isinstance(sha, str) or len(sha) != 64:
                    raise ValueError('Invalid transcription provenance')
            add('文字检查', 'ok' if available else 'warning',
                '识别程序和模型在位，首次检查时核验模型。' if available else
                '识别程序或模型缺失、不可执行或链接失效。请按 README 重新运行 scripts/setup_asr.py。')
        except (OSError, ValueError, KeyError, TypeError):
            add('文字检查', 'error', '识别设置或模型记录损坏。请按 README 运行 scripts/setup_asr.py 修复。')
    return {'ready': not any(c['status'] == 'error' for c in checks), 'checks': checks,
            'scope': '启动条件检查；不验证音质，不逐个核验模型权重，不上传稿件或音频。'}


def save_report(report, root=ROOT):
    folder = Path(root)/'user-data'
    folder.mkdir(parents=True, exist_ok=True)
    # Each run gets its own file so concurrent launch attempts cannot overwrite it.
    path = folder/f'environment-check-{time.time_ns()}.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return path


def print_report(report):
    labels = {'ok': '就绪', 'warning': '提示', 'error': '需处理'}
    for item in report['checks']:
        print(f"[{labels[item['status']]}] {item['name']}：{item['detail']}", flush=True)


def open_page(port, enabled=True):
    url = f'http://127.0.0.1:{port}/'
    print('VoxStage：'+url, flush=True)
    if enabled:
        try:
            subprocess.run(['open', url], check=True, timeout=10, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            print('浏览器未能自动打开，请复制上方地址。', flush=True)


def stop_child(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def print_lan(port, root=ROOT):
    """Where a phone or an iPad on the same network opens it, and with what key
    (本人 2026-09-22). The service prints this too; the launcher hides the
    service's output in a log, so it is repeated where the person can see it."""
    from . import lan
    key = lan.load_or_create_key(Path(root)/'user-data')
    print('局域网访问已开启。同一 WiFi 的设备上打开：', flush=True)
    for address in lan.addresses() or ['<这台 Mac 的局域网地址>']:
        print(f'    http://{address}:{port}/', flush=True)
    print(f'访问口令：{key}（每台设备输入一次，记住 30 天；换口令：.venv/bin/python -m runtime.app --lan --new-key）', flush=True)


def launch(port=8765, root=ROOT, browser=True, startup_timeout=45, network=False):
    root = Path(root)
    state = service_state(port, root)
    if state == 'ours':
        print('VoxStage 已在运行，直接打开已有页面。', flush=True)
        open_page(port, browser)
        return 0
    if state == 'occupied':
        print(f'端口 {port} 已被占用，无法确认是本目录的 VoxStage。\n'
              '若是旧版 VoxStage，请先完成当前任务，再在原启动窗口按 Ctrl+C 关闭后重试。\n'
              '程序没有停止或替换占用端口的服务。', flush=True)
        return 1
    report = inspect_environment(root)
    print_report(report)
    print('环境报告：'+str(save_report(report, root)), flush=True)
    if not report['ready']:
        print('请处理上方“需处理”项目，再重新启动。', flush=True)
        return 1
    logs = root/'user-data/logs'
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs/f'startup-{time.time_ns()}.log'
    env = dict(os.environ, HF_HUB_OFFLINE='1', PYTHONUNBUFFERED='1')
    child = None
    try:
        with log_path.open('w') as log:
            child = subprocess.Popen([sys.executable, '-m', 'runtime.app', '--port', str(port)] + (['--lan'] if network else []),
                                     cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            deadline = time.monotonic()+startup_timeout
            while child.poll() is None and time.monotonic() < deadline:
                if service_state(port, root, expected_pid=child.pid) == 'ours':
                    open_page(port, browser)
                    if network:
                        print_lan(port, root)
                    print('保持此窗口开启。按 Ctrl+C 停止；稿件和已保存声音留在本机。', flush=True)
                    code = child.wait()
                    if code:
                        print('服务已退出，详情见：'+str(log_path), flush=True)
                    return code
                time.sleep(.2)
            print('启动未完成，详情见：'+str(log_path), flush=True)
            return 1
    except KeyboardInterrupt:
        print('\n正在关闭 VoxStage。', flush=True)
        return 0
    except OSError as exc:
        print('无法启动服务：'+str(exc), flush=True)
        return 1
    finally:
        if child is not None:
            stop_child(child)


def main():
    parser = argparse.ArgumentParser(description='VoxStage 本地启动和环境检查')
    parser.add_argument('--check', action='store_true', help='只检查环境，不启动服务')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--lan', action='store_true', help='同一局域网的手机/iPad 也能访问，需要访问口令')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('端口必须在 1–65535 之间。')
    if args.check:
        report = inspect_environment()
        print_report(report)
        print('环境报告：'+str(save_report(report)))
        return 0 if report['ready'] else 1
    return launch(args.port, browser=not args.no_browser, network=args.lan)


def interrupted(signum, frame):
    raise KeyboardInterrupt


if __name__ == '__main__':
    # Closing Terminal must also clean up the child created in its own session.
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已取消启动。')
        sys.exit(0)

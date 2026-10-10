"""Native app service: pre-bound port, external data/logs and an owned process group."""
import argparse
import json
import os
from pathlib import Path
import socket
import threading
import time


def bound_socket(preferred=8765,network=False):
    host='0.0.0.0' if network else '127.0.0.1'
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        sock.bind((host,preferred))
    except OSError:
        sock.bind((host,0))
    sock.listen(128)
    return sock


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--lan',action='store_true')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    # Native termination owns only this group, including inference subprocesses.
    try:os.setsid()
    except PermissionError:
        if os.getpgrp()!=os.getpid():raise
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    from .paths import data_dir
    from .app import create_app,ROOT
    from .lan import load_or_create_key
    import uvicorn
    root=data_dir();root.mkdir(parents=True,exist_ok=True)
    state=Path(os.environ['VOXSTAGE_DESKTOP_STATE'])
    app=create_app(lan_key=load_or_create_key(root) if args.lan else None,voicepack_dir=ROOT/'voicepack/default')
    sock=bound_socket(args.port,args.lan)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=sock.getsockname()[1],log_level='info'))
    def announce():
        while not server.started and not server.should_exit:time.sleep(.05)
        if server.started:
            temporary=state.with_suffix('.partial')
            temporary.write_text(json.dumps(dict(app='VoxStage',pid=os.getpid(),port=sock.getsockname()[1],offline=True)))
            temporary.chmod(0o600);temporary.replace(state)
    threading.Thread(target=announce,daemon=True).start()
    try:server.run(sockets=[sock])
    finally:
        sock.close();state.unlink(missing_ok=True)


if __name__=='__main__':main()

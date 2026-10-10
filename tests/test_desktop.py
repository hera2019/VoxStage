import socket
from runtime.desktop import bound_socket


def test_port_collision_chooses_and_reserves_a_different_port():
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1',0));occupied.listen()
        selected=bound_socket(occupied.getsockname()[1])
        try:
            assert selected.getsockname()[0]=='127.0.0.1'
            assert selected.getsockname()[1]!=occupied.getsockname()[1]
            with socket.socket() as probe:
                assert probe.connect_ex(selected.getsockname())==0
        finally:selected.close()


def test_lan_binding_requires_the_explicit_option():
    selected=bound_socket(0,network=True)
    try:assert selected.getsockname()[0]=='0.0.0.0'
    finally:selected.close()


def test_packaged_exports_do_not_require_git_or_xcode(tmp_path,monkeypatch):
    from runtime import packages
    import subprocess
    monkeypatch.setattr(packages,'__file__',str(tmp_path/'app/runtime/packages.py'))
    def forbidden(*args,**kwargs):
        raise AssertionError('Packaged exports must not invoke system git')
    monkeypatch.setattr(subprocess,'run',forbidden)
    assert packages._made_by()=={'app':'VoxStage','commit':None}

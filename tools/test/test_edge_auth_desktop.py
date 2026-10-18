from types import SimpleNamespace

import pytest

from tools import edge_auth_desktop as desktop
from tools.edge_auth_contract import EXTENSION_ID
from tools.pc1_desktop_recovery import RecoveryError


def test_edge_launch_never_uses_debugging_or_profile_override(tmp_path, monkeypatch):
    browser = tmp_path / "Microsoft/Edge/Application/msedge.exe"
    browser.parent.mkdir(parents=True)
    browser.touch()
    for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path))
    launches = []
    monkeypatch.setattr(
        desktop,
        "subprocess",
        SimpleNamespace(Popen=lambda args, **kw: launches.append((args, kw))),
    )
    result = desktop.open_edge(
        data_root=tmp_path,
        request_id="a" * 32,
        url="https://sf.taobao.com/list/a.htm",
        scope="seed",
        api="fixture",
        challenge_id="challenge",
    )
    assert result["phase"] == "ready_for_human"
    assert launches[0][0] == [
        str(browser),
        f"chrome-extension://{EXTENSION_ID}/auth.html",
    ]
    assert launches[0][1]["cwd"] == str(browser.parent)


def test_no_edge_does_not_silently_launch_chrome(tmp_path, monkeypatch):
    for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path))
    with pytest.raises(RecoveryError, match="edge_unavailable"):
        desktop.open_edge(
            data_root=tmp_path,
            request_id="a" * 32,
            url="unused",
            scope="seed",
            api="fixture",
            challenge_id="",
        )
    assert not (tmp_path / "secrets").exists()

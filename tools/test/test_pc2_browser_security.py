import json
from pathlib import Path

from tools.pc2_browser_security import browser_seccomp_profile

ROOT = Path(__file__).resolve().parents[2]


def test_browser_policy_is_default_deny_and_not_a_privileged_profile():
    policy = browser_seccomp_profile()
    assert policy["defaultAction"] == "SCMP_ACT_ERRNO"
    allowed = {
        name
        for rule in policy["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW"
        for name in rule["names"]
    }
    assert {"clone", "unshare", "chroot"} <= allowed
    assert policy["architectures"] == ["SCMP_ARCH_X86_64"]
    assert not allowed & {"socketcall", "ipc", "setns"}
    assert not allowed & {
        "mount",
        "bpf",
        "reboot",
        "init_module",
        "perf_event_open",
        "open_by_handle_at",
    }
    clone3 = [rule for rule in policy["syscalls"] if "clone3" in rule["names"]]
    assert clone3 == [{"names": ["clone3"], "action": "SCMP_ACT_ERRNO", "errnoRet": 38}]


def test_socket_families_are_restricted_and_raw_packet_sockets_are_excluded():
    rules = [r for r in browser_seccomp_profile()["syscalls"] if "socket" in r["names"]]
    assert {r["args"][0]["value"] for r in rules} == {1, 2, 10, 16}
    assert all(r["args"][0]["op"] == "SCMP_CMP_EQ" for r in rules)


def test_apparmor_retains_host_protections_and_only_names_crow_profile():
    text = (ROOT / "ops/pc2-linux/crow-browser.apparmor").read_text(encoding="utf-8")
    assert "profile crow-browser-sandbox " in text
    assert "  userns," in text
    assert "  deny mount," in text
    assert "deny /sys/kernel/security/** rwklx" in text
    assert "flags=(unconfined)" not in text


def test_syscall_catalog_is_pinned_and_unique():
    catalog = json.loads((ROOT / "ops/pc2-linux/browser-syscalls.json").read_text())
    assert "2ceae35d351c156cb5a8efc0fdc4a08cf94569d8" in catalog["source"]
    assert len(catalog["syscalls"]) == len(set(catalog["syscalls"]))


def test_compose_and_deploy_keep_outer_security_and_load_the_scoped_profile():
    compose = (ROOT / "ops/pc2-linux/compose.yaml").read_text()
    browser = compose.split("\n  pc2-browser-solver:", 1)[1].split("\n  pc2-seed-1:", 1)[0]
    assert "cap_drop:\n      - ALL" in browser
    assert "no-new-privileges:true" in browser
    assert "apparmor=${FAPAI_BROWSER_APPARMOR_PROFILE" in browser
    assert "seccomp=${FAPAI_BROWSER_SECCOMP_PROFILE" in browser
    assert "privileged:" not in browser
    assert "unconfined" not in browser
    deploy = (ROOT / "ops/pc2-linux/deploy.sh").read_text()
    assert 'prepare_browser_security "$release_dir"' in deploy
    assert 'name="$(browser_apparmor_name "$target_release")"' in deploy
    assert 'cmp -s "$generated" "$installed"' in deploy
    assert (
        "FAPAI_BROWSER_SECCOMP_PROFILE=$target_release/ops/pc2-linux/seccomp-browser.json"
        in deploy
    )

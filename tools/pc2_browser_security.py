"""Generate the bounded amd64, zero-host-capability Chromium seccomp policy."""

import argparse
import json
from pathlib import Path


def browser_seccomp_profile():
    catalog = (
        Path(__file__).resolve().parents[1] / "ops/pc2-linux/browser-syscalls.json"
    )
    common = [
        name
        for name in json.loads(catalog.read_text(encoding="utf-8"))["syscalls"]
        if name not in {"socketcall", "ipc"}
    ]
    rules = [{"names": common, "action": "SCMP_ACT_ALLOW"}]
    # These do not grant host capabilities. The kernel still enforces namespace
    # permissions; AppArmor confines the resulting processes, including mounts.
    rules.append(
        {
            "names": [
                "arch_prctl",
                "modify_ldt",
                "chroot",
                "process_vm_readv",
                "process_vm_writev",
                "ptrace",
            ],
            "action": "SCMP_ACT_ALLOW",
        }
    )
    # Chromium creates user/PID/network namespaces, not mount/IPC/UTS/cgroup ones.
    for name, mask in (("clone", 0x0E020000), ("unshare", 0xEFFFFFFF)):
        rules.append(
            {
                "names": [name],
                "action": "SCMP_ACT_ALLOW",
                "args": [
                    {
                        "index": 0,
                        "value": mask,
                        "valueTwo": 0,
                        "op": "SCMP_CMP_MASKED_EQ",
                    }
                ],
            }
        )
    rules.append({"names": ["clone3"], "action": "SCMP_ACT_ERRNO", "errnoRet": 38})
    for name, values in (
        ("socket", (1, 2, 10, 16)),
        ("personality", (0, 8, 131072, 131080, 4294967295)),
    ):
        for value in values:
            rules.append(
                {
                    "names": [name],
                    "action": "SCMP_ACT_ALLOW",
                    "args": [{"index": 0, "value": value, "op": "SCMP_CMP_EQ"}],
                }
            )
    return {
        "defaultAction": "SCMP_ACT_ERRNO",
        "defaultErrnoRet": 1,
        "architectures": ["SCMP_ARCH_X86_64"],
        "syscalls": rules,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(browser_seccomp_profile(), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()

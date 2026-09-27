# PC2 authentication completion repair - 2026-09-27

Status at 16:03 UTC: the confirmed completion-metadata defect is fixed and deployed. Collection recovery is NOT accepted: unique links remain 330909 and captured details remain 155126. Both stages are paused on live site challenges.

## What happened

The earlier manual push reached PC2 at 14:16:52 UTC. Receiver recorded recovery_confirmed, detail scope and 150 cookies. NAS recorded captured_count_advanced from 155013 to 155021. Counts subsequently reached 330909 links and 155126 details before stalling again. Therefore the user's push was received and initially usable.

The PC2 solver completion request omitted node_id. NAS has no default FAPAI_NODE_ID, so it could not resolve the cookie snapshot destination and reported cookie_snapshot_path_not_configured after three retries. Separately, the NAS CDP allowlist omitted the actual external PC2 endpoint. Those faults could prevent successful local authentication from being finalized and cleared on NAS.

## Changes and activation

- tools/pc2_solver_auth.py now includes the node ID and, when configured, FAPAI_REPORT_CDP_ENDPOINT. It deliberately does not transmit a private loopback fallback.
- Three regression cases in tools/test/test_pc2_auth_completion_context.py cover actual destination resolution, challenge/completion/scope propagation and endpoint omission.
- NAS now permits the exact PC2 CDP endpoint http://192.168.15.104:9224. An unrelated endpoint remains rejected. CDP was reachable from NAS.
- PC2's deployed older facade received the same bounded metadata fix, preserving its other implementation. Candidate preflight verified the actual deployed sender without submitting a false authentication completion.

NAS canonical container: 7e008dcf53662ef603d261dfe1369da7b45311f50ac704ce26e3d6b9cfbd6392.
Retained rollback: crow-api-before-completion-20260927.
Private backup: /volume1/docker/fapaifang/backups/auth-completion-endpoint-20260927/.

PC2 canonical browser container: fd737cfe9bc78e30183fd572927a608732600e534526311d95d308465b5b129c.
Retained rollback: fapaifang-pc2-browser-solver-before-auth-completion-20260927.
Private release: /srv/apps/fapaifang-worker/releases/20260927-auth-completion/.
Installed sender SHA-256: faca16fc32574c5522fba7d1c95f7dc7266a296e6d5a4bafb9571b12b98187b9.

Activation receipts were recorded at 15:42:43 and 15:43:38 UTC. Secrets and profile mounts were preserved. No PC1 human-authentication browser, computer or unrelated service was restarted. No Compose service-wide recreation was used.

## Fresh runtime findings

At 15:53 UTC, read-only CDP inspection found all 7 expected critical session cookies, with all 7 values matching the accepted snapshot. Snapshot SHA-256: ba0e6ef54afec904cc3aaa0933d8ec90e1e414be8326333bbf1bcb42a848b30e. No cookie values were printed. Session restoration was unnecessary and was not attempted.

At about 16:02 UTC, PC2's actual detail page was at:
https://sf-item.taobao.com//sf_item/586505480496.htm/_____tmd_____/punish
The page contained challenge markers. A fresh production probe of https://sf.taobao.com/list/200782003__2.htm returned fresh_seed_authenticated=false. The probe closed only its own page.

Receiver logs since activation show repeated local solver failures and challenge rotation; there was no successful auth-completion callback available to validate end-to-end finalization. Seed cycles report seed_collection_paused / captcha_solver_running and zero attempted pages. Recent detail batches completed zero items. Some workers used a 900-second pause backoff; others resumed attempts with 60-second intervals without producing new captures. This does not establish a separate sleep defect.

At 16:03:02 UTC the actual server totals were links=330909 and captured_count=155126. Seed and detail remained paused. The current snapshot-refresh state was idle, not a newly successful completion. Lack of the old error after restart alone is not proof of a successful repair end-to-end.

The remaining acceptance blocker is a current site challenge on PC2 despite retained cookies. A legitimate successful challenge/access check and subsequent normal completion callback are still required. Re-uploading identical cookies alone has not been shown to resolve this challenge. No pause/challenge/cooldown state was forcibly cleared and no success was fabricated.

## Validation

Before activation, the focused completion-context, pending-lifecycle and recovery tests passed: 21 tests in 2.16 seconds. Scoped repository Ruff checks and format checks passed. Effective-code-line tests passed 19 tests; ratchet checked 1380 files with none above 500 effective lines. No full historical suite was rerun. Fresh final git diff --check passed. No source changes were made after those focused checks.

The installed desktop EXE matched the previously verified SHA-256 B6375A7D994FB5F08D56C0F8F5498B7A84C612C903CAF64EBD8A69AB9058613B. Crow was gracefully restarted, verified at the installed executable path with PID 55688, and scripts/update-collector-desktop-shortcut.ps1 refreshed and validated Crow.lnk. No desktop source change or new desktop build was needed for this sender/server repair. Visual screenshot acceptance was not performed in this continuation.

No commit or push was requested or performed. Existing unrelated working-tree edits were retained.

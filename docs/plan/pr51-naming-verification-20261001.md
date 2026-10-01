# PR #51 命名兼容验证与部署记录

本文保留最初阶段的历史快照。PC2 后续部署、运行恢复及最终验收状态以 [PR #51 PC2 恢复与运行验收](pr51-pc2-recovery-20261001.md) 为准，不能将下文的“尚未部署”作为当前状态。

## 代码基线与结论

- 核验时间：2026-10-01 UTC（本机 2026-09-30）。
- 已安全 fast-forward，HEAD 与 origin/master 均为 `7b2467ab38c8872d2c2847a967eb89499a47be8f`，即 PR #51 合并提交。
- 本轮修复保留在工作区，未提交、未推送。
- 新安装使用 CrowData；已有 populated FPFData 原地复用；冲突 fail closed。CROW/FAPAI 环境变量兼容读取，旧 ORM 名称保留 alias，未重命名生产 SQL 表或创建替代空库。
- 本机与 NAS 已验证更新；PC2 新版本尚未部署，不能视为整套系统验收完成。

## 本轮修复

1. PC2 release 验证兼容旧版回滚：旧版不依赖 project-environment.sh 时不强制要求该新文件；新版缺少所引用 helper 仍明确失败。新增 legacy/current/missing-helper 三场景回归。
2. 为 shell 源码设置 LF 属性，修复 Windows checkout/archive 产生 CRLF 后 Linux Bash 解析失败。新增关键入口行尾检查。
3. 测试使用临时数据根，不读取真实 FPFData；更新环境变量兼容 helper 的静态调用断言以及跨平台路径比较。
4. 实际安装版 WebView2 暴露 native IPC CSP 拒绝，精确加入 ipc: 与 http://ipc.localhost，未放宽为任意 HTTP；新增回归。

## 分阶段验证证据

以下来自不同阶段，不代表最终工作区同一次全量通过；最后 CSP 修复采用 focused 验证，未重复无关 broad suites。

| 范围 | 结果 |
| --- | --- |
| 路径、模型、环境变量初始 focused | 62 passed |
| PR 影响测试及 Compose config（Windows） | 513 passed, 25 skipped |
| Linux shell、回滚与部署 focused | 45 passed |
| security（Windows） | 781 passed, 4 skipped |
| Linux fast，最后 CSP 修复前 | 1691 passed, 35 skipped；runner 48.36 秒，满足 60 秒门槛 |
| 隔离 PostgreSQL/PostGIS | 42 passed，包含迁移保留及并发认领 |
| 前端 Node / TypeScript | 45 passed / typecheck 通过 |
| Playwright configuration compatibility | 2 passed |
| Rust | 14 passed, 1 ignored；installed_bundle_read_only_probe 未执行 |
| 最后 CSP 与桌面源码契约 | 30 passed |
| 最后补验 CSP 与 shell 行尾 | 4 passed |
| effective-code-lines checker 测试 | 19 passed |
| ratchet | 1447 files，超过 500 行档位为 0 |
| git diff --check | 通过；Git 提示部分非 shell 工作副本未来转换 CRLF，不是检查错误 |

系统 Python 无 pytest、测试镜像缺依赖、首次 PostgreSQL 缺 PostGIS 等环境问题已分别纠正。Windows fast 功能测试通过但超 60 秒，不计作门槛通过；实际门槛以 Linux 结果为准。

## 本机桌面

- 安装路径：`C:\Users\vmjcv\AppData\Local\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe`。
- SHA-256：`37EDDB8E20902C96944C82B4CE7747EAFB56C0E7F5BC40C6111035230EC9E4E3`。
- 已使用正式 Tauri release 构建，更新 65 个 helper，保留 runtime JSON 和启动器，刷新并验证 Crow.lnk。
- 原文件备份：安装目录下 `backup/pr51-20260930-182522`。
- 真实 WebView2 已读取商品列表、原统计与线上配置；修复后不再出现 native IPC CSP 拒绝。
- 验证结束后不带临时调试参数正常重启，进程路径与安装哈希复核通过。

## NAS

- 当前镜像：`crow-collection:pr51-7b2467ab3-fixed`。
- 当前容器 ID：`dfe3f8283f69038903d146cc9d1377f4525c76437d1a787c9d98b400e60e7699`。
- 镜像 ID：`sha256:40839b316c61a3b282579a2696d808e98335689ddece938559d91f08337fa907`。
- build_info.commit 已纠正为完整真实 HEAD；早期候选误标 38a8fb20f，仅版本元数据错误，归档实际始终基于 7b2467ab3。
- 1,331 个 src/tools/scripts/ops 源码文件与 staging 哈希一致，零不匹配。
- 原数据库 fapaifang、原 PostgreSQL 容器、所有挂载、非构建业务环境变量均保持不变。
- `/api/status`：db_mode=true，auth recovery enabled；342909 条链接，最终部署核验时 captured_count=164224（此前 164195），AI finalized=121725。
- restart policy 为 unless-stopped。保留同 Compose labels 的全部历史备份，使用 exact ID 切换，未执行 service-wide recreate。
- 原始回滚容器：`crow-api-before-pr51-20261001`；元数据纠正前版本另保留为 `crow-api-before-pr51-metadata-20261001`。
- 数据库备份：`/volume1/docker/fapaifang/backups/pr51-20261001/database.dump`，342405935 bytes，已验证 pg_restore 目录。
- 备份 SHA-256：`8a47f832306da6dadd2e8f87f3f603738a26d66640c73a737b44c866ec39c239`。

## PC2 未完成边界

- 未切换 PC2 生产镜像、容器或 controller，仍为旧版本。
- 多次 SFTP/SCP/HTTP/SMB 传输分别 reset、timeout 或资源暂时不可用，最终普通 SSH 也超时。没有完整哈希验证的部署包，因此未构建或激活候选。
- 最后短时只读 SSH 恢复：controller active，浏览器、3 个详情、4 个 AI 容器 healthy；seed 容器 unhealthy，报 worker progress heartbeat is stale or stopped，最后业务日志为 captcha_solver_running。
- 该运行异常出现在旧版本，尚不能归因于 PR #51。新 NAS 与旧 PC2 详情链路可继续写入原数据库，但不等于链接发现和 AI 全链路均正常。
- 未改网络配置或重启机器；后续仍需稳定传输、验证 PC2 候选、带回滚部署，并核验 seed 实际进展。不得依据短时 SSH 成功认定网络问题已解决。

## 证据与收尾

本轮脚本、测试产物、源码清单与运行证据位于 `C:\Users\Public\nas_home\AI\GameEditor\linshi\crow-pr51-20261001`。本轮运行的 quality/postgres/postgis 临时容器已停止，保留供复查；未删除数据、凭据或旧部署。

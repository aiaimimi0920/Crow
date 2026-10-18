# 认证提示协调收尾

## 本轮行为

- PC1 watcher 每次后台检查最多主动展示一个认证页面。
- 主提示已经展示后，再发现 seed 阻塞，只持久化 `waiting_for_seed_auth` 和目标，不创建或激活第二个页签。下一次自然调度仍会验证，并在必要时展示 seed。
- 主提示已展示同一个 seed 目标时，复用其提示记录，不重复提醒。
- 保留实际验证、同轮持久化去重、无活跃采集端禁止自动认证以及手动操作入口。未改变完整浏览器采集路径。

## 验证

- PC1 聚焦回归 22 项通过，包括真实 PowerShell 执行、模拟 CDP、延迟时不触碰浏览器、持久状态重载以及不同/相同目标去重。
- 最终源码联合回归 97 项通过，覆盖失败冷却、活跃采集端保护、人工状态保持、PC2 导入凭据和 PC1 提示。该数字不包含此前其他时间的测试，也不是完整历史测试套件。
- Ruff、PowerShell AST 解析、Git 差异检查通过；有效行数检查自测 19 项通过，ratchet 通过。

## 安装与自然调度

本机任务 `\FapaiFang\FapaiFangNasAuthRecovery` 使用的两份脚本已备份后更新。更新期间暂停任务调度，完成后恢复启用；未重启 Crow EXE、PC1 Edge、PC2 或 NAS。首次暂停命令因未指定任务文件夹失败，未写安装文件；随后通过精确任务对象操作成功。

备份：`C:/Users/Public/nas_home/AI/GameEditor/linshi/crow-prompt-coordination-backup-20261018`。

安装路径：`C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/scripts/`。

- `pc1-auth-recovery-policy.ps1`：`B07D17A96928A57054FCFC4BD573DA7942C676BFB7D5BA41227C66F02D2568D7`
- `watch-pc1-nas-auth-recovery.ps1`：`E4CFD471EA8C2BFCE55A5D688B0339BE5ECA4B8E3B5AF0A642323066594FBE2E`

安装哈希与源码一致。更新后观察到北京时间 2026-10-18 21:05:21 自然调度完成，LastTaskResult=0，任务 Enabled=true、State=Ready。任务成功退出不等于真实双目标认证场景已出现；未主动制造认证失败或弹窗。

## 收尾边界

本次审计识别的四项具体缺口均已修复并应用：失败冷却旁路、人工状态被重复报告覆盖、PC2 同实例重复导入、PC1 同轮连续提示。生产失败注入和真实人工认证端到端观察未进行，不承诺网站不再要求认证，也不把健康检查当作采集成功证明。

# Edge 本机助手注册可见性修复

## 证据与结果

扩展 0.1.1 的 ping 在用户级注册存在时仍返回 native_not_found。Process Monitor 捕获 Edge 主进程打开 HKCU 下 NativeMessagingHosts 父键成功，但打开 com.crow.manual_auth 子键返回 NAME NOT FOUND。普通进程、独立管理员进程、32/64 位视图和同方式 Win32 注册表查询均可读取该子键。确认同一用户 SID、键名无隐藏字符；完整退出 Edge 再打开仍失败。新增当前用户 Chromium 备用注册未解决。

仅在 HKLM 的 Microsoft Edge NativeMessagingHosts 下增加同名 Registry64 注册，仍指向原清单后，用户点击“检查本机连接”获得“本机助手 0.1.1 已连接”。这是真实 Edge 发起的握手通过，不只是命令行直接启动助手。

用户级注册与 Edge 可见性差异的底层机制尚未查明；机器级 Edge 专用注册是本机已经验证有效的修复，不应声称已证明 Windows 或 Edge 的具体缺陷。

## 可维护安装

scripts/register-edge-auth-host.ps1 新增 RegistrationScope：默认 CurrentUser 保持原行为，LocalMachine 要求显式管理员调用，固定使用 Registry64。管理员权限仅用于注册，不用于启动 Python 助手。现有同名注册指向不同安装位置时拒绝覆盖，必须另做明确迁移。后续常规升级仍使用同一清单路径，因此现有机器级注册持续有效；迁移安装目录时需重新处理机器级注册。

注册清单的 allowed_origins 仍仅有原 Crow 扩展 ID。未修改浏览器策略、扩展权限、Cookie、配置或配对；未重启桌面应用和浏览器。此前添加的 Chromium 备用项保留并有独立变更记录，未因清理而删除注册数据。

验收范围仅为扩展到本机助手的发现、启动和 ping 回包。任务领取、人工网站认证、Cookie 提交与 PC2 恢复仍需业务验收，不能由 ping 成功推断。

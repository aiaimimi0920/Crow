# Crow 的本机 AI Gateway 受限转发

当 AI Gateway 只监听 PC1 的 loopback 地址时，PC2 和 NAS 容器不能使用
`http://127.0.0.1:4200/v1` 访问它；容器内的 loopback 指向容器自身。

`tools/crow_ai_gateway_relay.py` 提供不解析 HTTP 的 TCP 转发。它要求指定
监听地址、loopback 上游和来源 IP 白名单；拒绝来源不会连接上游。转发器
不保存 AI 密钥，也不记录请求头、请求体、响应体或模型输出。

当前经用户批准的部署拓扑：

```text
PC2 192.168.15.104 / NAS 192.168.15.200
    -> PC1 192.168.15.20:4200
    -> PC1 127.0.0.1:4200
```

远端 Crow AI 客户端使用 `http://192.168.15.20:4200/v1`，原 Gateway
继续只监听 `127.0.0.1:4200`。这是获准局域网内的 HTTP 转发，不是 TLS
隧道；不要将监听地址改成 wildcard，或开放到公网。

运行参数如下；地址属于本次部署配置，不是代码中的固定默认值：

```text
pythonw.exe -B crow_ai_gateway_relay.py --listen-host 192.168.15.20 --listen-port 4200 --upstream-host 127.0.0.1 --upstream-port 4200 --allow-client 192.168.15.104 --allow-client 192.168.15.200
```

PC1 已安装副本位于 `%LOCALAPPDATA%\CrowGatewayRelay\`。当前用户的
`Crow AI Gateway Relay` 计划任务在登录后启动该副本；更新前应核对任务
action、脚本 SHA-256 和 exact process identity，只重启该转发进程。
Gateway 停止时转发器不会代为启动或重启 Gateway。

AI 地址和密钥必须同时写入实际 AI 客户端及其持久运行配置。PC2 仍以
settings mailbox、`active.json`、operation lock 和 claim-bound receipt 为
准；NAS API 是独立客户端。保留同 Compose labels 的旧容器时，不得使用
service-wide Compose recreation，必须按 canonical exact ID 替换并保留回滚。
不要把密钥写入源码、示例、命令行或公开检查回执。

验收应分别检查来源拒绝、PC2/NAS 实际可达性、密钥一致性、容器健康和
真实 AI 请求。`GET /v1/models` 返回 200 只证明目录访问，不能证明账户
额度、模型推理或采集 AI 归档可用。

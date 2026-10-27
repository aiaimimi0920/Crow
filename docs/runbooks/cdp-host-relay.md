# CDP Host relay 的 HTTP 连接边界

`tools/cdp_host_relay.py` 面向 Chromium DevTools：将每条连接的首个 HTTP 请求的 `Host` 改为受信任的 upstream authority，随后透传数据。它不是支持 HTTP pipelining 的通用代理。

普通 HTTP 响应必须显式携带 `Connection: close`，并移除 `Keep-Alive`。否则 HTTP 客户端可能复用该连接，第二个请求的服务名 Host 未经改写就到达 Chromium，表现为首个请求 200、后续请求 Host 校验失败。仅给请求增加 `Connection: close` 不足以保证 Chromium 主动关闭连接。

响应处理只修改最终响应头的连接声明，保留 Content-Length、chunked framing 和 body 字节；100/103 等临时响应原样发送。带有 Upgrade 请求头的连接保留原来的双向透传，包括 WebSocket 101 握手和后续二进制帧。客户端关闭或任一方向结束后仍由既有取消与关闭路径释放两端连接；客户端 CIDR 访问限制不变。

## 验证与诊断

离线回归：`tools/test/test_cdp_host_relay.py` 与 `tools/test/test_cdp_host_relay_http.py`。后者仅访问 loopback 假上游，覆盖同 Session 连续请求、两种 body framing、临时响应、EOF-delimited body、自然连接释放与 WebSocket 双向字节一致性。

运行排查优先读取少量 `/json/version` 和 `/json/list` 元数据，并区分新连接、复用连接与浏览器本机结果；不要输出业务 URL、页面正文、凭据或完整 WebSocket 路径，不创建页面或触发求解来验证 relay。

元数据返回 200 只能证明相应 HTTP 端点可读，不能证明页面执行、Playwright attach 或抓取成功。`detail_browser_capture_deadline` 来自整个抓取 helper 的 180 秒截止时间；不能仅凭外层 `detail_cdp_unreachable` 认定 TCP 端点宕机，也不能把 relay 回归通过解释为 solver 通过率提升。

## 部署前的启动契约

以容器当前 Config.Entrypoint、Config.Cmd 和实际挂载为准核对启动入口；镜像内的源码副本不一定是执行文件。若入口由只读 bind mount 覆盖，应核对挂载源、执行文件及持久化计划，而不是将二者哈希不同直接判为临时热改。仅保留镜像也不能证明下一次重建会保留该入口。

比较计划与实际挂载时，同时解析 Compose volumes 和文件型 secrets；后者也会成为只读运行时挂载，不应再重复添加同目标的 volume。已确认的计划漂移只能按当前实际配置修复，保留私有备份，未知差异应停止切换；不得为部署 relay 顺便改变代理、显示、solver 或重试参数。

# 商品分析停滞调查：2026-09-27

核查时间：2026-09-27 16:46 UTC。本次检查没有修改或重启 Crow、NAS、PC2 或本机 CLIProxyAPI。

## 实际部署位置

商品分析任务在 PC2 执行。当前运行的 fapaifang-pc2-analysis-1 至 analysis-4 都是 detail-analysis-worker 模式。NAS 的 crow-api 是 api 模式，承担 API 和数据管理；本次核查的正式部署中，未发现 NAS 运行这组商品分析 worker。

PC2 分析进程和 NAS API 当前均配置：

- AI 地址：http://192.168.15.20:8317/v1
- 模型：deepseek-v4-flash
- PC2 访问 Crow 控制/数据 API 的地址：https://192.168.15.200:9520/api

192.168.15.20 已核实为本机以太网地址。8317 端口由本机 CLIProxyAPI-windows-amd64.exe 监听，PID 13060，实际程序位于 AIGateway/builds/CLIProxyAPI-20260925-basispoints-v1。

## 为什么数量不增长

四个 PC2 分析容器虽然 Docker 健康检查正常，但近期业务日志一致为：

    decision=detail_worker_llm_unavailable
    completed=0
    attempts=0
    sleep_seconds=60

这表示分析在模型预检阶段就被阻止，没有开始处理商品。

从实际 PC2 analysis-1 容器，以及 NAS crow-api 容器，分别使用各自现有模型配置发起了一次最小 chat/completions 请求。两次结果相同：

    HTTP 503
    type=server_error
    code=model_availability_filtered
    message=API key route is temporarily protected; retry later or use another credential
    has_choices=false

因此，PC2 和 NAS 均能连接本机 AI 服务，但当前凭据对应的模型路由被服务端保护机制拦截，实际推理没有成功。不能把网络连通、模型名存在或容器 healthy 当成 AI 服务可用。

PC2 还有第二层模型资格池保护。检查时它没有当前可用的 qualified_models，预检为 503 / exhausted_or_probing，并处于约 869 秒的冷却期。deepseek-v4-flash 曾通过资格测试（5 分），但历史通过不代表现在可调用。资格池另有其他模型的 401、403 和测试不达标记录，不能将这些其他模型的错误直接归因于当前 deepseek 路由。

## 最新数量

16:46:21 UTC 的实际服务器状态：

- 商品链接：330935。
- 已捕获详情：155151。
- 已完成 AI 分析：121084。
- 等待分析 / 分析积压：25824。
- 正在分析：0。
- 分析阻塞：8243。

详情捕获已比之前的 155126 增加 25，但分析完成数仍为 121084。已有大量待分析详情，当前分析停滞不能仅用采集暂停解释。

## 结论与修复边界

商品分析部署在 PC2，配置确实指向本机 AI 服务；当前未能成功完成推理。直接阻塞点是本机 CLIProxyAPI 返回的 model_availability_filtered，随后 Crow 的资格池也保持不可用/冷却状态。

下一步应查看 CLIProxyAPI 中 Crow 所用凭据对应的模型路由保护记录和上游失败原因，修复或恢复合法可用的路由，再验证 PC2 实际完成商品分析、121084 计数开始增长。当前证据尚不能区分上游凭据失效、额度、模型可用性或其他保护触发原因，因此不应直接声称是欠费或密钥失效，也不应盲目清空冷却、绕过保护或替换凭据。

本次只完成诊断：未修改 CPA 配置、未重置保护、未切换模型或凭据。真实请求仅各一次最小探针，没有返回推理内容或 usage；日志和报告均未输出 API Key。

# H4M 北京真值候选核验（2026-11-18）

结论：停止接入当前半年标签管线。已取得并在内存解析完整作者公开 real_estate.json，不是下载障碍；文件缺成交日期，不能对齐 t+6。没有训练、匹配测试城或计算精度，没有修改采集。

来源：
- 作者下载页 https://indigopurple.github.io/H4M/download.html
- 原始公开目录 https://drive.google.com/drive/folders/18LiPUgnoYxBYLGdqx4fTIK6qXHn-sHA6
- 原始 real_estate.json file ID: 1v-mAVtK2YgBntT636ogWflhldvZR-pfo
- 论文 Data Records / Usage Notes: https://arxiv.org/html/2208.12542v1
- 代码许可 https://raw.githubusercontent.com/IndigoPurple/H4M/main/LICENSE

实际文件：31,671,090 bytes，29,145 行；SHA256 95f417617d9f7c97d46f52686b20229bba7e5671d015a88ac396769c144585b0。
完整顶层键并集：BathNum, BuildingArea, Decoration, Elevator, Floor, HallNum, Heating, Id, InsideArea, KitchenNum, Lat, Layout, Lng, Orientation, RoomNum, TotlaPrice, Year。
无成交日期、小区名、直接单价字段；TotlaPrice 是实际拼写，不能按论文样例 TotalPrice 假定读取。论文明确 Year 为建筑年份，不能当成交年；2017–2018 的总体覆盖不能替代逐笔日期。论文清洗后 28,645 行与原始文件 29,145 行不同，不擅自假定同一版本。

论文 CC BY4.0 与软件 MIT 分别针对论文/Software；数据下载页要求引用但未见明确覆盖外部数据的独立许可，不能推定无限制商用。即便后续许可澄清，缺成交日期仍阻止当前时间标签任务。当前没有请求作者、接受协议或执行第三方脚本；原文件仅内存读取，不复制进入 Crow 数据层。

重新开启条件：作者公开带真实逐笔成交日期的兼容版本，并澄清数据使用范围；还须验证地段对应和历史可得性。不得由建筑年份、抓取/修改日期、ID排序猜成交时点。不要为了凑回测结果改冻结目标或使用留出城拟合。

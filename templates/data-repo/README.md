# 私人数据仓库骨架（由 init_data_repo.bat 生成）

这个目录**只有数据，没有代码**。代码在旁边的逻辑仓库里，两边靠 `DATA_DIR` 单向连接。

## ⛔ 永不推云

这里会放：微信聊天留痕、你的薪资口径、联系人档案、API Key、运行日志。
**不要 `git push`、不要设为 public、不要放云同步盘、不要发给别人**，private 远端也不行。
备份 = 整个目录打包到本机另一块盘或离线介质。详见 `DO_NOT_PUSH.md`。

## 目录

| 路径 | 作用 | 缺失时 |
|---|---|---|
| `.env` | 主配置：`WECHAT_DB_DIR` / `WATCH_CHATS` / 节流参数 | 全部走默认值 |
| `ai_provider.env` | **AI 接口**：`AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` | 无 Key 则 AI 功能不可用 |
| `口径包.md` | 固定口径（离职原因、到岗时间、项目数据等） | AI 用通用求职礼仪兜底 |
| `examples.md` | 风格 few-shot，教模型像你说话 | 用代码内置虚构示例 |
| `contacts/<备注名>.md` | 单个 HR/猎头的专属档案，防前后矛盾 | 只用通用口径包 |
| `notes/*.md` | 可选检索语料 | 回退到 `JOB_DOCS_DIR` |
| `logs/` | 运行留痕、上游日志 | 运行时自动创建 |
| `_copilot_home.bat` | 记录逻辑仓库位置（本机路径，已 gitignore） | 由初始化脚本生成 |

目录契约与配置优先级见逻辑仓库的 `DATA_CONTRACT.md`。

## 启动

| 双击 | 效果 |
|---|---|
| `start.bat` | 人工确认模式（推荐） |
| `start_auto.bat` | 自动回复模式（带护栏，默认别开） |
| `doctor.bat` | 体检：只报状态，不打印密钥、数据内容或联系人姓名 |

脚本会设好 `DATA_DIR` / `PYTHONPATH`，把工作目录切到这里，再调逻辑仓库的 venv。
逻辑仓库换位置时，重跑一次 `scripts\init_data_repo.bat`（不会覆盖已有配置）。

# WeChatJobCopilot — 求职微信对话助手

[![offline-tests](https://github.com/Sy-best/wechat-job-copilot/actions/workflows/tests.yml/badge.svg)](https://github.com/Sy-best/wechat-job-copilot/actions/workflows/tests.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

HR 加微信后，新消息实时进 Copilot，AI 按你自己的口径生成回复建议，人工确认一键发送；
也可以开启带护栏的自动回复。替代「截图发给 AI」的原始流程。

> **定位差异**：微信 + AI 的通用机器人很多，本项目只做一件事——**求职/HR 对话**。
> 底层读库/发送不是我们做的，价值在业务层：固定口径包、联系人专属档案（防止前后说法矛盾）、
> 连发合批、去 AI 腔风格守门，以及默认「人工确认」的安全边界。

## 快速开始（fork / clone 后 3 步）

```cmd
:: 1. 代码 + 依赖（Windows + Python 3.12）
git clone https://github.com/<你的账号>/wechat-job-copilot.git WeChatJobCopilot
cd WeChatJobCopilot
git clone --depth 1 --branch v1.2.9 https://github.com/fanyuantaier/wechatauto-replica.git _deps\wechatauto-replica
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .\_deps\wechatauto-replica

:: 2. 一键生成私人数据仓库（骨架 + 启动脚本，已存在的文件不覆盖）
scripts\init_data_repo.bat

:: 3. 填 AI 接口，然后体检
notepad ..\wechat-job-data\ai_provider.env
.venv\Scripts\python -m copilot.main doctor
```

第 2 步会在代码仓库同级生成 `wechat-job-data\`：`.env`、`ai_provider.env`、
`口径包.md`、`examples.md`、`contacts\`、`notes\`、`logs\`，以及 `start.bat` /
`start_auto.bat` / `doctor.bat`；同时把一行 `DATA_DIR=...` 写进代码仓库的引导 `.env`。
**这个数据仓库含个人消息与密钥，永不推云**，详见它自带的 `DO_NOT_PUSH.md`。

> 只想验证代码？跳过第 2、3 步：`.venv\Scripts\python -m unittest discover -s tests -v`
> （18 项离线单测，不需要微信在线、上游库或 API Key），或双击 `start_listener.bat` 零数据试跑。

## 架构：代码仓库 / 数据仓库分离

```
┌──────────────────────────┐     DATA_DIR（唯一契约）   ┌──────────────────────────┐
│ 逻辑仓库（本仓库，可公开）│ ───────只读，不写回──────▶ │ 数据仓库（私有，不上云）  │
│  copilot/*.py / 模板/单测 │                            │  .env / 口径包.md /       │
│  零个人信息、零硬编码路径 │                            │  examples.md / contacts/ │
│                          │                            │  notes/ / logs/           │
└──────────────────────────┘                            └──────────────────────────┘
```

完整契约见 **[DATA_CONTRACT.md](DATA_CONTRACT.md)**：目录约定、配置加载优先级、
零数据模式、从零建数据仓库、改代码时的约束。

```
微信 4.x PC 客户端（已登录，窗口别关）
   │
   ▼
适配层 copilot/adapter.py      ← 唯一接触上游库的模块（本地库解密 + Listener + UIA 发送）
   ▼
业务层 copilot/main.py        人工确认 / 自动回复护栏 / 队列合批 / 自适应轮询 / doctor
   ▼
AI 层 copilot/ai.py           任意 OpenAI 兼容端点 + 依据注入 + 去 AI 腔风格守门
   ▼
上下文 copilot/context.py     ★ 唯一读取 DATA_DIR 的模块（口径包/档案/示例/语料检索）
```

上游依赖 [wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica)（Apache-2.0），
克隆到 `_deps/`（gitignored）以 editable 方式安装，**不进本仓库**。
上游与微信版本强耦合（要求 WeChat 4.1.12+，实测 4.1.15 / 4.2.0），
将来微信更新失配时只需重写 `adapter.py`，业务层零改动。

## 安装细则

- 固定上游 tag `v1.2.9` 是为了避免微信客户端升级导致意外失配；升级时显式改 tag 并回归测试。
- `scripts\init_data_repo.bat` 可重复运行、不覆盖已有配置；想放别的路径就传参数：
  `scripts\init_data_repo.bat D:\my\data-dir`。逻辑仓库换位置后重跑一次即可刷新路径。
- 不用脚本也行，手动建数据仓库：

```cmd
mkdir ..\wechat-job-data && cd ..\wechat-job-data
mkdir contacts notes logs
copy ..\WeChatJobCopilot\.env.example .env
copy ..\WeChatJobCopilot\ai_provider.env.example ai_provider.env
copy ..\WeChatJobCopilot\copilot\口径包.example.md 口径包.md
copy ..\WeChatJobCopilot\copilot\examples.example.md examples.md
```

  再从 `templates\data-repo\` 复制 `run.bat` / `start.bat` / `start_auto.bat` /
  `doctor.bat` / `gitignore.template`（改名 `.gitignore`），并在代码仓库写一行引导配置
  `.env`：`DATA_DIR=D:\path\to\wechat-job-data`（或用系统环境变量传入）。

- `.env` 里填 `WECHAT_DB_DIR`（留空自动探测）、`WATCH_CHATS` 等；
  **AI 接口单独填 `ai_provider.env`**：`AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL`。
  两份模板都是空白占位 + 逐项注释，不含真实密钥或接口地址，都要 gitignore。
  兼容任意 OpenAI 格式 `/chat/completions` 端点，换模型/换厂商只改这一个文件。

| 数据文件 | 作用 |
|---|---|
| `ai_provider.env` | **AI 接口**：Key / 接口地址 / 模型名；模板 `ai_provider.env.example` 是空白 + 逐项注释 |
| `.env` | 主配置：微信库路径、监听名单、节流参数 |
| `口径包.md` | 身份/离职原因/到岗时间/薪资锚点等固定口径，改文件即生效，无需重启 |
| `contacts/<备注名>.md` | 单个联系人已说过的话（如已报数字），防止 AI 自相矛盾 |
| `examples.md` | 风格 few-shot，按你自己的说话方式举例 |
| `notes/*.md` | 可选检索语料；也可用 `JOB_DOCS_DIR` 只读挂外部笔记目录 |

不配数据仓库也能跑（零数据模式），AI 退化为通用求职礼仪回复。配完跑一次体检：

```cmd
.venv\Scripts\python -m copilot.main doctor
```

`doctor` 只报状态，不打印数据内容、密钥或联系人姓名。

## 使用

前提：微信 PC 端保持登录，窗口不要最小化/锁屏（发送靠 UIA，窗口不可见会失败）。

| 双击 | 效果 |
|---|---|
| 数据仓库 `start.bat` | 人工确认模式（推荐：配置、日志、数据都在数据仓库） |
| 数据仓库 `start_auto.bat` | 自动回复模式（带护栏，见下） |
| 数据仓库 `doctor.bat` | 配置与数据体检 |
| 代码仓库 `start_listener.bat` | 零数据模式试跑，日志退回代码仓库的 `logs/` |

> 数据仓库里的 `run.bat` / `start*.bat` / `doctor.bat` 由 `scripts\init_data_repo.bat`
> 从 `templates\data-repo\` 生成。它们设好 `DATA_DIR` / `PYTHONPATH`，把工作目录切到
> 数据仓库，运行留痕落在 `logs/`，不污染代码仓库。

命令行：

```cmd
.venv\Scripts\python -m copilot.main doctor                  :: 数据/配置体检
.venv\Scripts\python -m copilot.main                        :: 人工确认（默认）
.venv\Scripts\python -m copilot.main --auto                  :: 自动回复
.venv\Scripts\python -m copilot.main --auto --dry-run        :: 演练：只打印不发送
.venv\Scripts\python -m copilot.main search 关键词            :: 查准确昵称 / wxid
.venv\Scripts\python -m copilot.main read                    :: 列出最近会话
.venv\Scripts\python -m copilot.main read 张三 -n 30 --ai    :: 按需读取 + AI 建议（不发送）
```

`WATCH_CHATS` 用逗号/顿号分隔指定监听对象（名字里不能带逗号），
留空 = 全局监听（自动发现新会话、跳过群聊），新 HR 加你开聊无需改配置。

### 检测节奏（自适应 tick）

| 状态 | 查库间隔 |
|---|---|
| 启动 / 对话中（最近 10 分钟有新消息） | 10s |
| 连续 10 分钟没有任何新消息 | 60s |

配置：`TICK_ACTIVE=10`、`TICK_IDLE=60`、`TICK_WINDOW=600`。
这是**查库频率**，不是回复频率。上游 `Listener._run` 用 `_stop.wait(interval)` 睡眠，
回调在 worker 线程改 interval 唤不醒它；`adapter.py` 用 1s 心跳 + 独立 wake 事件覆盖 `_run`，
所以静默期间来消息会立刻唤醒提速。

### 自动回复护栏

**默认关闭**（`AUTO_SEND=0`）。开启方式：`--auto`，或 `.env` 设 `AUTO_SEND=1`。

- 每条消息入队，`REPLY_WINDOW`(60s) 内连发合并成一条回复；单条静默 `REPLY_QUIET_FAST`(8s) 即回；两次发送间隔 ≥ 60s
- 群聊、非文本、空/超 500 字回复、每人每次运行 20 批上限 → 一律转人工并打印建议 + 留痕
- AI 调用失败有限次重试并整批重新入队，重试耗尽留痕提示人工补回，不静默丢消息
- 所有自动发送写入数据仓库的 `logs/`；建议先用 `--dry-run` 演练

⚠️ 自动回复意味着 AI 生成的内容直接发给 HR，没有人工过目、发出去撤不回。
**求职号风控优先，除非你清楚自己在做什么，别开全自动。**

## 回复决策依据

三层依据按优先级注入 system prompt，全部来自数据仓库：

1. **联系人档案** `contacts/<备注名>.md` —— 每个关键联系人的专属口径，优先级最高
2. **固定口径包** `口径包.md` —— 离职口径/到岗时间/项目数据/薪资锚点/红线，改文件即生效
3. **实时检索** —— 按联系人名 + 对方消息关键词，去 `DATA_DIR/notes` 或 `JOB_DOCS_DIR` 的 md 文件 grep 命中行兜底

笔记里的策略句统一加 **【内部】** 标记并明令「只用来判断，一个字都不能出现在回复里」，
避免内部口径被模型当成话术照抄。

## 去 AI 腔

`BASE_PROMPT` 用硬规则而非抽象要求：一条只做一件事、40 字内、一句话最多一个逗号、
禁书面连接词/职场客套/HR 黑话、不追加固定结尾、数据一次一个、用「你」不用「您」。
`examples.md` 提供真人短句 few-shot + AI 腔负例对照；连发合并额外挂 `BATCH_PROMPT`。

`_smell` 程序化风格守门检测书面词、HR 黑话、分号/括号/编号、超长、逗号过多，
命中就带纠偏提示**自动重写一次**，仍不过才放行并告警。干净回复不产生额外 API 调用。

## 安全边界与隐私

- 消息只在本机读取（解密本地 SQLite），除发给所选大模型 API 的对话片段外不上传任何数据
- **代码仓库零个人数据、零密钥**：真实配置在数据仓库的 `.env` 与 `ai_provider.env`；
  代码仓库只有空白模板（`.env.example` / `ai_provider.env.example`）和字段注释
- **数据仓库永不推云**：不建 remote、不 push、不设 public、不放云同步盘；
  生成的骨架自带 `.gitignore` 与 `DO_NOT_PUSH.md`
- **AI 接口可插拔**：`AI_BASE_URL` 指向任意 OpenAI 兼容 `/chat/completions` 端点，
  代码里只保留公开兜底默认值，实际运行时以数据仓库配置为准
- 只读本地库 + GUI 发送，不注入微信进程、不碰协议层，不提供批量加人/群发/营销能力
- 发送用 `verify=False` + 本进程已解密的库回读留痕：上游 `verify=True` 会自己探测库目录，
  显式指定 `WECHAT_DB_DIR` 时会「消息已发出却报未确认」。回读失败按已发送处理，避免重复补发
- 仅用于读取和管理**你自己账号**的聊天数据；请遵守微信软件许可及所在地法律
- 第三方客户端自动化存在账号风控风险；与腾讯/微信官方无任何关联，使用后果自负

## 相关项目（选型时对比过）

| 类型 | 代表 |
|---|---|
| 通用微信 AI 机器人 | [CowAgent](https://github.com/zhayujie/CowAgent)、[LangBot](https://github.com/langbot-app/LangBot)、[wechat-bot](https://github.com/wangrongding/wechat-bot) |
| 微信 4.x 本地库解密 / MCP | [wechat-decrypt](https://github.com/bbingz/wechat-decrypt)、TraceMemo、WeChatDataAnalysis |
| 微信 4.x 自动化底座 | [wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica)、[wxauto](https://github.com/cluic/wxauto) |

本项目不重复造底座，只覆盖「求职对话辅助」这一细分场景。

## 测试与目录

```cmd
.venv\Scripts\python -m unittest discover -s tests -v
```

CI 在每次 push / PR 自动跑同一套离线单测（只需 `requests`，不需要微信或 API Key）。

```
copilot/
  adapter.py   微信适配层（上游隔离点 + 自适应 tick）
  ai.py        AI 回复建议（三层依据 + 风格守门 + 合批）
  context.py   ★ 唯一数据入口：DATA_DIR -> 口径包/档案/示例/检索
  config.py    分层 .env 加载（环境变量 > ai_provider.env > 数据仓库 .env > 引导）
  main.py      监听 + 回复队列 / 人工确认 / read / search / doctor
  *.example.md 通用模板（虚构内容，可公开）
scripts/init_data_repo.bat   一键生成私人数据仓库骨架
templates/data-repo/         数据仓库模板（启动脚本 / gitignore / DO_NOT_PUSH.md）
.github/workflows/tests.yml   CI：离线单测
tests/                       离线单测（含隐私回归）
.env.example / ai_provider.env.example   空白配置模板 + 逐项注释
DATA_CONTRACT.md             数据契约（目录约定 / 优先级 / 零数据模式）
CONTRIBUTING.md              fork / PR 流程与隐私红线
_deps/                       wechatauto-replica 克隆（不提交）
```

## 许可证

[MIT](LICENSE) · 上游依赖许可证见 [NOTICE](NOTICE) · 参与开发见 [CONTRIBUTING.md](CONTRIBUTING.md)

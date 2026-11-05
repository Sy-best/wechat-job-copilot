# 数据契约（DATA_CONTRACT.md）

本仓库**只有逻辑代码**。所有个人数据（口径包、联系人档案、风格示例、配置、运行留痕）
都在一个独立的**数据仓库**里，通过一个环境变量 `DATA_DIR` 单向连接。

```
┌──────────────────────────┐        DATA_DIR        ┌──────────────────────────┐
│ 逻辑仓库（本仓库 / 可公开）│ ─────────────────────▶ │ 数据仓库（私有，不入云）  │
│  *.py / 模板 / 单测       │   只读，绝不写回        │  .env / *.md / logs/     │
└──────────────────────────┘                        └──────────────────────────┘
```

好处：代码可以公开、可以随便升级；数据仓库可以整体备份、单独做版本历史；
微信客户端升级只动 `adapter.py`；换机器只改启动脚本里的一行路径。

## 目录约定

| 数据仓库路径 | 读取方 | 内容 | 缺失时行为 |
|---|---|---|---|
| `.env` | `config.load_env()` | 主配置：微信库路径、监听名单、节流参数、`DATA_DIR` | 全部走默认值 |
| `ai_provider.env` | `config.load_env()` → `ai.Replier` | **AI 接口独立配置**：`AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` / `AI_TEMPERATURE` | 无 Key 则 AI 功能不可用 |
| `ai_provider.env.example` | 人读 | 空白模板 + 逐项字段注释（可提交、可公开） | — |
| `口径包.md` | `context.load_pack()` | 固定口径：离职原因、到岗时间、薪资底线等项目事实与策略 | AI 用通用求职礼仪兜底 |
| `examples.md` | `context.load_examples()` | 风格 few-shot + AI 腔负例 | 用 `ai.py` 内置虚构通用示例 |
| `contacts/<备注名>.md` | `context.load_contact_pack()` | 单个 HR/猎头专属档案，优先级高于通用口径包 | 只用通用口径包 |
| `notes/*.md`（可选） | `context.retrieve()` | 本工具专属检索语料 | 回退到 `JOB_DOCS_DIR` |
| `logs/` | `_auto_logger()` + 上游日志 | 自动回复留痕、本地库运行日志 | 运行时自动创建 |

`JOB_DOCS_DIR` 可以指向**数据仓库之外**的任意只读语料目录（例如已有的求职笔记空间）。
显式配置时优先于 `notes/`；两者都空则关闭检索兜底。这样大型知识库不必搬进数据仓库，
避免产生两份会分叉的副本。

## 配置加载优先级

`copilot/config.py::load_env()` 按高 → 低合并，结果同时写进 `SETTINGS` 和 `os.environ`：

1. 真实系统环境变量（启动脚本用它传 `DATA_DIR`，也可临时覆盖任意参数）
2. `<DATA_DIR>/ai_provider.env` —— AI 接口独立配置（Key / 地址 / 模型 / 温度）
3. `<DATA_DIR>/.env` —— 数据仓库主配置
4. `<代码仓库>/.env` —— 兼容/引导文件，正常只写一行 `DATA_DIR=...`

代码仓库只提供两份**空白占位 + 注释**的模板：`.env.example` 与 `ai_provider.env.example`；
后者逐项写明每个字段该填什么、支持哪些 OpenAI 兼容端点。仓库里没有任何真实密钥、
真实接口地址，也没有硬编码的个人路径。
**优先级规则的意义**：想临时改监听名单或换个模型，设个环境变量即可，不必动数据仓库。

## 零数据模式

`DATA_DIR` 未配置时程序照常运行：口径包/示例/档案/检索全部为空，
AI 只用 `BASE_PROMPT` + `GENERIC_EXAMPLES`（完全虚构）生成通用回复。
公开仓库 clone 下来第一次试跑就是这个状态，不会读到任何人的隐私。

## 从零建一个数据仓库

公开仓库提供 `scripts\init_data_repo.bat`：一键建目录、复制空白模板、生成启动脚本与
引导 `.env`，已存在的文件一律不覆盖（可重复运行）。等价于下面的手动步骤：

```cmd
mkdir my-wechat-data && cd my-wechat-data
mkdir contacts notes logs
copy <代码仓库>/.env.example .env        # 填 DATA_DIR、WECHAT_DB_DIR、WATCH_CHATS 等
copy <代码仓库>/ai_provider.env.example ai_provider.env   # 填 AI_API_KEY / AI_BASE_URL / AI_MODEL
copy <代码仓库>/copilot/口径包.example.md 口径包.md
copy <代码仓库>/copilot/examples.example.md examples.md
```

`ai_provider.env` 含密钥，务必加进数据仓库的 `.gitignore`。
换模型或换厂商（含本地 Ollama 等 OpenAI 兼容端点）只改这一个文件，代码零改动；
旧键 `DEEPSEEK_API_KEY` / `MODEL` 仍兼容，但 `AI_*` 优先。

然后在代码仓库目录写一行引导配置（或用环境变量）：

```ini
DATA_DIR=D:\path\to\my-wechat-data
```

体检：

```bash
python -m copilot.main doctor
```

`doctor` 只打印状态、文件字节数、档案份数和语料篇数，**不打印任何数据内容、
密钥或联系人姓名**，输出可以安全地贴出来排查问题。

## 启动脚本的分工

数据仓库里的脚本由 `scripts\init_data_repo.bat` 从 `templates\data-repo\` 复制生成
（模板可公开、不含任何个人路径）：

- 数据仓库的 `run.bat` / `start*.bat` / `doctor.bat`：`DATA_DIR` 指自己、
  `PYTHONPATH` 指代码仓库、**工作目录切到数据仓库**，代码仓库位置记在
  `_copilot_home.bat`（含本机路径，已 gitignore）。这样上游 `wechatauto_logs/`
  和自动回复留痕都落在 `logs/`，代码仓库不会被运行时产物污染。
- 代码仓库的 `start_listener*.bat`：给「不挂数据仓库、直接试跑逻辑」的开源用户用，
  日志退回代码仓库的 `logs/`（gitignore）。

## 约束（改代码时别破坏）

1. `context.py` 是**唯一**读数据文件路径的模块，其他模块只能通过 `load_*()` 拿内容。
2. 任何模块不得硬编码个人路径、姓名、公司名、薪资数字、API Key 或真实接口地址；
   接口参数一律经 `config.SETTINGS` 传入 `ai.Replier`，隐私回归测试见 `tests/`。
3. 数据是**只读**的：除 `logs/` 外，程序不向数据仓库写任何文件。
4. 改数据不需要重启进程 —— `load_pack()` / `load_examples()` / `load_contact_pack()`
   都是每次触发现读。
5. 数据仓库含真实个人信息，**不要 push 到远程、不要设为 public**；
   代码仓库公开前必须跑一遍敏感词扫描。

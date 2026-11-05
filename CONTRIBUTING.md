# 贡献指南

欢迎 fork。这是个**纯逻辑仓库**：代码可以公开、可以随便改；个人数据永远不进这里。

## Fork 之后

```bash
git clone https://github.com/<你的账号>/wechat-job-copilot.git
cd wechat-job-copilot
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m unittest discover -s tests -v
```

18 项离线单测**不需要微信在线、不需要 API Key、不需要装上游库**（`wechatauto-replica`
是运行时懒加载）。改完代码先跑一遍，CI 也会在 push / PR 时自动跑。

想真机试跑，再按 README 装上游、用 `scripts\init_data_repo.bat` 生成私人数据仓库。

## 提 PR 前的红线

- **不要提交任何个人数据**：`.env`、`ai_provider.env`、`口径包.md`、`examples.md`、
  `contacts/*.md`、聊天记录、运行日志、真实姓名/公司名/薪资数字/个人路径/API Key。
  本仓库的 `.gitignore` 已经挡了一层，但请在 `git diff --cached` 里再扫一眼。
- **不要硬编码路径**：所有数据路径必须经 `DATA_DIR` 派生，且只有 `copilot/context.py`
  能读数据文件；接口参数一律从 `config.SETTINGS` 传给 `ai.Replier`。
- **上游失配只改 `copilot/adapter.py`**：微信客户端升级后不要改业务层去适配上游，
  适配层的存在就是为了让其余模块零改动。
- 新增可配置项时，同步更新 `.env.example` / `ai_provider.env.example` 的空白模板与注释，
  以及 `DATA_CONTRACT.md`。
- 新增逻辑请补离线单测；`tests/test_offline.py` 里有隐私回归用例，别删。

## 边界

- 本项目只做「自己账号的求职/HR 对话辅助」，不提供批量加人、群发、营销能力，
  这类 PR 不会被合并。
- 第三方客户端自动化有账号风控风险，与本仓库无关的账号问题请在 Issue 里说明，
  maintainer 不提供规避封号的支持。
- 上游 [wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica)
  是 Apache-2.0，署名见 `NOTICE`；本仓库代码是 MIT。

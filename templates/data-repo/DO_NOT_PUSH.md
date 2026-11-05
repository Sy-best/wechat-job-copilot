# ⛔ 这个目录永不推云

这里是**私人数据仓库**：微信聊天留痕、薪资口径、猎头档案、API Key、求职笔记、运行日志。
逻辑仓库（代码）可以公开、可以 fork；这个目录存在的意义就是让个人消息一条都不上云。

- ❌ `git remote add` / `git push` / GitHub private 远端
- ❌ 设为 public、加 collaborator、把 `.git` 打包发给别人
- ❌ 放进任何云同步盘（网盘、笔记同步、同步文件夹）
- ✅ 备份：整个目录打包到本机另一块盘或离线 U 盘

如果确实要在这个目录里做本地版本管理，先把下面这些加进 `.gitignore`
（初始化脚本已经生成好了）：`.env`、`ai_provider.env`、`_copilot_home.bat`、`logs/`。

要分享给别人用的只有逻辑仓库里的 `*.example` 空白模板，永远不是这个目录。

# Git 推送

本仓库的已批准上游为 `origin/feat/pageindex`：
`https://github.com/harryzhang-carefold/kb-management.git`。

当前本机 macOS Keychain 的 GitHub 账号 `wang-yingke` 对该仓库返回 403。
既有可用推送凭据位于部署服务器 `35.209.183.7` 的
`/opt/carefold-agent/.git/config`，由该部署仓库的 HTTPS origin 保存。
它与本机 Keychain、KB MCP 凭据及模型 API key 分开。

在本地 `feat/pageindex` 分支完成修改、验证、CHANGELOG 和 commit 后运行：

```bash
python3 scripts/push_upstream.py
```

入口通过 `yk@35.209.183.7` 和 `~/.ssh/id_ed25519` 登录，使用现有免交互
sudo 只读取得 GitHub 凭据，再推送本地 HEAD 到 `origin/feat/pageindex`。
服务器只提供既有认证资料，不替代本地提交，也不从服务器上传工作树。

需要使用另一套已授权 SSH 连接时，设置 `CAREFOLD_DEPLOY_HOST` 和
`CAREFOLD_DEPLOY_IDENTITY_FILE`。凭据读取失败时先核对 SSH、sudo 和上述
origin 配置；403 表示当前凭据不能写入目标仓库，不能据此认定网络不通。

口令只存在于推送进程内存；临时 askpass 文件仅引用环境变量，结束后删除。
该入口不会改变本机 Keychain、Git 全局配置或仓库远端，不把口令写入文档、
命令参数、日志或 Git。文档保存可重复执行的读取位置和步骤。

推送不等于 KB 已部署。发布继续使用本仓库版本化 `scripts/deploy_runtime.sh`，
按既有部署流程核对同一 commit 和真实知识读取结果。

# Tk GUI（旧版/可选）

该目录保留为旧版 GUI 参考实现；当前项目推荐使用 `webview_gui/`（pywebview WebView2）作为主要图形界面。

## ✅ 重要变化（请先读）

- 配置：已改为**程序内部存储**（Windows：当前用户注册表），不再从工作目录读取 `config.toml` / `team.json`。
- 输出：账号/凭据/追踪已改为写入**内部数据库**（Windows：`%LOCALAPPDATA%/OaiTeamAutoProvisioner/data.sqlite`），默认不会在工作目录生成 `accounts.csv` / `created_credentials.csv` / `team_tracker.json`。
- 导出：需要文件时，请在 WebView GUI 的「数据/导出」页导出到 `工作目录/exports/`。

## ▶️ 运行（源码）

在仓库根目录执行：

```bash
python -m tk_gui
```

> 提示：若你要用 Tk GUI 跑任务，请先用 `python -m webview_gui` 在「配置编辑」页保存好配置（写入内部存储），再在 Tk GUI 中执行任务。


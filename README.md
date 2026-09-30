# work-log

## 每周精力分布

![每周精力分布](charts/effort-latest.png)

每周五自动更新 · 历史图见 [charts/](charts/) · 周报见 [reports/](reports/)

## 每日记录与计划

全部由代码自动生成，不调用 AI（纽约时间）：工作日 07:15 左右计划 → [plans/](plans/)，18:15 左右当天记录 → [logs/](logs/)；周五 18:20 左右周报 → [reports/](reports/)。详细说明见 [.github/scripts/worklog.md](.github/scripts/worklog.md)，日常用法见 [help.md](help.md)。

---

## 系统设计（复用到其他工程时参考）

### 组成

| 组件 | 触发 | 做什么 | 是否用 AI |
|---|---|---|---|
| `workflows/daily-log.yml` + `scripts/worklog.py log` | 工作日 18:17 起 | 抓取上次日志以来所有 issue 评论和新建/关闭/重开事件，按父 issue 分组，写入 `logs/YYYY/日期.md` | 否 |
| `workflows/morning-plan.yml` + `scripts/worklog.py plan` | 工作日 07:17 起 | 按看板 Status 列出进行中/待办/阻塞，附最近记录、隔夜动态、7 天未动项，写入 `plans/YYYY/日期.md` | 否 |
| `workflows/weekly-summary.yml` + `scripts/worklog.py week` + `scripts/weekly_report.py` | 周五 18:20 起 | 周报：各工作线概况表、本周关闭/新建、7 天未动项、按工作线分组的全部评论，写入 `reports/YYYY/YYYY-Www.md`；另画每日活跃度和每周精力分布图 | 否 |

`worklog.py` 只用 Python 标准库；画图的 `weekly_report.py` 需要 matplotlib（workflow 中自动安装）。

### 设计原则

1. **自动产出全部由代码生成，AI 只在人工环节使用**。让 AI 自己去翻 issue 会漏条目、编时间（Copilot 实测漏掉了当天关闭的 #21，把 issue 正文当评论，并编造了事件时间）。脚本取数是确定性的；需要润色成邮件时，把脚本产出的文件贴给 AI，再人工审核。
2. **每条内容都能追溯**。日志和周报的每条评论都附链接；AI 润色后的文字，凡是在原始文件里找不到依据的都删掉。
3. **滚动窗口，不留缝隙**。日志和周报的窗口都是"上次结束 → 本次运行"，状态保存在 `logs/.state.json`。18:00 后的评论进入第二天，周一覆盖整个周末；周报从上周五 18:20 接续；重跑会重新生成同一窗口。
4. **定时不可靠 → 多次重试 + 本地时间判断 + 幂等**。GitHub 定时任务常延迟甚至被丢弃（本仓库实测：一次晚了 5.5 小时，一次整个没触发）。每个 workflow 排多个 UTC 时刻（每 30 分钟左右一次），覆盖夏令时和冬令时；脚本按纽约时间判断星期和时刻，第一次成功后，后续运行发现文件已存在即跳过。
5. **原始记录进 git**。日志、计划每天一个文件，周报每周一个，按年分目录，有完整历史，可检索，可作为汇报和论文素材的原始依据。
6. **不依赖外部 AI 服务**。GitHub Models 已于 2026-07-30 停止服务，这类托管服务随时可能变化；自动流程只依赖 GitHub API，长期稳定。

### 记录习惯

- 进展随手写成 issue **评论**，带板号、数值、条件、结果（如"CTS#2 冷测试，数据连接失败，换线后恢复"），不要只写"好了"。
- 有明确终点的事才开 issue，开时写一句**完成标准**；零散想法先记在一个 Inbox issue 里。
- 持续性工作（shifter、日常维护）保持 open，不计入完成率。
- 看板状态：Backlog → Todo → In Progress → Done / Blocked。计划只展开 Todo / In Progress / Blocked，Backlog 只计数。
- 每周看一次计划里"超过 7 天无更新"的项：推进、退回 Backlog，或关闭（completed / not planned）。

### 复用到其他仓库

1. 复制 `.github/scripts/worklog.py`、`.github/workflows/daily-log.yml`、`.github/workflows/morning-plan.yml`；需要周报时再复制 `weekly-summary.yml` 和 `weekly_report.py`。
2. **Settings → Actions → General → Workflow permissions** 选 *Read and write*。
3. 可选：Secret `PROJECT_TOKEN`（classic PAT，`read:project`）+ Variable `PROJECT_NUMBER`，计划按看板 Status 分组；不配则按最近更新列出 open issue。
4. 时区或时间点不同：改脚本中的 `NY` 时区，以及 workflow 里的 cron（多个重试时刻）和 `--at-hour`。
5. Actions 页面手动 *Run workflow*（勾选 force）验证一次。

注意：仓库为 public 时，`logs/`、`plans/`、`reports/` 同样公开；工作记录建议放在私有仓库。

### 用 AI 写日报 / 周报

把当天的 `logs/…/日期.md`（或本周的 `reports/…/YYYY-Www.md`）贴给 Claude 或 Copilot，附上：

```
下面是 work-log 的原始记录（脚本抓取，未经处理）。请按工作线写一份英文日报（或周报）邮件：
- 只使用记录中的内容，不补充结论（只写"测试了"就不要写"通过"）；
- 保留板号、人名、数值原文；
- 每条工作线列出完成的事、当前问题；需要协调的单独列出。
```

发出前核对板号、数值和结论，凡是在原始记录里找不到依据的都删掉。

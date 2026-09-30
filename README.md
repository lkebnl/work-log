# work-log

## 每周精力分布

![每周精力分布](charts/effort-latest.png)

每周五自动更新 · 历史图见 [charts/](charts/) · 周报见 [Issues](../../issues?q=周报)

## 每日记录与计划

工作日自动生成（纽约时间）：08:00 计划 → [plans/](plans/)，18:00 当天记录 → [logs/](logs/)。详细说明见 [.github/scripts/worklog.md](.github/scripts/worklog.md)，日常用法见 [help.md](help.md)。

---

## 系统设计（复用到其他工程时参考）

### 组成

| 组件 | 触发 | 做什么 | 是否用 AI |
|---|---|---|---|
| `workflows/daily-log.yml` + `scripts/worklog.py log` | 工作日 18:00 | 抓取上次日志以来所有 issue 评论和新建/关闭/重开事件，按父 issue 分组，写入 `logs/YYYY/日期.md` | 否 |
| `workflows/morning-plan.yml` + `scripts/worklog.py plan` | 工作日 08:00 | 按看板 Status 列出进行中/待办/阻塞，附最近记录、隔夜动态、7 天未动项；顶部 3–5 条 AI 建议 | 仅建议部分 |
| `workflows/weekly-summary.yml` + `scripts/weekly_report.py` | 每周五 | 周报 issue：精力分布图、计数表、按工作线分组的原始日志 | 否 |

脚本只用 Python 标准库，不需要安装依赖。

### 设计原则

1. **取数据用代码，AI 只负责表达**。让 AI 自己去翻 issue 会漏条目、编时间（Copilot 实测漏掉了当天关闭的 #21，把 issue 正文当评论，并编造了事件时间）。脚本取数是确定性的，AI 只处理脚本给出的文本。
2. **AI 输出必须能追溯**。日志每条附评论链接；计划中的 AI 建议只能引用清单内的 issue 编号，引用了清单外编号的建议会被自动剔除；模型调用失败时退回纯代码输出。
3. **滚动窗口，不留缝隙**。日志窗口是"上次结束 → 本次运行"，状态保存在 `logs/.state.json`。18:00 后的评论进入第二天，周一覆盖整个周末；重跑当天会重新生成同一窗口。
4. **cron 只认 UTC → 双时刻 + 本地时间判断**。每个 workflow 同时排夏令时和冬令时对应的两个 UTC 时刻，脚本按纽约时间只执行一次；同一天文件已存在则跳过，定时延迟不影响结果。
5. **原始记录进 git**。每天一个 Markdown 文件，按年分目录，有完整历史，可检索，可作为日报/周报/论文素材的原始依据。

### 记录习惯

- 进展随手写成 issue **评论**，带板号、数值、条件、结果（如"CTS#2 冷测试，数据连接失败，换线后恢复"），不要只写"好了"。
- 有明确终点的事才开 issue，开时写一句**完成标准**；零散想法先记在一个 Inbox issue 里。
- 持续性工作（shifter、日常维护）保持 open，不计入完成率。
- 看板状态：Backlog → Todo → In Progress → Done / Blocked。计划只展开 Todo / In Progress / Blocked，Backlog 只计数。
- 每周看一次计划里"超过 7 天无更新"的项：推进、退回 Backlog，或关闭（completed / not planned）。

### 复用到其他仓库

1. 复制 `.github/scripts/worklog.py`、`.github/workflows/daily-log.yml`、`.github/workflows/morning-plan.yml`。
2. **Settings → Actions → General → Workflow permissions** 选 *Read and write*。
3. 可选：Secret `PROJECT_TOKEN`（classic PAT，`read:project`）+ Variable `PROJECT_NUMBER`，计划按看板 Status 分组；不配则按最近更新列出 open issue。
4. 可选 AI 建议（二选一，都不配则计划只有清单）：Secret `COPILOT_GITHUB_TOKEN`（fine-grained PAT，账户权限 *Copilot Requests*，需个人 Copilot 订阅，消耗 Copilot 额度），或 Secret `ANTHROPIC_API_KEY`（Claude API，默认 Haiku 4.5）。Variable `PLAN_AI=0` 可关闭。
   注意：GitHub Models 已于 2026-07-30 停止服务，不要再用。
5. 时区或时间点不同：改脚本中的 `NY` 时区，以及 workflow 里的两个 cron 和 `--at-hour`。
6. Actions 页面手动 *Run workflow*（勾选 force）验证一次。

注意：仓库为 public 时，`logs/` 和 `plans/` 同样公开。

### 用 Claude 写日报

把当天 `logs/…/日期.md` 贴给 Claude，附上：

```
下面是 work-log 当天的原始记录（脚本抓取，未经处理）。请按工作线写一份英文日报邮件：
- 只使用记录中的内容，不补充结论（只写"测试了"就不要写"通过"）；
- 保留板号、人名、数值原文；
- 每条工作线列出完成的事、当前问题；需要协调的单独列出。
```

发出前核对板号、数值和结论，凡是在原始记录里找不到依据的都删掉。

# 自动工作记录

三个 GitHub Actions workflow，全部由脚本生成，不调用 AI：

| 时间（纽约） | workflow | 输出 |
|---|---|---|
| 工作日凌晨 03:17 起 | `morning-plan.yml` | `plans/YYYY/YYYY-MM-DD.md` |
| 工作日 18:17 起 | `daily-log.yml` | `logs/YYYY/YYYY-MM-DD.md` |
| 周五 18:20 起 | `weekly-summary.yml` | `reports/YYYY/YYYY-Www.md` + `charts/` 两张图 |

每次运行的结果也会显示在 Actions 页面对应 run 的 Summary 里，可以直接复制。

## 日志（18:17 起）

- **滚动窗口**：从上一次日志结束到本次运行，不留缝隙。18:00 之后的评论进入第二天的记录；周一的记录覆盖周五 18:00 到周一 18:00。
- 收录每个 issue 的**全部评论原文**和**状态事件**（新建 / 关闭 / 重开），按父 issue 分组，每条附评论链接。
- issue 正文不收录。
- 末尾列出本窗口无更新的 open issue。

## 计划（凌晨 03:17 起）

- 按 Project 的 Status 字段列出 **In Progress / Todo / Blocked**，每项附上一条最近的评论，方便接上昨天的进度。
- 列出上次日志之后（前一天 18:00 后）的新动态。
- 列出超过 7 天没有更新的 In Progress / Todo 项。
- Backlog 和没有设置状态的只统计数量，不展开。

## 周报（周五 18:20 起）

- **滚动窗口**：从上一份周报结束到本次运行（第一份从本周一 00:00 开始），状态同样保存在 `logs/.state.json`。
- 内容：各工作线概况表（评论数、新建、关闭、有活动的 issue）→ 本周关闭 → 本周新建 → 超过 7 天无更新的 open issue → 按工作线分组的全部评论原文（带链接）。
- 同时画每日活跃度图和每周精力分布图，周报里直接引用。
- 手动补生成：Actions → *Weekly work-log summary* → Run workflow，勾选 force（不限星期）。

## 一次性设置

1. 合并本 PR（`.github/scripts/worklog.py` 与两个 workflow）。
2. **Settings → Actions → General → Workflow permissions** 选 *Read and write permissions*（用于提交日志文件）。
3. 计划读取 Project 状态（可选，但建议配置）：
   - 创建一个 classic PAT，勾选 `read:project`（加上 `repo`，如果仓库改为 private）。
   - **Settings → Secrets and variables → Actions**：
     - Secret `PROJECT_TOKEN` = 上面的 PAT
     - Variable `PROJECT_NUMBER` = Project 网址 `.../projects/<N>` 中的 N
   - 未配置时，计划会退化为按最近更新列出所有 open issue。
4. 在 Actions 页面手动运行一次（*Run workflow*，勾选 force）验证。

## 注意

- Actions 的定时任务经常延迟，高峰时段还会被丢弃（本仓库实测晚过 5.5 小时，也整次没触发过），所以每个 workflow 每 30 分钟左右重试一次，文件已存在即跳过。时刻表见 [help.md](../../help.md) 的"定时"一节。
- cron 只支持 UTC；脚本按纽约时间判断星期和时刻，夏令时、冬令时都不用改。
- 如需补某段时间的记录：`python3 .github/scripts/worklog.py log --start 2026-09-29T04:00:00Z --end 2026-09-30T04:00:00Z --force`（不会改动滚动状态）。
- 仓库是 public 时，生成的日志也是公开的。

## 粘贴给 Claude 的总结 prompt

```
下面是 work-log 当天的原始记录（脚本抓取，未经处理）。请按工作线写一份英文日报邮件：
- 只使用记录中的内容，不补充结论（只写"测试了"就不要写"通过"）；
- 保留板号、人名、数值原文；
- 每条工作线列出完成的事、当前问题；有"需要协调"的单独列出；
- 状态变化（关闭）只陈述事实。

<粘贴 logs/…/YYYY-MM-DD.md 的内容>
```

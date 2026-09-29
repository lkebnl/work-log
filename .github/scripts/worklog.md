# 自动工作记录

两个 GitHub Actions workflow，只用脚本抓取数据，不经过 AI：

| 时间（纽约，工作日） | workflow | 输出 |
|---|---|---|
| 08:00 | `morning-plan.yml` | `plans/YYYY/YYYY-MM-DD.md` |
| 18:00 | `daily-log.yml` | `logs/YYYY/YYYY-MM-DD.md` |

每次运行的结果也会显示在 Actions 页面对应 run 的 Summary 里，可以直接复制。

## 日志（18:00）

- **滚动窗口**：从上一次日志结束到本次运行，不留缝隙。18:00 之后的评论进入第二天的记录；周一的记录覆盖周五 18:00 到周一 18:00。
- 收录每个 issue 的**全部评论原文**和**状态事件**（新建 / 关闭 / 重开），按父 issue 分组，每条附评论链接。
- issue 正文不收录。
- 末尾列出本窗口无更新的 open issue。

## 计划（08:00）

- 按 Project 的 Status 字段列出 **In Progress / Todo / Blocked**，每项附上一条最近的评论，方便接上昨天的进度。
- 列出上次日志之后（前一天 18:00 后）的新动态。
- 列出超过 7 天没有更新的 In Progress / Todo 项。
- Backlog 和没有设置状态的只统计数量，不展开。

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

- Actions 的定时任务在高峰时段可能延迟 10–30 分钟；脚本以纽约时间判断，延迟不影响结果。
- cron 只支持 UTC，所以每个 workflow 排了两个时间（分别对应夏令时和冬令时），脚本只执行正确的那一次。
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

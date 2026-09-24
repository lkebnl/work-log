"""
work-log 周报 + 每周精力分布图

每周运行一次：
  1. 拉取仓库所有 issue、sub-issue 父子关系、最近 N 周的 comment
  2. sub-issue 的 comment 归到它的顶层工作线（如 #14 shifter -> [FEMB] #11）
  3. 画出最近 N 周各工作线的日志条数堆叠柱状图 -> charts/effort-latest.png
  4. 用 GitHub Models 把本周日志整理成周报 -> summary.md

环境变量：
  REPO      owner/repo（Actions 里自动传入）
  GH_TOKEN  GitHub token（Actions 里用 github.token）
  DAYS      周报覆盖最近几天，默认 7
  WEEKS     图表显示最近几周，默认 8
  MODEL     GitHub Models 的模型名，默认 openai/gpt-4.1-mini
  LANG      输出语言：en（默认）或 zh
  DEMO=1    不联网，用样例数据测试出图
"""
import collections, datetime as dt, json, os, random, re, urllib.request
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

TZ = ZoneInfo("America/New_York")
REPO = os.environ.get("REPO", "lkebnl/work-log")
TOKEN = os.environ.get("GH_TOKEN", "")
DAYS = int(os.environ.get("DAYS", "7"))
WEEKS = int(os.environ.get("WEEKS", "8"))
MODEL = os.environ.get("MODEL", "openai/gpt-4.1-mini")
DEMO = os.environ.get("DEMO") == "1"
LANG = os.environ.get("REPORT_LANG", os.environ.get("LANG_OUT", "en")).lower()
LANG = "zh" if LANG.startswith("zh") else "en"

T = {
    "en": {
        "ylabel": "Log entries", "xlabel": "Week (starting Monday)",
        "title": "Weekly effort by workstream · {repo} (sub-issues rolled up)",
        "h_chart": "Weekly effort distribution", "alt": "Weekly effort distribution",
        "col": ("Workstream", "This week", "Last {n} weeks"),
        "raw": "This week's raw log", "none": "none",
        "empty": "_No new log entries this week._", "demo": "_(Demo mode, model not called.)_",
        "fail": "_Summary generation failed: {e}_",
        "prompt": ("Below are my daily progress notes from this week, grouped by workstream "
                   "(sub-issues are rolled up into their parent workstream). Some notes are in Chinese. "
                   "Write a concise weekly report in English for my supervisor: for each workstream give "
                   "2-4 bullet points covering what was done, results/data, and next steps. "
                   "Do not invent anything not in the notes; keep board IDs, serial numbers and other "
                   "identifiers exactly as written. End with a short list of cross-workstream risks or open items.\n\n"),
    },
    "zh": {
        "ylabel": "日志条数", "xlabel": "周（周一起）",
        "title": "每周精力分布 · {repo} · 按工作线（sub-issue 归入父级）",
        "h_chart": "每周精力分布", "alt": "每周精力分布",
        "col": ("工作线", "本周条数", "近 {n} 周合计"),
        "raw": "本周原始日志", "none": "无",
        "empty": "_本周没有新的日志。_", "demo": "_（测试模式，未调用模型）_",
        "fail": "_周报生成失败：{e}_",
        "prompt": ("下面是我这一周在各工作线下记录的每日进展（sub-issue 已归入所属工作线）。"
                   "请整理成简洁的中文周报：每条工作线 2-4 个要点，写清完成了什么、结果/数据、下一步。"
                   "不要编造日志中没有的内容，保留板号、编号等原始信息。最后列出跨工作线的风险或待办。\n\n"),
    },
}[LANG]

# 固定顺序的分类色（按工作线 issue 编号排序后依次分配，颜色跟着工作线走）
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


# ---------- GitHub API ----------
def api(path):
    url = path if path.startswith("http") else f"https://api.github.com/{path}"
    out = []
    while url:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(req) as r:
            data = json.load(r)
            link = r.headers.get("Link", "")
        if isinstance(data, dict):
            return data
        out += data
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out


def short_label(title):
    m = re.match(r"\s*\[([^\]]+)\]", title)
    s = m.group(1) if m else title
    return s if len(s) <= 22 else s[:21] + "…"


def load_real(since_utc):
    issues = [i for i in api(f"repos/{REPO}/issues?state=all&per_page=100") if "pull_request" not in i]
    by_num = {i["number"]: i for i in issues}
    parent = {}
    for i in issues:
        if (i.get("sub_issues_summary") or {}).get("total"):
            for c in api(f"repos/{REPO}/issues/{i['number']}/sub_issues?per_page=100"):
                parent[c["number"]] = i["number"]
    stamp = since_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    comments = []
    for c in api(f"repos/{REPO}/issues/comments?since={stamp}&per_page=100"):
        created = dt.datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
        if created < since_utc:          # since 按 updated_at 过滤，这里再按创建时间筛
            continue
        num = int(c["issue_url"].rsplit("/", 1)[1])
        if num in by_num:
            comments.append({"issue": num, "created": created, "body": c["body"].strip()})
    return by_num, parent, comments


def load_demo(since_utc):
    titles = {6: "[WIB] 本周核心工作", 7: "[ISEG / WIEC] 本周核心工作", 8: "[LN2 Dewar Refill]",
              11: "[FEMB] 本周核心工作", 12: "[Cable] 本周核心工作", 13: "CRP Patch Panel",
              14: "shifter for HD / VD FEMB 09232026", 15: "paper for FEMB QC"}
    by_num = {n: {"number": n, "title": t} for n, t in titles.items()}
    parent = {14: 11, 15: 11}
    rnd = random.Random(7)
    weight = {6: 1.2, 7: 2, 8: 1, 11: 3, 12: 1, 13: 1.6, 14: 1, 15: .9}
    comments, t = [], since_utc
    now = dt.datetime.now(dt.timezone.utc)
    while t < now:
        if t.astimezone(TZ).weekday() < 5:
            for n, w in weight.items():
                for _ in range(int(rnd.random() * w * 1.3)):
                    comments.append({"issue": n, "created": t + dt.timedelta(hours=rnd.randint(9, 18)),
                                     "body": f"示例日志 #{n}"})
        t += dt.timedelta(days=1)
    return by_num, parent, comments


# ---------- 聚合 ----------
def top_level(num, parent):
    seen = set()
    while num in parent and num not in seen:
        seen.add(num)
        num = parent[num]
    return num


def week_start(d):
    local = d.astimezone(TZ).date()
    return local - dt.timedelta(days=local.weekday())


# ---------- 出图 ----------
def pick_font():
    names = {f.name for f in font_manager.fontManager.ttflist}
    for n in ["Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans SC", "WenQuanYi Zen Hei", "Source Han Sans SC"]:
        if n in names:
            return n
    return "DejaVu Sans"


def draw(weeks, streams, counts, labels, path):
    plt.rcParams.update({"font.family": pick_font(), "font.size": 10, "axes.unicode_minus": False})
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160)
    fig.patch.set_facecolor("#fcfcfb"); ax.set_facecolor("#fcfcfb")
    x = range(len(weeks))
    bottom = [0] * len(weeks)
    for k, s in enumerate(streams):
        vals = [counts[w].get(s, 0) for w in weeks]
        ax.bar(x, vals, width=0.58, bottom=bottom, color=PALETTE[k % len(PALETTE)],
               edgecolor="#fcfcfb", linewidth=1.5, label=labels[s], zorder=3)
        bottom = [b + v for b, v in zip(bottom, vals)]
    for i, total in enumerate(bottom):
        if total:
            ax.text(i, total + max(bottom) * 0.015, str(total), ha="center", va="bottom", fontsize=9, color="#0b0b0b")
    ax.set_xticks(list(x), [f"{w.month}/{w.day}" for w in weeks], color="#52514e")
    ax.set_ylabel(T["ylabel"], color="#52514e")
    ax.set_title(T["title"].format(repo=REPO), loc="left", fontsize=12, color="#0b0b0b", pad=12)
    ax.grid(axis="y", color="#e1e0d9", linewidth=0.8, zorder=0)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(axis="both", length=0, colors="#52514e")
    ax.set_xlabel(T["xlabel"], color="#898781")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


# ---------- 周报 ----------
def summarize(log):
    prompt = T["prompt"] + log
    req = urllib.request.Request(
        "https://models.github.ai/inference/chat/completions",
        data=json.dumps({"model": MODEL, "temperature": 0.2,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def main():
    now = dt.datetime.now(dt.timezone.utc)
    this_monday = week_start(now)
    first_monday = this_monday - dt.timedelta(weeks=WEEKS - 1)
    since = dt.datetime.combine(first_monday, dt.time(), TZ).astimezone(dt.timezone.utc)

    by_num, parent, comments = (load_demo if DEMO else load_real)(since)

    # 图表数据
    weeks = [first_monday + dt.timedelta(weeks=i) for i in range(WEEKS)]
    counts = {w: collections.Counter() for w in weeks}
    for c in comments:
        counts[week_start(c["created"])][top_level(c["issue"], parent)] += 1
    streams = sorted({s for w in weeks for s in counts[w]})
    labels = {s: f"{short_label(by_num[s]['title'])} #{s}" for s in streams}

    os.makedirs("charts", exist_ok=True)
    stamp = now.astimezone(TZ).date().isoformat()
    draw(weeks, streams, counts, labels, "charts/effort-latest.png")
    draw(weeks, streams, counts, labels, f"charts/effort-{stamp}.png")

    # 本周日志，按顶层工作线分组
    cutoff = now - dt.timedelta(days=DAYS)
    groups = collections.defaultdict(list)
    for c in sorted(comments, key=lambda c: c["created"]):
        if c["created"] >= cutoff:
            top = top_level(c["issue"], parent)
            sub = "" if top == c["issue"] else f"（{by_num[c['issue']]['title']} #{c['issue']}）"
            groups[top].append(f"- [{c['created'].astimezone(TZ):%m-%d}] {sub}{c['body']}")
    log = "\n\n".join(f"## {by_num[n]['title']} #{n}\n" + "\n".join(v) for n, v in sorted(groups.items()))

    # 本周计数表（图片加载不出来时也能看）
    wk = counts[this_monday]
    c1, c2, c3 = T["col"]
    table = f"| {c1} | {c2} | {c3.format(n=WEEKS)} |\n|---|---:|---:|\n"
    for s in sorted(streams, key=lambda s: -wk.get(s, 0)):
        table += f"| {labels[s]} | {wk.get(s, 0)} | {sum(counts[w].get(s, 0) for w in weeks)} |\n"

    if not groups:
        text = T["empty"]
    elif DEMO or not TOKEN:
        text = T["demo"]
    else:
        try:
            text = summarize(log)
        except Exception as e:  # 模型调用失败时仍然发布图表和原始日志
            text = T["fail"].format(e=e)

    img = f"https://raw.githubusercontent.com/{REPO}/HEAD/charts/effort-{stamp}.png"
    with open("summary.md", "w") as f:
        f.write(f"{text}\n\n## {T['h_chart']}\n\n![{T['alt']}]({img})\n\n{table}\n"
                f"<details><summary>{T['raw']}</summary>\n\n{log or T['none']}\n\n</details>\n")
    print(f"weeks={len(weeks)} streams={len(streams)} comments={len(comments)} this_week={sum(wk.values())}")


if __name__ == "__main__":
    main()

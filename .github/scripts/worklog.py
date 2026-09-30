#!/usr/bin/env python3
"""
work-log automation (standard library only).

  python3 .github/scripts/worklog.py log   [--at-hour 18] [--force] [--start ISO] [--end ISO]
  python3 .github/scripts/worklog.py plan  [--at-hour 8]  [--force]
  python3 .github/scripts/worklog.py week  [--at-hour 18] [--force] [--start ISO]

log  : rolling window from the end of the previous log to now. Collects every
       issue comment and open/close/reopen event, grouped by parent issue.
       Output: logs/YYYY/YYYY-MM-DD.md. No AI anywhere in this script; issue bodies are skipped.
plan : today's plan from the Project "Status" field (In Progress / Todo /
       Blocked), with each item's latest comment, activity since the last log,
       and stale items. Output: plans/YYYY/YYYY-MM-DD.md.
week : weekly report (Fridays). Rolling window since the previous report:
       per-workstream counts, issues closed / opened, stale items, and every
       comment grouped by parent issue. Output: reports/YYYY/YYYY-Www.md.

Environment:
  GITHUB_TOKEN     required (provided automatically in Actions)
  REPO             owner/name, default lkebnl/work-log
  PROJECT_TOKEN    optional, classic PAT with read:project (needed for Status)
  PROJECT_OWNER    optional, project owner login, default = REPO owner
  PROJECT_NUMBER   optional, the N in .../projects/N
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
API = "https://api.github.com"
REPO = os.environ.get("REPO") or "lkebnl/work-log"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
ROOT = Path(os.environ.get("WORKLOG_ROOT", "."))
STATE = ROOT / "logs" / ".state.json"
WEEKDAY = "一二三四五六日"
STALE_DAYS = 7


# ---------------------------------------------------------------- GitHub API
def _request(url, data=None, token=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "work-log-bot",
    }
    tok = token or TOKEN
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r), r.headers.get("Link", "")


def _next(link):
    m = re.search(r'<([^>]+)>;\s*rel="next"', link or "")
    return m.group(1) if m else None


def get(path, **params):
    """GET with automatic pagination for list endpoints."""
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data, link = _request(url)
    if not isinstance(data, list):
        return data
    out = list(data)
    while (url := _next(link)):
        data, link = _request(url)
        out.extend(data)
    return out


# ---------------------------------------------------------------- helpers
def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def nyf(t, fmt="%m-%d %H:%M"):
    return t.astimezone(NY).strftime(fmt)


def day_title(t):
    d = t.astimezone(NY)
    return f"{d:%Y-%m-%d}（周{WEEKDAY[d.weekday()]}）"


def snippet(text, n=140):
    s = re.sub(r"\s+", " ", text or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def quote(text):
    lines = (text or "").strip().splitlines() or [""]
    return "\n".join("  > " + ln if ln.strip() else "  >" for ln in lines)


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2) + "\n")


def summary(md):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")


# ---------------------------------------------------------------- data
def all_issues():
    return [i for i in get(f"/repos/{REPO}/issues", state="all", per_page=100)
            if "pull_request" not in i]


def parent_map(issues):
    """child number -> (parent number, parent title)."""
    pm = {}
    for i in issues:
        if (i.get("sub_issues_summary") or {}).get("total"):
            try:
                for c in get(f"/repos/{REPO}/issues/{i['number']}/sub_issues", per_page=100):
                    pm[c["number"]] = (i["number"], i["title"])
            except urllib.error.HTTPError as e:
                print(f"warn: sub_issues #{i['number']}: {e}", file=sys.stderr)
    return pm


def activity(start, end, issues):
    """[(issue, [entry...])] for issues with comments/events in [start, end)."""
    res = []
    for i in issues:
        if ts(i["updated_at"]) < start:
            continue
        n, entries = i["number"], []
        created = ts(i["created_at"])
        if start <= created < end:
            entries.append({"t": created, "kind": "event", "text": "新建",
                            "who": (i.get("user") or {}).get("login"), "url": i["html_url"]})
        for c in get(f"/repos/{REPO}/issues/{n}/comments", since=iso(start), per_page=100):
            t = ts(c["created_at"])
            if start <= t < end:
                entries.append({"t": t, "kind": "comment", "text": c.get("body") or "",
                                "who": (c.get("user") or {}).get("login"), "url": c["html_url"]})
        for e in get(f"/repos/{REPO}/issues/{n}/events", per_page=100):
            if e.get("event") not in ("closed", "reopened"):
                continue
            t = ts(e["created_at"])
            if not (start <= t < end):
                continue
            if e["event"] == "closed":
                r = e.get("state_reason")
                label = f"关闭（{r}）" if r else "关闭"
            else:
                label = "重新打开"
            entries.append({"t": t, "kind": "event", "text": label,
                            "who": (e.get("actor") or {}).get("login"), "url": i["html_url"]})
        if entries:
            entries.sort(key=lambda x: x["t"])
            res.append((i, entries))
    return res


def group_key(issue, pm):
    return pm.get(issue["number"], (issue["number"], issue["title"]))


# ---------------------------------------------------------------- log
def render_groups(acts, pm, level=2):
    """Activity grouped by parent issue (workstream), full comment text with links."""
    out = []
    h = "#" * level
    groups = {}
    for i, es in acts:
        groups.setdefault(group_key(i, pm), []).append((i, es))

    def last_t(items):
        return max(e["t"] for _, es in items for e in es)

    for (pn, ptitle), items in sorted(groups.items(), key=lambda kv: last_t(kv[1]), reverse=True):
        out += [f"{h} {ptitle} #{pn}", ""]
        items.sort(key=lambda it: (not any(e["text"].startswith("关闭") for e in it[1]),
                                   -max(e["t"] for e in it[1]).timestamp()))
        for i, es in items:
            out.append(f"{h}# #{i['number']} {i['title']} · {i['state']}")
            out.append("")
            for e in es:
                who = f" · {e['who']}" if e["who"] else ""
                if e["kind"] == "comment":
                    out.append(f"- **{nyf(e['t'])}**{who} · [评论]({e['url']})")
                    out.append(quote(e["text"]))
                else:
                    out.append(f"- **{nyf(e['t'])}**{who} · 状态：{e['text']}")
            out.append("")

    return out


def render_log(start, end, acts, issues, pm):
    n_comments = sum(1 for _, es in acts for e in es if e["kind"] == "comment")
    n_closed = sum(1 for _, es in acts if any(e["text"].startswith("关闭") for e in es))
    n_new = sum(1 for _, es in acts if any(e["text"] == "新建" for e in es))
    out = [
        f"# 工作记录 {day_title(end)}",
        "",
        f"- 窗口（纽约）：{nyf(start, '%Y-%m-%d %H:%M')} → {nyf(end, '%Y-%m-%d %H:%M')}",
        f"- 窗口（UTC）：{iso(start)} → {iso(end)}",
        f"- 有活动的 issue：{len(acts)}（新建 {n_new}，关闭 {n_closed}）；评论：{n_comments}",
        "- 来源：脚本直接抓取 issue 评论与状态事件，未经 AI 处理；issue 正文不收录",
        "",
    ]
    out += render_groups(acts, pm)

    active = {i["number"] for i, _ in acts}
    idle = [i for i in issues if i["state"] == "open" and i["number"] not in active]
    out += ["## 本窗口无更新的 open issue", ""]
    out += [f"- #{i['number']} {i['title']}" for i in sorted(idle, key=lambda x: x["number"])] or ["- （无）"]
    out.append("")
    return "\n".join(out)


def cmd_log(a):
    now = ts(a.end) if a.end else dt.datetime.now(UTC)
    today = now.astimezone(NY).date()
    path = ROOT / "logs" / f"{today:%Y}" / f"{today:%Y-%m-%d}.md"
    if not guard(a, now, path):
        return 0
    st = load_state()
    if a.start:
        start = ts(a.start)
    elif st.get("last_log_date") == today.isoformat() and st.get("last_log_start"):
        start = ts(st["last_log_start"])          # re-run today: regenerate same window
    elif st.get("last_log_end"):
        start = ts(st["last_log_end"])            # rolling: continue from last log
    else:
        start = dt.datetime.combine(today, dt.time(0), NY)
    issues = all_issues()
    md = render_log(start, now, activity(start, now, issues), issues, parent_map(issues))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    if not (a.start or a.end):
        save_state({**st, "last_log_start": iso(start), "last_log_end": iso(now),
                    "last_log_date": today.isoformat()})
    summary(md)
    print(f"wrote {path}")
    return 0


# ---------------------------------------------------------------- week
def render_week(start, end, acts, issues, pm, charts_stamp=None):
    y, w, _ = end.astimezone(NY).isocalendar()
    n_comments = sum(1 for _, es in acts for e in es if e["kind"] == "comment")
    closed = [(i, e) for i, es in acts for e in es if e["text"].startswith("关闭")]
    opened = [(i, e) for i, es in acts for e in es if e["text"] == "新建"]
    out = [
        f"# 周报 {y}-W{w:02d}（{nyf(start, '%m-%d')} – {nyf(end, '%m-%d')}）",
        "",
        f"- 窗口（纽约）：{nyf(start, '%Y-%m-%d %H:%M')} → {nyf(end, '%Y-%m-%d %H:%M')}",
        f"- 有活动的 issue：{len(acts)}（新建 {len(opened)}，关闭 {len(closed)}）；评论：{n_comments}",
        "- 来源：脚本直接抓取 issue 评论与状态事件，未经 AI 处理；issue 正文不收录",
        "",
    ]
    if charts_stamp:
        out += ["## 图表", "",
                f"![每日活跃度](../../charts/daily-{charts_stamp}.png)", "",
                f"![每周精力分布](../../charts/effort-{charts_stamp}.png)", ""]

    # per-workstream table
    rows = {}
    for i, es in acts:
        k = group_key(i, pm)
        r = rows.setdefault(k, {"issues": set(), "c": 0, "new": 0, "closed": 0})
        r["issues"].add(i["number"])
        r["c"] += sum(1 for e in es if e["kind"] == "comment")
        r["new"] += sum(1 for e in es if e["text"] == "新建")
        r["closed"] += sum(1 for e in es if e["text"].startswith("关闭"))
    out += ["## 各工作线概况", "", "| 工作线 | 评论 | 新建 | 关闭 | 有活动的 issue |", "|---|---:|---:|---:|---|"]
    for (pn, pt), r in sorted(rows.items(), key=lambda kv: -kv[1]["c"]):
        refs = " ".join(f"#{n}" for n in sorted(r["issues"]))
        out.append(f"| {pt} #{pn} | {r['c']} | {r['new']} | {r['closed']} | {refs} |")
    if not rows:
        out.append("| （无） | 0 | 0 | 0 | |")
    out.append("")

    out += ["## 本周关闭", ""]
    out += [f"- #{i['number']} {i['title']}（{nyf(e['t'], '%m-%d')}，{e['text']}）" for i, e in closed] or ["- （无）"]
    out += ["", "## 本周新建", ""]
    out += [f"- #{i['number']} {i['title']}（{nyf(e['t'], '%m-%d')}）" for i, e in opened] or ["- （无）"]
    out.append("")

    stale_cut = end - dt.timedelta(days=STALE_DAYS)
    stale = [i for i in issues if i["state"] == "open" and ts(i["updated_at"]) < stale_cut]
    out += [f"## 超过 {STALE_DAYS} 天无更新的 open issue", ""]
    out += [f"- #{i['number']} {i['title']}（最后更新 {nyf(ts(i['updated_at']), '%m-%d')}）"
            for i in sorted(stale, key=lambda x: x["updated_at"])] or ["- （无）"]
    out += ["", "## 本周明细", ""]
    out += render_groups(acts, pm, level=3) or ["- （无）", ""]
    return "\n".join(out)


def cmd_week(a):
    now = dt.datetime.now(UTC)
    local = now.astimezone(NY)
    y, w, _ = local.isocalendar()
    path = ROOT / "reports" / f"{y}" / f"{y}-W{w:02d}.md"
    if not a.force and local.weekday() != 4:
        print(f"skip: weekly report runs on Fridays (today {local:%a})")
        return 0
    if not guard(a, now, path):
        return 0
    st = load_state()
    key = f"{y}-W{w:02d}"
    if a.start:
        start = ts(a.start)
    elif st.get("last_week_key") == key and st.get("last_week_start"):
        start = ts(st["last_week_start"])         # re-run this week: same window
    elif st.get("last_week_end"):
        start = ts(st["last_week_end"])           # rolling: continue from last report
    else:
        monday = local.date() - dt.timedelta(days=local.weekday())
        start = dt.datetime.combine(monday, dt.time(0), NY)
    issues = all_issues()
    pm = parent_map(issues)
    md = render_week(start, now, activity(start, now, issues), issues, pm,
                     charts_stamp=local.date().isoformat() if a.charts else None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    if not a.start:
        save_state({**st, "last_week_start": iso(start), "last_week_end": iso(now), "last_week_key": key})
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"wrote=true\npath={path}\n")
    summary(md)
    print(f"wrote {path}")
    return 0


# ---------------------------------------------------------------- plan
PROJECT_QUERY = """
query($login:String!, $num:Int!, $after:String) {
  repositoryOwner(login:$login) {
    ... on ProjectV2Owner {
      projectV2(number:$num) {
        items(first:100, after:$after) {
          pageInfo { hasNextPage endCursor }
          nodes {
            status:   fieldValueByName(name:"Status")   { ... on ProjectV2ItemFieldSingleSelectValue { name } }
            priority: fieldValueByName(name:"Priority") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
            content { ... on Issue { number repository { nameWithOwner } } }
          }
        }
      }
    }
  }
}"""


def project_fields():
    """issue number -> (status, priority), or None if the project is not configured."""
    tok, num = os.environ.get("PROJECT_TOKEN"), os.environ.get("PROJECT_NUMBER")
    if not (tok and num):
        return None
    owner = os.environ.get("PROJECT_OWNER") or REPO.split("/")[0]
    out, after = {}, None
    while True:
        data, _ = _request(API + "/graphql", {"query": PROJECT_QUERY,
                           "variables": {"login": owner, "num": int(num), "after": after}}, token=tok)
        if data.get("errors"):
            raise RuntimeError(data["errors"])
        items = data["data"]["repositoryOwner"]["projectV2"]["items"]
        for node in items["nodes"]:
            c = node.get("content") or {}
            if (c.get("repository") or {}).get("nameWithOwner", "").lower() == REPO.lower():
                out[c["number"]] = ((node.get("status") or {}).get("name"),
                                    (node.get("priority") or {}).get("name"))
        if not items["pageInfo"]["hasNextPage"]:
            return out
        after = items["pageInfo"]["endCursor"]


def bucket(status):
    s = (status or "").strip().lower()
    for key, names in (("prog", ("in progress", "doing")), ("todo", ("todo", "to do")),
                       ("block", ("blocked",)), ("backlog", ("backlog",)), ("done", ("done",))):
        if s in names:
            return key
    return "other"


_COMMENTS = {}


def comments_of(n):
    if n not in _COMMENTS:
        _COMMENTS[n] = get(f"/repos/{REPO}/issues/{n}/comments", per_page=100)
    return _COMMENTS[n]


def last_comment(n):
    cs = comments_of(n)
    return cs[-1] if cs else None


def plan_buckets(issues, fields):
    """{'prog'|'todo'|'block'|'backlog'|'done'|'other'|'all': [open issue...]}"""
    open_issues = [i for i in issues if i["state"] == "open"]
    if fields is None:
        return {"all": open_issues}
    by = {}
    for i in open_issues:
        by.setdefault(bucket(fields.get(i["number"], (None, None))[0]), []).append(i)
    return by


def render_plan(now, by, pm, fields, overnight, since):
    out = [f"# 今日计划 {day_title(now)}", "",
           f"- 生成：纽约 {nyf(now, '%H:%M')}；状态来源："
           + ("Project「Status」字段" if fields is not None else "未配置 Project，按最近更新排序"), ""]

    def line(i):
        pri = (fields or {}).get(i["number"], (None, None))[1]
        head = f"- [ ] #{i['number']} {i['title']}" + (f"（{pri}）" if pri else "")
        c = last_comment(i["number"])
        if c:
            head += f"\n  - 上次记录 {nyf(ts(c['created_at']))}：{snippet(c.get('body'))} [→]({c['html_url']})"
        return head

    def section(title, items):
        out.extend([f"## {title}", ""])
        if not items:
            out.extend(["- （无）", ""])
            return
        groups = {}
        for i in items:
            groups.setdefault(group_key(i, pm), []).append(i)
        for (pn, pt), its in sorted(groups.items()):
            out.append(f"**{pt} #{pn}**")
            out.append("")
            out.extend(line(i) for i in sorted(its, key=lambda x: ts(x["updated_at"]), reverse=True))
            out.append("")

    stale_cut = now - dt.timedelta(days=STALE_DAYS)
    if fields is not None:
        section("进行中（In Progress）", by.get("prog", []))
        section("待办（Todo）", by.get("todo", []))
        section("阻塞（Blocked）", by.get("block", []))
        stale = [i for i in by.get("prog", []) + by.get("todo", []) if ts(i["updated_at"]) < stale_cut]
        backlog_n, other_n = len(by.get("backlog", [])), len(by.get("other", []))
    else:
        section("Open issue（按最近更新）", by.get("all", []))
        stale = [i for i in by.get("all", []) if ts(i["updated_at"]) < stale_cut]
        backlog_n = other_n = 0

    out += [f"## 上次日志之后的新动态（纽约 {nyf(since, '%m-%d %H:%M')} 起）", ""]
    if overnight:
        for i, es in overnight:
            for e in es:
                what = snippet(e["text"], 100) if e["kind"] == "comment" else f"状态：{e['text']}"
                out.append(f"- #{i['number']} {nyf(e['t'])} · {what} [→]({e['url']})")
    else:
        out.append("- （无）")
    out.append("")

    out += [f"## 超过 {STALE_DAYS} 天无更新（进行中 / 待办）", ""]
    out += [f"- #{i['number']} {i['title']}（最后更新 {nyf(ts(i['updated_at']), '%m-%d')}）" for i in stale] or ["- （无）"]
    out.append("")
    if backlog_n or other_n:
        out += ["## 备注", "", f"- Backlog {backlog_n} 项、未设状态 {other_n} 项未列出", ""]
    return "\n".join(out)


def cmd_plan(a):
    now = dt.datetime.now(UTC)
    today = now.astimezone(NY).date()
    path = ROOT / "plans" / f"{today:%Y}" / f"{today:%Y-%m-%d}.md"
    if not guard(a, now, path):
        return 0
    st = load_state()
    since = ts(st["last_log_end"]) if st.get("last_log_end") else now - dt.timedelta(hours=14)
    issues = all_issues()
    try:
        fields = project_fields()
    except Exception as e:  # keep producing a plan even if the project query fails
        print(f"warn: project query failed, falling back: {e}", file=sys.stderr)
        fields = None
    pm = parent_map(issues)
    by = plan_buckets(issues, fields)
    overnight = activity(since, now, issues)
    md = render_plan(now, by, pm, fields, overnight, since)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    summary(md)
    print(f"wrote {path}")
    return 0


# ---------------------------------------------------------------- main
def guard(a, now, path):
    """Actions fires at two UTC hours to cover EDT/EST; run only the right one."""
    if a.force:
        return True
    local = now.astimezone(NY)
    if local.weekday() >= 5:
        print(f"skip: weekend ({local:%a})")
        return False
    if local.hour < a.at_hour:
        print(f"skip: {local:%H:%M} NY is before {a.at_hour}:00")
        return False
    if path.exists():
        print(f"skip: {path} already exists")
        return False
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("log")
    lg.add_argument("--at-hour", type=int, default=18)
    lg.add_argument("--start", help="override window start (ISO, e.g. 2026-09-29T04:00:00Z)")
    lg.add_argument("--end", help="override window end (ISO)")
    lg.add_argument("--force", action="store_true")
    pl = sub.add_parser("plan")
    pl.add_argument("--at-hour", type=int, default=8)
    pl.add_argument("--force", action="store_true")
    wk = sub.add_parser("week")
    wk.add_argument("--at-hour", type=int, default=18)
    wk.add_argument("--start", help="override window start (ISO)")
    wk.add_argument("--charts", action="store_true", help="embed charts/daily|effort-<date>.png")
    wk.add_argument("--force", action="store_true")
    a = p.parse_args(argv)
    if not TOKEN:
        print("warn: no GITHUB_TOKEN; unauthenticated rate limit is 60 req/h", file=sys.stderr)
    return {"log": cmd_log, "plan": cmd_plan, "week": cmd_week}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

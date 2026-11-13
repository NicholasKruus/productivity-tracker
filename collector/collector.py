#!/usr/bin/env python3
"""Collect productivity data that no Claude connector can reach, for the dashboard.

Plain code with no AI in it. Run it on your Mac every hour (see the launchd
template next to this file). It writes small CSV files to a folder that Google
Drive syncs; the dashboard reads them through the Google Drive connector.

Sources, each switched on in config.toml:

- dictation:   superwhisper's local database (words dictated per day, and how
               many of them went into AI apps).
- claude_code: Claude Code transcripts in ~/.claude/projects (prompts you wrote,
               words in them, sessions, hours Claude worked, most sessions at once).
- published:   public feeds of finished work: YouTube channels and any RSS or
               Atom feed (Substack, a blog, a papers list).
- commits:     git history of the repos on this Mac, counting your own commits.
- rescuetime:  RescueTime's API, hours per day on distracting sites and apps,
               and on social media.

From your own Mac data it writes counts only, never text or titles. Published
items are public, so their titles and links are kept.

Usage:
    python3 collector.py                      # uses config.toml next to this file
    python3 collector.py --config path.toml
    python3 collector.py --out /tmp/test      # write somewhere else, for testing
"""

import argparse
import collections
import csv
import datetime as dt
import email.utils
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")

# The Google Drive connector sometimes drops the last few dozen characters of a
# file. Each CSV ends with a row-count line and padding, so the dashboard can
# tell a cut read from a short file and fail loudly instead of losing a day.
END_PADDING = "." * 400

SUPERWHISPER_DB = os.path.join(HOME, "Library/Application Support/superwhisper/database/superwhisper.sqlite")
CLAUDE_PROJECTS = os.path.join(HOME, ".claude/projects")
GIT = "/usr/bin/git"
RESCUETIME_API = "https://www.rescuetime.com/anapi/data"

# Text in a prompt that you didn't type: pastes, system text, command output, code.
STRIP = [
    re.compile(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", re.S),
    re.compile(r"<system-reminder[^>]*>.*?</system-reminder>", re.S),
    re.compile(r"<command-(?:message|args|stdout|stderr)>.*?</command-[a-z]+>", re.S),
    re.compile(r"<local-command-[a-z]+>.*?</local-command-[a-z]+>", re.S),
    re.compile(r"\[Pasted text #\d+[^\]]*\]"),
    re.compile(r"\[Image[^\]]*\]"),
    re.compile(r"```.*?```", re.S),
]
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*")


# ---------- shared helpers ----------

class Config:
    def __init__(self, path):
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        self.raw = raw
        self.tz = ZoneInfo(raw.get("timezone", "UTC"))
        self.out = os.path.expanduser(raw["out_dir"])
        self.start = dt.date.fromisoformat(raw["start"])

    def section(self, name):
        sec = self.raw.get(name) or {}
        return sec if sec.get("enabled", False) else None


def write_csv(path, header, rows):
    # Written in place (no rename) so Google Drive keeps the same file id.
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
        written = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fh.write(f"# end rows={len(rows)} written={written}\n# {END_PADDING}\n")


def read_csv(path, key):
    """Rows of a file this script wrote, keyed by one column."""
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    return {r[key]: r for r in csv.DictReader(lines)}


def written_at(path):
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        for line in fh:
            m = re.match(r"# end rows=\d+ written=(\S+)", line)
            if m:
                return dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
    return None


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "productivity-tracker", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def days_between(start, end):
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


# ---------- dictation (superwhisper) ----------

def dictation_by_day(cfg, sec):
    """superwhisper stores datetime as UTC text and duration in milliseconds."""
    days = collections.defaultdict(collections.Counter)
    if not os.path.exists(SUPERWHISPER_DB):
        print("dictation: superwhisper database not found", file=sys.stderr)
        return days
    ai_apps, ignore = set(sec.get("ai_apps", [])), set(sec.get("ignore_apps", []))
    con = sqlite3.connect(f"file:{SUPERWHISPER_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select datetime, appName, wordCount, duration from recording_stat_lines "
            "where kind = 'dictation' and fromFile = 0").fetchall()
    finally:
        con.close()
    for when, app, n_words, duration_ms in rows:
        if app in ignore:
            continue
        t = dt.datetime.fromisoformat(when).replace(tzinfo=dt.timezone.utc).astimezone(cfg.tz)
        d = days[t.date()]
        d["dictations"] += 1
        d["words"] += n_words or 0
        d["seconds"] += (duration_ms or 0) / 1000
        if app in ai_apps:
            d["words_to_ai"] += n_words or 0
    return days


# ---------- Claude Code ----------

def human_text(entry):
    """The text of a prompt you wrote, or None for anything else."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    if (entry.get("origin") or {}).get("kind") != "human":
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if not parts:
            return None
        text = "\n".join(parts)
    else:
        return None
    return None if text.startswith("[Request interrupted") else text


def words(text):
    for rx in STRIP:
        text = rx.sub(" ", text)
    return len(WORD.findall(text))


def claude_sessions(cfg, idle_gap):
    """Yield (prompts, turns) per transcript: prompts are (time, words), turns (start, end)."""
    files = sorted(glob.glob(os.path.join(CLAUDE_PROJECTS, "**/*.jsonl"), recursive=True))
    # A resumed or forked session starts its new file with a copy of the earlier
    # conversation, so each entry counts once, in the first file it appears in.
    seen = set()
    for path in files:
        if f"{os.sep}subagents{os.sep}" in path:
            continue
        events = []
        with open(path, errors="ignore") as fh:
            for line in fh:
                if '"timestamp"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("timestamp")
                if not ts or entry.get("type") not in ("user", "assistant", "system"):
                    continue
                uid = entry.get("uuid")
                if uid:
                    if uid in seen:
                        continue
                    seen.add(uid)
                t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(cfg.tz)
                text = human_text(entry)
                events.append((t, text is not None, words(text) if text else 0))
        if not events:
            continue
        events.sort(key=lambda e: e[0])
        prompts = [(t, w) for t, is_prompt, w in events if is_prompt]
        turns, start, last = [], None, None
        for t, is_prompt, _ in events:
            if is_prompt:
                if start is not None and last > start:
                    turns.append((start, last))
                start = last = t
            elif start is not None:
                if t - last > idle_gap:  # Claude was waiting, e.g. on a permission prompt
                    if last > start:
                        turns.append((start, last))
                    start = None
                else:
                    last = t
        if start is not None and last > start:
            turns.append((start, last))
        yield prompts, turns


def claude_by_day(cfg, sec):
    idle_gap = dt.timedelta(minutes=sec.get("idle_gap_minutes", 15))
    days = collections.defaultdict(collections.Counter)
    spans = []
    for prompts, turns in claude_sessions(cfg, idle_gap):
        session_days = set()
        for t, w in prompts:
            days[t.date()]["prompts"] += 1
            days[t.date()]["prompt_words"] += w
            session_days.add(t.date())
        for day in session_days:
            days[day]["sessions"] += 1
        for s, e in turns:
            while s.date() < e.date():  # split at midnight
                midnight = dt.datetime.combine(s.date() + dt.timedelta(days=1), dt.time(), cfg.tz)
                days[s.date()]["agent_seconds"] += (midnight - s).total_seconds()
                spans.append((s, midnight))
                s = midnight
            days[s.date()]["agent_seconds"] += (e - s).total_seconds()
            spans.append((s, e))
    points = collections.defaultdict(list)
    for a, b in spans:
        points[a.date()] += [(a, 1), (b, -1)]
    for day, pts in points.items():
        cur = peak = 0
        for _, step in sorted(pts):
            cur += step
            peak = max(peak, cur)
        days[day]["peak_parallel"] = peak
    return days


DAILY_HEADER = ["date", "dictations", "dictated_words", "dictated_minutes", "dictated_words_to_ai",
                "claude_prompts", "claude_prompt_words", "claude_sessions", "claude_agent_hours",
                "claude_peak_parallel"]


def collect_daily(cfg, today, recount_claude):
    dsec, csec = cfg.section("dictation"), cfg.section("claude_code")
    if not dsec and not csec:
        return "daily: skipped (dictation and claude_code are off)"
    dictation = dictation_by_day(cfg, dsec) if dsec else collections.defaultdict(collections.Counter)
    claude = claude_by_day(cfg, csec) if csec else collections.defaultdict(collections.Counter)
    path = os.path.join(cfg.out, "daily.csv")
    stored = read_csv(path, "date")
    # Claude Code deletes transcripts after 30 days, so older days keep the
    # Claude counts first written for them. superwhisper keeps its history.
    frozen_before = today - dt.timedelta(days=(csec or {}).get("freeze_after_days", 20))
    rows = []
    for day in days_between(cfg.start, today):
        d, c = dictation[day], claude[day]
        row = [day.isoformat(), d["dictations"], d["words"], round(d["seconds"] / 60, 1), d["words_to_ai"],
               c["prompts"], c["prompt_words"], c["sessions"], round(c["agent_seconds"] / 3600, 2),
               c["peak_parallel"]]
        old = stored.get(day.isoformat())
        if day < frozen_before and old and list(old) == DAILY_HEADER and not recount_claude:
            row[5:] = [old[k] for k in DAILY_HEADER[5:]]
        rows.append(row)
    write_csv(path, DAILY_HEADER, rows)
    return f"daily: wrote {len(rows)} days"


# ---------- published work ----------

ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"


def feed_items(url, tz):
    """(link, date, title) for each entry of an RSS 2.0 or Atom feed."""
    root = ET.fromstring(fetch(url))
    for item in root.iter("item"):  # RSS
        when = email.utils.parsedate_to_datetime(item.findtext("pubDate")).astimezone(tz)
        yield item.findtext("link"), when.date().isoformat(), item.findtext("title")
    for entry in root.iter(f"{ATOM}entry"):  # Atom (YouTube, many blogs)
        vid = entry.findtext(f"{YT}videoId")
        link = f"https://www.youtube.com/watch?v={vid}" if vid else next(
            (l.get("href") for l in entry.findall(f"{ATOM}link") if l.get("rel", "alternate") == "alternate"), None)
        stamp = entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tz)
        yield link, when.date().isoformat(), entry.findtext(f"{ATOM}title")


def collect_published(cfg):
    sec = cfg.section("published")
    if not sec:
        return "published: skipped"
    path = os.path.join(cfg.out, "shipped.csv")
    header = ["date", "type", "title", "url"]
    rows = read_csv(path, "url")
    feeds = [{"url": f"https://www.youtube.com/feeds/videos.xml?channel_id={c}", "type": "video"}
             for c in sec.get("youtube_channels", [])] + list(sec.get("feeds", []))
    skip = set(sec.get("exclude_links", []))
    problems = []
    for feed in feeds:
        try:
            for link, when, title in feed_items(feed["url"], cfg.tz):
                if link and link not in skip:
                    rows[link] = {"date": when, "type": feed.get("type", "post"), "title": title, "url": link}
        except (urllib.error.URLError, OSError, ET.ParseError, ValueError, TypeError) as e:
            problems.append(f"{feed['url']} ({type(e).__name__}: {e})")
    ordered = sorted(rows.values(), key=lambda r: (r["date"], r["type"], r["title"]))
    write_csv(path, header, [[r[k] for k in header] for r in ordered])
    # Feeds list only recent items, so a row is kept once seen, even after it drops off.
    note = f"published: wrote {len(ordered)} items"
    return note + ("; NOT refreshed: " + "; ".join(problems) if problems else "")


# ---------- commits ----------

def find_repos(roots, depth, skip):
    found = []
    for root in roots:
        root = os.path.expanduser(root)
        for here, dirs, _ in os.walk(root):
            rel = os.path.relpath(here, root)
            level = 0 if rel == "." else rel.count(os.sep) + 1
            if ".git" in dirs and level > 0:
                found.append(here)
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip] if level < depth else []
    return sorted(found)


def collect_commits(cfg):
    sec = cfg.section("commits")
    if not sec:
        return "commits: skipped"
    emails = {e.lower() for e in sec.get("author_emails", [])}
    prefixes = tuple(p.lower() for p in sec.get("author_email_prefixes", []))
    path = os.path.join(cfg.out, "commits.csv")
    header = ["date", "repo", "commits"]
    stored = []
    if os.path.exists(path):
        with open(path, newline="") as fh:
            stored = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    repos = find_repos(sec.get("roots", ["~"]), sec.get("depth", 3), set(sec.get("skip_dirs", [])))
    counts, read_ok, problems = collections.Counter(), set(), []
    for repo in repos:
        name = os.path.relpath(repo, HOME)
        try:
            out = subprocess.run([GIT, "-C", repo, "log", "--all", f"--since={cfg.start.isoformat()}",
                                  "--format=%H %aI %ae"], capture_output=True, text=True, timeout=60,
                                 check=True).stdout
        except (subprocess.SubprocessError, OSError) as e:
            problems.append(f"{name} ({type(e).__name__})")
            continue
        read_ok.add(name)
        seen = set()
        for line in out.splitlines():
            sha, when, author = line.split(" ", 2)
            author = author.lower()
            if sha in seen or not (author in emails or author.startswith(prefixes)):
                continue
            seen.add(sha)
            day = dt.datetime.fromisoformat(when).astimezone(cfg.tz).date()
            if day >= cfg.start:
                counts[(day.isoformat(), name)] += 1
    # A repo that wasn't read this run (moved, deleted, failing) keeps its stored rows.
    rows = [[r["date"], r["repo"], r["commits"]] for r in stored if r["repo"] not in read_ok]
    rows += [[d, name, n] for (d, name), n in counts.items()]
    rows.sort()
    write_csv(path, header, rows)
    note = f"commits: wrote {len(rows)} day-repo rows from {len(read_ok)} repos"
    return note + ("; NOT read: " + ", ".join(problems) if problems else "")


# ---------- RescueTime ----------

def rescuetime_key(env_file, timeout):
    """Read RESCUETIME_API_KEY from a .env file, which may be a 1Password-mounted pipe."""
    try:
        out = subprocess.run(["/bin/cat", env_file], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "the .env read timed out (1Password locked and not approved?)"
    if out.returncode != 0:
        return None, f"{env_file} not found"
    if not out.stdout.strip():
        return None, ".env came back empty (1Password probably locked); the next run tries again"
    for line in out.stdout.splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "RESCUETIME_API_KEY" and value.strip().strip("'\""):
            return value.strip().strip("'\""), None
    return None, "RESCUETIME_API_KEY not in .env"


def collect_rescuetime(cfg, today, force):
    sec = cfg.section("rescuetime")
    if not sec:
        return "rescuetime: skipped"
    path = os.path.join(cfg.out, "rescuetime.csv")
    header = ["date", "distracting_hours", "social_hours"]
    stored = read_csv(path, "date")
    last = written_at(path)
    # Fetched once a day, so a locked 1Password asks at most once a day.
    if not force and stored and last and last.astimezone(cfg.tz).date() == today:
        return "rescuetime: already fetched today"
    env_file = os.path.join(HERE, sec.get("env_file", ".env"))
    key, problem = rescuetime_key(env_file, sec.get("env_read_timeout", 120))
    if problem:
        return f"rescuetime: NOT updated: {problem}"
    yesterday = today - dt.timedelta(days=1)
    # The free plan's API returns only about the last 14 days, so after the first
    # fetch only recent days are asked for and older days keep their stored hours.
    begin = today - dt.timedelta(days=sec.get("refetch_days", 10)) if stored else cfg.start
    query = urllib.parse.urlencode({"format": "json", "perspective": "interval", "resolution_time": "day",
                                    "restrict_kind": "activity", "restrict_begin": begin.isoformat(),
                                    "restrict_end": yesterday.isoformat()})
    try:
        data = json.loads(fetch(f"{RESCUETIME_API}?{query}", {"Authorization": f"Bearer {key}"}))
        rows = [dict(zip(data["row_headers"], r)) for r in data["rows"]]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        return f"rescuetime: NOT updated: API call failed ({type(e).__name__}: {e})"
    if not rows:
        # RescueTime logs all computer time, so an empty answer means a limit or outage.
        return f"rescuetime: NOT updated: no rows for {begin} to {yesterday}"
    social = set(sec.get("social_categories", []))
    distracting, social_s = collections.Counter(), collections.Counter()
    for r in rows:
        day = r["Date"][:10]
        if r["Productivity"] < 0:  # RescueTime's distracting (-1) and very distracting (-2)
            distracting[day] += r["Time Spent (seconds)"]
        if r["Category"] in social:
            social_s[day] += r["Time Spent (seconds)"]
    first = min(stored) if stored else min(r["Date"][:10] for r in rows)
    out = []
    for day in days_between(dt.date.fromisoformat(first), yesterday):
        iso, old = day.isoformat(), stored.get(day.isoformat())
        if day < begin and old:
            out.append([old[k] for k in header])
        else:
            out.append([iso, round(distracting[iso] / 3600, 2), round(social_s[iso] / 3600, 2)])
    write_csv(path, header, out)
    return f"rescuetime: wrote {len(out)} days"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.toml"))
    ap.add_argument("--out", help="write here instead of out_dir (for testing)")
    ap.add_argument("--recount-claude", action="store_true",
                    help="recount Claude columns for every day, ignoring stored counts")
    ap.add_argument("--rescuetime-now", action="store_true", help="fetch RescueTime even if fetched today")
    args = ap.parse_args()
    cfg = Config(args.config)
    if args.out:
        cfg.out = args.out
    os.makedirs(cfg.out, exist_ok=True)
    now = dt.datetime.now(cfg.tz)
    print(f"--- run {now:%Y-%m-%d %H:%M}")
    print(collect_daily(cfg, now.date(), args.recount_claude))
    print(collect_published(cfg))
    print(collect_commits(cfg))
    print(collect_rescuetime(cfg, now.date(), args.rescuetime_now))


if __name__ == "__main__":
    main()

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

From your own Mac data it writes counts, dates and repo folder names, never
text you wrote. Published items are public, so their titles and links are kept.

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

if sys.version_info < (3, 11):
    sys.exit("collector.py needs Python 3.11 or newer (macOS's own /usr/bin/python3 is 3.9). "
             "Install one with Homebrew: brew install python")

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
# A repo's own config can name programs for git to run (a signature checker, or a
# remote to fetch missing objects from). These settings stop that, so reading
# history never runs code from a repo or reaches the network.
GIT_ARGS = [GIT, "-c", "log.showSignature=false", "-c", "core.fsmonitor=false"]
GIT_ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"}
# Never searched for repos: macOS guards some of these (a background job reading
# them triggers a permission prompt), and the rest hold no repos of yours.
ALWAYS_SKIP = {"Library", "Desktop", "Documents", "Downloads", "Pictures", "Movies", "Music",
               "Applications", "node_modules"}
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


class StoredFileError(Exception):
    """A file this script wrote earlier looks cut or edited; rewriting it would lose history."""


def read_csv(path, key):
    """Rows of a file this script wrote, keyed by one column.

    The file must end with the end line write_csv adds, with the right row count.
    Otherwise it was cut (for example mid-sync) and is refused, so the caller
    doesn't overwrite stored history with a partial copy.
    """
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as fh:
        text = fh.read()
    m = re.search(r"^# end rows=(\d+) ", text, re.M)
    lines = [line for line in text.splitlines(keepends=True) if not line.startswith("#")]
    rows = list(csv.DictReader(lines))
    if not m or int(m.group(1)) != len(rows):
        raise StoredFileError(f"{os.path.basename(path)} looks cut or edited (end line missing or wrong "
                              "row count); not overwriting it. Restore it from Drive's version history.")
    return {r[key]: r for r in rows}


def written_at(path):
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        for line in fh:
            m = re.match(r"# end rows=\d+ written=(\S+)", line)
            if m:
                return dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would send an Authorization header on to any redirect target."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"refused redirect to {newurl}", headers, fp)


def fetch(url, headers=None, follow_redirects=True):
    req = urllib.request.Request(url, headers={"User-Agent": "productivity-tracker", **(headers or {})})
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirect)
    with opener.open(req, timeout=30) as resp:
        return resp.read()


def web_link(link):
    """The link if it is http(s), else None: a feed could carry javascript: or file: links."""
    link = (link or "").strip()
    return link if urllib.parse.urlsplit(link).scheme in ("http", "https") else None


def one_line(text):
    """Collapse whitespace, so a title can't break a CSV row or fake the end line."""
    return " ".join((text or "").split())


def days_between(start, end):
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


# ---------- dictation (superwhisper) ----------

def dictation_by_day(cfg, sec):
    """Per local day: dictations, words, seconds, words into AI apps. None if unreadable.

    superwhisper stores datetime as UTC text and duration in milliseconds.
    """
    if not os.path.exists(SUPERWHISPER_DB):
        return None
    ai_apps, ignore = set(sec.get("ai_apps", [])), set(sec.get("ignore_apps", []))
    try:
        con = sqlite3.connect(f"file:{SUPERWHISPER_DB}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "select datetime, appName, wordCount, duration from recording_stat_lines "
                "where kind = 'dictation' and fromFile = 0").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None  # schema changed or database locked: keep what is stored
    days = collections.defaultdict(collections.Counter)
    for when, app, n_words, duration_ms in rows:
        if app in ignore:
            continue
        try:
            t = dt.datetime.fromisoformat(when).replace(tzinfo=dt.timezone.utc).astimezone(cfg.tz)
        except (TypeError, ValueError):
            continue  # a row without a usable date is skipped, not fatal
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


def claude_sessions(idle_gap):
    """Yield (prompts, spans) per transcript, in UTC.

    prompts: (time, words) for each prompt you wrote. spans: (start, end) stretches
    when Claude was working: from a prompt to its last step, split wherever nothing
    happened for longer than idle_gap (Claude waiting on you), and picked up again
    when work resumes. Times stay in UTC so durations are right across DST changes.
    """
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
                    ts = entry.get("timestamp")
                    if not ts or entry.get("type") not in ("user", "assistant", "system"):
                        continue
                    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
                except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                    continue
                uid = entry.get("uuid")
                if uid:
                    if uid in seen:
                        continue
                    seen.add(uid)
                text = human_text(entry)
                events.append((t, text is not None, words(text) if text else 0))
        if not events:
            continue
        events.sort(key=lambda e: e[0])
        prompts = [(t, w) for t, is_prompt, w in events if is_prompt]
        spans, start, last = [], None, None
        for t, is_prompt, _ in events:
            if is_prompt:
                if start is not None and last > start:
                    spans.append((start, last))
                start = last = t
            elif start is not None:
                if t - last > idle_gap:  # Claude waited (a permission prompt, say); resume the clock here
                    if last > start:
                        spans.append((start, last))
                    start = t
                last = t
        if start is not None and last > start:
            spans.append((start, last))
        yield prompts, spans


def claude_by_day(cfg, sec):
    """Per local day: prompts, words, sessions, Claude's working seconds, most spans at once."""
    idle_gap = dt.timedelta(minutes=sec.get("idle_gap_minutes", 15))
    local = lambda t: t.astimezone(cfg.tz)
    days = collections.defaultdict(collections.Counter)
    pieces = []  # (local day, start UTC, end UTC)
    for prompts, spans in claude_sessions(idle_gap):
        session_days = set()
        for t, w in prompts:
            day = local(t).date()
            days[day]["prompts"] += 1
            days[day]["prompt_words"] += w
            session_days.add(day)
        for day in session_days:
            days[day]["sessions"] += 1
        for s, e in spans:
            while local(s).date() < local(e).date():  # split at local midnight
                midnight = dt.datetime.combine(local(s).date() + dt.timedelta(days=1), dt.time(), cfg.tz)
                midnight = midnight.astimezone(dt.timezone.utc)
                pieces.append((local(s).date(), s, midnight))
                s = midnight
            pieces.append((local(s).date(), s, e))
    points = collections.defaultdict(list)
    for day, a, b in pieces:
        days[day]["agent_seconds"] += (b - a).total_seconds()
        points[day] += [(a, 1), (b, -1)]
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
DICTATION_COLS, CLAUDE_COLS = DAILY_HEADER[1:5], DAILY_HEADER[5:]


def collect_daily(cfg, today, recount):
    """daily.csv. A source that is off is left blank; one that can't be read keeps what is stored."""
    dsec, csec = cfg.section("dictation"), cfg.section("claude_code")
    if not dsec and not csec:
        return "daily: skipped (dictation and claude_code are off)"
    path = os.path.join(cfg.out, "daily.csv")
    stored = read_csv(path, "date")
    notes = []
    dictation = dictation_by_day(cfg, dsec) if dsec else None
    if dsec and dictation is None:
        notes.append("superwhisper database not found or unreadable; kept stored dictation")
    claude = claude_by_day(cfg, csec) if csec else None
    # Claude Code deletes transcripts after 30 days by default, so older days keep the
    # Claude counts first written for them, unless asked to recount (--recount-claude
    # recounts the last 29 days; --recount-claude-all every day, losing what's gone).
    frozen_before = today - dt.timedelta(days=(csec or {}).get("freeze_after_days", 20))
    if recount == "recent":
        frozen_before = min(frozen_before, today - dt.timedelta(days=29))
    elif recount == "all":
        frozen_before = cfg.start
    rows = []
    for day in days_between(cfg.start, today):
        old = stored.get(day.isoformat())
        old = old if old and list(old) == DAILY_HEADER else None
        if dictation is not None:
            d = dictation[day]
            dcols = [d["dictations"], d["words"], round(d["seconds"] / 60, 1), d["words_to_ai"]]
        elif dsec and old:
            dcols = [old[k] for k in DICTATION_COLS]
        else:
            dcols = [""] * len(DICTATION_COLS)
        if claude is not None:
            c = claude[day]
            ccols = [c["prompts"], c["prompt_words"], c["sessions"], round(c["agent_seconds"] / 3600, 2),
                     c["peak_parallel"]]
            # Keep stored counts for old days, unless they were blank (source was off then).
            if day < frozen_before and old and old["claude_prompts"] != "":
                ccols = [old[k] for k in CLAUDE_COLS]
        else:
            ccols = [""] * len(CLAUDE_COLS)
        rows.append([day.isoformat()] + dcols + ccols)
    write_csv(path, DAILY_HEADER, rows)
    return f"daily: wrote {len(rows)} days" + ("; " + "; ".join(notes) if notes else "")


# ---------- published work ----------

ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"


def feed_items(url, tz):
    """(link, date, title) for each entry of an RSS 2.0 or Atom feed.

    An entry without a usable date or web link is skipped, not fatal.
    """
    root = ET.fromstring(fetch(url))
    for item in root.iter("item"):  # RSS
        try:
            when = email.utils.parsedate_to_datetime(item.findtext("pubDate"))
            if when.tzinfo is None:  # "-0000" means UTC with no stated zone
                when = when.replace(tzinfo=dt.timezone.utc)
            when = when.astimezone(tz)
        except (TypeError, ValueError, AttributeError):
            continue
        link = web_link(item.findtext("link"))
        if link:
            yield link, when.date().isoformat(), one_line(item.findtext("title"))
    for entry in root.iter(f"{ATOM}entry"):  # Atom (YouTube, many blogs)
        vid = entry.findtext(f"{YT}videoId")
        link = f"https://www.youtube.com/watch?v={vid}" if vid else next(
            (l.get("href") for l in entry.findall(f"{ATOM}link") if l.get("rel", "alternate") == "alternate"), None)
        stamp = entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")
        try:
            when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            when = when.astimezone(tz)
        except (TypeError, ValueError, AttributeError):
            continue
        link = web_link(link)
        if link:
            yield link, when.date().isoformat(), one_line(entry.findtext(f"{ATOM}title"))


FEED_TYPES = ("video", "post", "paper")


def collect_published(cfg):
    sec = cfg.section("published")
    if not sec:
        return "published: skipped"
    path = os.path.join(cfg.out, "shipped.csv")
    header = ["date", "type", "title", "url"]
    rows = read_csv(path, "url")
    feeds = [{"url": f"https://www.youtube.com/feeds/videos.xml?channel_id={c}", "type": "video"}
             for c in sec.get("youtube_channels", [])] + list(sec.get("feeds", []))
    for feed in feeds:
        if feed.get("type", "post") not in FEED_TYPES:
            raise ValueError(f"feed type must be one of {', '.join(FEED_TYPES)}: {feed}")
    skip = set(sec.get("exclude_links", []))
    problems = []
    for feed in feeds:
        try:
            for link, when, title in feed_items(feed["url"], cfg.tz):
                if link not in skip:
                    rows[link] = {"date": when, "type": feed.get("type", "post"), "title": title, "url": link}
        except (urllib.error.URLError, OSError, ET.ParseError, ValueError, TypeError) as e:
            problems.append(f"{feed['url']} ({type(e).__name__}: {e})")
    ordered = sorted(rows.values(), key=lambda r: (r["date"], r["type"], r["title"]))
    write_csv(path, header, [[r[k] for k in header] for r in ordered])
    # Feeds list only recent items, so a row is kept once seen, even after it drops off.
    note = f"published: wrote {len(ordered)} items"
    if problems:
        raise RuntimeError(note + "; NOT refreshed: " + "; ".join(problems))
    return note


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


def git(repo, *args):
    return subprocess.run(GIT_ARGS + ["-C", repo, "--no-pager"] + list(args), capture_output=True,
                          text=True, timeout=120, check=True, env=GIT_ENV).stdout


def collect_commits(cfg):
    sec = cfg.section("commits")
    if not sec:
        return "commits: skipped"
    emails = {e.lower() for e in sec.get("author_emails", [])}
    prefixes = tuple(p.lower() for p in sec.get("author_email_prefixes", []))
    path = os.path.join(cfg.out, "commits.csv")
    header = ["date", "repo", "repo_id", "commits"]
    stored = []
    if os.path.exists(path):
        read_csv(path, "date")  # refuses a cut file before anything is rewritten
        with open(path, newline="") as fh:
            stored = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    repos = find_repos(sec.get("roots", ["~"]), sec.get("depth", 3), ALWAYS_SKIP | set(sec.get("skip_dirs", [])))
    counts, read_ok, problems, names = collections.Counter(), set(), [], {}
    seen = set()  # commit hashes, across repos: a second clone doesn't count twice
    for repo in repos:
        name = os.path.relpath(repo, HOME)
        try:
            # A repo is identified by its first commit, so a renamed or moved repo keeps its history.
            roots = git(repo, "rev-list", "--max-parents=0", "HEAD").split()
            if not roots:
                continue
            repo_id = sorted(roots)[0][:12]
            # Every branch and tag, but not stashes (each stash is two commits of its own).
            # No --since: it filters by committer date and can stop early on skewed clocks.
            out = git(repo, "log", "--exclude=refs/stash", "--all", "--no-show-signature", "--format=%H %aI %ae")
        except subprocess.CalledProcessError:
            continue  # an empty repo, with no commits yet
        except (subprocess.SubprocessError, OSError) as e:
            problems.append(f"{name} ({type(e).__name__})")
            continue
        read_ok.add(repo_id)
        names[repo_id] = name
        for line in out.splitlines():
            try:
                sha, when, author = line.split(" ", 2)
                day = dt.datetime.fromisoformat(when).astimezone(cfg.tz).date()
            except ValueError:
                continue  # a malformed commit is skipped, not fatal
            author = author.lower()
            if sha in seen or day < cfg.start or not (author in emails or author.startswith(prefixes)):
                continue
            seen.add(sha)
            counts[(day.isoformat(), repo_id)] += 1
    # A repo that wasn't read this run (moved off this Mac, deleted, failing) keeps its stored rows.
    rows = [[r["date"], r["repo"], r["repo_id"], r["commits"]] for r in stored
            if r.get("repo_id") and r["repo_id"] not in read_ok]
    rows += [[d, names[rid], rid, n] for (d, rid), n in counts.items()]
    rows.sort()
    write_csv(path, header, rows)
    note = f"commits: wrote {len(rows)} day-repo rows from {len(read_ok)} repos"
    if problems:
        raise RuntimeError(note + "; NOT read: " + ", ".join(problems))
    return note


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


RESCUETIME_HISTORY_DAYS = 13  # the free plan's API returns about the last 14 days


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
        raise RuntimeError(f"NOT updated: {problem}")
    yesterday = today - dt.timedelta(days=1)
    # Ask again for recent days (late syncs), and for any gap since the last stored
    # day, but never further back than the API keeps.
    if stored:
        last_stored = dt.date.fromisoformat(max(stored))
        begin = min(today - dt.timedelta(days=sec.get("refetch_days", 10)), last_stored + dt.timedelta(days=1))
        begin = max(begin, today - dt.timedelta(days=RESCUETIME_HISTORY_DAYS))
    else:
        begin = cfg.start
    query = urllib.parse.urlencode({"format": "json", "perspective": "interval", "resolution_time": "day",
                                    "restrict_kind": "activity", "restrict_begin": begin.isoformat(),
                                    "restrict_end": yesterday.isoformat()})
    try:
        data = json.loads(fetch(f"{RESCUETIME_API}?{query}", {"Authorization": f"Bearer {key}"},
                                follow_redirects=False))
        rows = [dict(zip(data["row_headers"], r)) for r in data["rows"]]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        raise RuntimeError(f"NOT updated: API call failed ({type(e).__name__}: {e})")
    if not rows:
        # RescueTime logs all computer time, so an empty answer means a limit or outage.
        raise RuntimeError(f"NOT updated: no rows for {begin} to {yesterday}")
    social = set(sec.get("social_categories", []))
    distracting, social_s, answered = collections.Counter(), collections.Counter(), set()
    for r in rows:
        day = r["Date"][:10]
        answered.add(day)
        if r["Productivity"] < 0:  # RescueTime's distracting (-1) and very distracting (-2)
            distracting[day] += r["Time Spent (seconds)"]
        if r["Category"] in social:
            social_s[day] += r["Time Spent (seconds)"]
    first = min(stored) if stored else min(answered)
    out = []
    for day in days_between(dt.date.fromisoformat(first), yesterday):
        iso, old = day.isoformat(), stored.get(day.isoformat())
        if old and (day < begin or iso not in answered):
            out.append([old[k] for k in header])  # keep what was stored where the API says nothing
        elif day < begin:
            out.append([iso, "", ""])  # a gap the API no longer reaches: unknown, not zero
        else:
            out.append([iso, round(distracting[iso] / 3600, 2), round(social_s[iso] / 3600, 2)])
    write_csv(path, header, out)
    return f"rescuetime: wrote {len(out)} days"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.toml"))
    ap.add_argument("--out", help="write here instead of out_dir (for testing)")
    ap.add_argument("--recount-claude", action="store_const", const="recent", dest="recount",
                    help="recount the Claude columns for the last 29 days, ignoring stored counts")
    ap.add_argument("--recount-claude-all", action="store_const", const="all", dest="recount",
                    help="recount every day; days whose transcripts are deleted drop to zero")
    ap.add_argument("--rescuetime-now", action="store_true", help="fetch RescueTime even if fetched today")
    args = ap.parse_args()
    cfg = Config(args.config)
    if args.out:
        cfg.out = os.path.expanduser(args.out)
    if not os.path.isdir(os.path.dirname(os.path.abspath(cfg.out))):
        # Otherwise an unedited example path would quietly create a folder Drive never syncs.
        sys.exit(f"The output folder's parent doesn't exist: {os.path.dirname(cfg.out)}. "
                 "Set out_dir in config.toml to a folder inside your Google Drive.")
    os.makedirs(cfg.out, exist_ok=True)  # creates only the last folder
    now = dt.datetime.now(cfg.tz)
    print(f"--- run {now:%Y-%m-%d %H:%M}")
    steps = [("daily", lambda: collect_daily(cfg, now.date(), args.recount)),
             ("published", lambda: collect_published(cfg)),
             ("commits", lambda: collect_commits(cfg)),
             ("rescuetime", lambda: collect_rescuetime(cfg, now.date(), args.rescuetime_now))]
    failed = False
    for name, step in steps:
        try:
            print(step())
        except Exception as e:  # logged loudly; the other sources still run
            failed = True
            print(f"{name}: FAILED: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

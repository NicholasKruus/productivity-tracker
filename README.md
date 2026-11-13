# Productivity tracker

A weekly dashboard of what you actually finished, built with Claude: pieces you
published, code you committed, conversations in your field, applications you
sent, emails and Slack messages you wrote, time lost to distracting sites, and
how much work Claude does for each prompt you give it.

**Demo with made-up numbers:** https://productivity-tracker-demo.vercel.app

It counts outcomes rather than effort, and it collects everything itself. Trackers
you have to fill in by hand tend to lapse; this one keeps going without you.

## What it shows

| Chart | Source |
|---|---|
| Pieces published per week (videos, posts, papers) | Public RSS/Atom feeds, YouTube channel feeds |
| Commits per week | git history of the repos on your Mac |
| Conversations and applications per week | A daily Claude routine reading your meeting notes, calendar and Gmail |
| Emails and Slack messages you sent | Gmail and Slack, read live by the dashboard |
| Hours on distracting sites, and on social media | RescueTime |
| Hours Claude worked for you, and Claude's minutes per prompt | Claude Code transcripts on your Mac |
| Words you dictated vs typed to Claude | superwhisper and Claude Code |

Every part is optional. Leave a source out and its chart says so; the rest of
the page works.

## How it fits together

```
 your Mac (no AI)                          claude.ai
 ┌──────────────────────────┐             ┌───────────────────────────────┐
 │ collector/collector.py   │  CSV files  │ Dashboard (Data artifact)     │
 │ hourly via launchd       ├────────────►│  reads the CSVs via the       │
 │ superwhisper, Claude     │ Google Drive│  Google Drive connector, the  │
 │ Code, feeds, git,        │   folder    │  log sheet via Google Sheets, │
 │ RescueTime               │             │  Gmail and Slack live         │
 └──────────────────────────┘             └───────────────▲───────────────┘
                                                          │ log sheet
                                          ┌───────────────┴───────────────┐
                                          │ Daily routine (cloud agent)   │
                                          │  meeting notes, calendar,     │
                                          │  Gmail → one row per          │
                                          │  conversation or application  │
                                          └───────────────────────────────┘
```

- **The collector** reads what no connector can reach: local databases, local
  transcripts, local git repos. It is plain Python with no AI and no network
  access except the public feeds and RescueTime's API. It writes counts, never
  your text.
- **The routine** handles the parts that need judgement. It can read, and its
  only write tool appends rows to one sheet.
- **The dashboard** reads everything live, with your own access, each time you
  open it.

## Setup

You need macOS, Python 3.11 or newer, Google Drive for desktop, and a Claude plan
with connectors and routines. superwhisper, RescueTime and a meeting-notes app
such as Granola are optional.

1. **Collector.** Copy `collector/config.example.toml` to `collector/config.toml`,
   set `out_dir` to a folder inside your Google Drive, and switch on the sources
   you use. Run it once:

   ```
   python3 collector/collector.py
   ```

   It prints one line per source. Check the CSV files appeared in Drive.
2. **Run it hourly.** Edit `collector/com.example.productivity-collector.plist`
   (your user name and Python path), then:

   ```
   cp collector/com.example.productivity-collector.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.productivity-collector.plist
   ```

   The log is `~/Library/Logs/productivity-collector.log`. If a source needs
   files in Desktop, Documents or Downloads, macOS may ask you to allow Python.
3. **RescueTime (optional).** Create an API key at
   https://www.rescuetime.com/anapi/manage and put `RESCUETIME_API_KEY=...` in
   `collector/.env`. Better: keep it in a secrets manager that mounts the file
   for you (a 1Password Environment, for example), so the key never sits on
   disk. `.env` is git-ignored either way.
4. **Routine (optional).** Follow `routine/conversations-and-applications.md`.
5. **Dashboard.** Follow `dashboard/datasets.md`.

## Privacy and safety

- The collector writes counts, dates and repo names. Published items keep their
  public titles and links. No prompt text, dictation, email or message text is
  written anywhere.
- The routine sees your meeting notes, calendar and email, because judging them
  is its job. It writes only the date, kind, organization and names to the log,
  and it can't send, post, browse or run commands. List any notes folders it
  must never open.
- The dashboard is private to you unless you share it. Its live sources run with
  each viewer's own access, so someone you share it with sees their own Gmail
  and Slack numbers, not yours.

## Limits

- Claude Code deletes transcripts after 30 days, so the collector keeps each
  day's Claude counts once they are 20 days old. History before you install it
  is only as complete as the transcripts left.
- RescueTime's free plan returns about 14 days through the API, so its history
  builds up from when you start.
- Feeds list only recent items; an item is kept once seen.
- The routine's judgements can be wrong. The log sheet lists each row with who
  it was, so you can delete or fix rows by hand.
- Claude's minutes per prompt rises when you hand over bigger tasks, and also
  when Claude is stuck. Read it next to what you shipped.

## The demo

`demo/` is the same dashboard page running on made-up data, generated in the
browser so it always ends today. `demo/shim.js` stands in for the Data artifact
runtime. Rebuild it after changing the page with `python3 demo/build.py`.

## License

MIT. See `LICENSE`.

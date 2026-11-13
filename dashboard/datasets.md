# Dashboard sources

The dashboard is a Claude "Data" artifact: a page (`index.html`) plus one dataset
per source. Each dataset is a live connector call that runs, with your own
access, whenever you open the page. Replace the `<…>` values with your own.

| Dataset id | Connector | Tool | Arguments |
|---|---|---|---|
| `daily` | Google Drive | `download_file_content` | `{"fileId": "<id of daily.csv>"}` |
| `shipped` | Google Drive | `download_file_content` | `{"fileId": "<id of shipped.csv>"}` |
| `commits` | Google Drive | `download_file_content` | `{"fileId": "<id of commits.csv>"}` |
| `rescuetime` | Google Drive | `download_file_content` | `{"fileId": "<id of rescuetime.csv>"}` |
| `log` | Google Sheets | `get_values` | `{"spreadsheetId": "<log sheet id>", "range": "Log!A:C"}` |
| `sent_mail` | Gmail | `search_threads` | `{"query": "in:sent newer_than:84d", "pageSize": 50, "view": "THREAD_VIEW_METADATA_ONLY"}` |
| `slack_sent` | Slack | `slack_search_public_and_private` | `{"filters": "from:<@<your Slack member id>>", "natural_language_query": "", "response_format": "detailed", "include_context": false, "sort": "timestamp", "limit": 20, "max_context_length": 20}` |

Notes:

- The collector writes the CSV files in place, so their Drive ids never change.
  Find an id in the file's Drive URL, or ask Claude to search your Drive for it.
- `log` reads only the date, kind and label columns. The routine's `who` column
  stays out of the dashboard.
- `sent_mail` and `slack_sent` page through their results in the page's loader
  and keep only dates and counts. Message text never reaches the page's rows.
  The Slack loader stops once results are older than 12 weeks.
- Your Slack member id: in Slack, open your profile, then ⋮ (More) → Copy member
  ID. The Slack connector reaches one workspace.
- A source you leave out shows "Failed to load" in its chart; the rest of the
  page works.

## Making the dashboard

In Claude Code, from this repo's folder, ask: "Create a Data artifact from
dashboard/index.html with the datasets in dashboard/datasets.md", and give it
your file and sheet ids. It writes the page and datasets and checks the page
runs. The first time you open the dashboard, Claude asks you to allow each
connector the page uses.

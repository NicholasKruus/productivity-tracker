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
| `slack_sent` | Slack | `slack_search_public_and_private` | `{"filters": "from:<@<your Slack user id>> after:<YYYY-MM-DD, about 12 weeks ago>", "natural_language_query": "", "response_format": "detailed", "include_context": false, "sort": "timestamp", "limit": 20, "max_context_length": 20}` |

Notes:

- The collector writes the CSV files in place, so their Drive ids never change.
  Find an id in the file's Drive URL, or ask Claude to search your Drive for it.
- `log` reads only the date, kind and label columns. The routine's `who` column
  stays out of the dashboard.
- `sent_mail` and `slack_sent` page through their results in the page's loader
  and keep only dates and counts. Message text never reaches the page's rows.
- The Slack connector reaches one workspace.
- Any source you don't use can be left out: its chart shows "Failed to load" or
  an empty state, and the rest of the page works.

## Making the dashboard

In Claude, ask for a new Data artifact, give it `index.html` as the page and the
datasets above, and let it check the page runs. The first time you open it,
Claude asks you to allow each connector the page uses.

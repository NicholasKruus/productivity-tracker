#!/usr/bin/env python3
"""PreToolUse hook: let Google Sheets tools touch only the sheets listed below.

A routine that reads other people's email can be steered by a planted message.
Sheets tools accept any spreadsheet the account can edit, so this hook, not the
prompt, decides which sheets a run may use. It fails closed: anything it can't
read is blocked (exit 2; stderr is shown to Claude as the reason).
"""
import json
import sys

ALLOWED = {
    "YOUR_LOG_SHEET_ID",  # the log sheet from the routine guide
}


def block(reason):
    print(f"sheet guard: {reason}", file=sys.stderr)
    sys.exit(2)


try:
    event = json.load(sys.stdin)
    args = event.get("tool_input") or {}
    sheet = args.get("spreadsheetId") or args.get("spreadsheet_id")
except Exception as e:  # malformed input: block rather than guess
    block(f"couldn't read the tool call ({type(e).__name__}); blocked.")

if sheet in ALLOWED:
    sys.exit(0)
block(f"blocked {event.get('tool_name')} on spreadsheet {sheet!r}. This routine may only use its own log sheet.")

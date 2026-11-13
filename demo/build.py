#!/usr/bin/env python3
"""Build demo/index.html from dashboard/index.html, with made-up data.

The dashboard page is written for Claude's Data artifact type. Here it runs on
shim.js, a small stand-in for that runtime, and demo-data.js.
Run: python3 demo/build.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
page = open(os.path.join(HERE, "..", "dashboard", "index.html")).read()
page = page.replace('<meta name="dash-one-writer">\n', "")

html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Productivity tracker demo</title>
<meta name="description" content="A weekly dashboard of finished work, conversations, commits and focus, built with Claude. Demo with made-up numbers.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter+Tight:wght@800;900&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script src="demo-data.js"></script>
<script src="shim.js"></script>
<style>
  body {{ margin: 0; background: #fff; }}
  .demo-bar {{ display: flex; flex-wrap: wrap; gap: 6px 18px; justify-content: space-between; padding: 10px 28px; border-bottom: 1px solid rgba(11, 15, 23, 0.12); background: #e5f1ff; color: #0052a8; font: 500 10px/1.6 "IBM Plex Mono", ui-monospace, monospace; letter-spacing: 0.06em; text-transform: uppercase; }}
  .demo-bar a {{ color: #0052a8; }}
  @media (max-width: 520px) {{ .demo-bar {{ padding: 10px 16px; }} }}
</style>
</head>
<body>
<div class="demo-bar"><span>Demo with made-up numbers</span><a href="https://github.com/NicholasKruus/productivity-tracker">Code and setup on GitHub</a></div>
<div id="dash-root">
{page}
</div>
</body>
</html>
"""
open(os.path.join(HERE, "index.html"), "w").write(html)
print("wrote demo/index.html")

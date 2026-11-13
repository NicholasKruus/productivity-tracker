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
<script src="d3.v7.9.0.min.js"></script>
<script src="demo-data.js"></script>
<script src="shim.js"></script>
<style>
  /* Fonts and d3 are served from this site, so visitors make no third-party requests. */
  @font-face {{ font-family: "Inter"; font-weight: 100 900; font-display: swap; src: url(fonts/inter-latin.woff2) format("woff2"); }}
  @font-face {{ font-family: "Inter Tight"; font-weight: 100 900; font-display: swap; src: url(fonts/inter-tight-latin.woff2) format("woff2"); }}
  @font-face {{ font-family: "IBM Plex Mono"; font-weight: 400; font-display: swap; src: url(fonts/IBMPlexMono-Regular.ttf) format("truetype"); }}
  @font-face {{ font-family: "IBM Plex Mono"; font-weight: 500; font-display: swap; src: url(fonts/IBMPlexMono-Medium.ttf) format("truetype"); }}
  @font-face {{ font-family: "IBM Plex Mono"; font-weight: 600; font-display: swap; src: url(fonts/IBMPlexMono-SemiBold.ttf) format("truetype"); }}
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

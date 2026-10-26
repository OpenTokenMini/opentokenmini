# Demo

`index.html` is the "Early value" page: the user's last 30 days from local session logs, readable in a few seconds. Headline spend, daily chart by model, two facts picked from their data (priciest session and why, cache or delegation share), top models, projects and sessions; more findings and token, tool and agent breakdowns are folded below.

It reads `usage.json` from the same folder, made by `python3 02-measure/from-transcripts.py 30 > 00-docs/demo/usage.json`; that file is personal and not committed. Serve the folder with any static server, e.g. `python3 -m http.server 7843 -b 127.0.0.1 -d 00-docs/demo` (opening the file directly cannot fetch it). With no sessions in the window the page says so instead of drawing empty charts. Without it the page falls back to `sample.json`, a neutral sample (real shape, project names replaced) and says so.

Pending: screenshots.

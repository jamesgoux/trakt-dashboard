# Iris Project Rules

## Git Workflow
- Always commit and push changes to the `main` branch after completing work.
- The GitHub Actions workflow triggers on every push to `main`, rebuilding index.html automatically.
- Commit messages should be concise and descriptive of the change.
- Be aware of push race conditions: if a workflow is already running and you push again, the first run's "Commit and push" step may fail because the remote moved ahead. This is harmless — the next run will pick up all changes.

## Architecture
- `index.html` is auto-generated — never edit it directly (except via local rebuild).
- All dashboard UI changes go in `templates/dashboard.html`.
- All data pipeline changes go in `scripts/`.
- Data files live in `data/` as JSON — they are incrementally built and committed by GitHub Actions.

## Publish / Rebuild / Test Workflow

### Template-only changes (JS, CSS, HTML layout)
These don't need new API data. Use the fast local rebuild:
1. Edit `templates/dashboard.html`
2. Pull latest to get fresh data: `git pull`
3. Run local rebuild to inject current data into updated template:
   ```python
   import re
   from datetime import datetime, UTC
   with open('index.html', 'r', encoding='utf-8') as f:
       html = f.read()
   m = re.search(r'var D=(.+?);\nvar HS=', html, re.DOTALL)
   data_str = m.group(1)
   with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
       template = f.read()
   new_html = template.replace('__DASHBOARD_DATA__', data_str)
   new_html = new_html.replace('__BUILD_TIME__', datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC'))
   with open('index.html', 'w', encoding='utf-8') as f:
       f.write(new_html)
   ```
4. Commit and push — site updates in ~1 minute via GitHub Pages deploy.

### Python data pipeline changes (scripts/)
These change how data is structured or fetched. The workflow must run to regenerate data:
1. Edit the script(s) in `scripts/`
2. Commit and push
3. Wait for the "Refresh Trakt Data" workflow to complete (~5-10 min). It fetches from all APIs and rebuilds index.html with new data.
4. Monitor progress: check https://github.com/jamesgoux/trakt-dashboard/actions or poll via `git fetch` for new commits.

### Both template + pipeline changes
1. Make all edits to both `templates/dashboard.html` and `scripts/`
2. Do a local rebuild so the template changes are immediately visible
3. Commit and push everything
4. Template fixes are live immediately; data structure changes take effect after the workflow completes

### Checking workflow status
Use the GitHub API from the terminal:
```python
import urllib.request, json
url = 'https://api.github.com/repos/jamesgoux/trakt-dashboard/actions/runs?per_page=5'
req = urllib.request.Request(url, headers={'User-Agent': 'Iris/1.0'})
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
for r in data['workflow_runs']:
    print(r['id'], '|', r['status'], '|', r['conclusion'], '|', r['head_commit']['message'][:50])
```

## Iteration Plan
- Active bugs and feature priorities are tracked in `ITERATION_PLAN.md` at the repo root.
- Always reference the iteration plan when deciding what to work on next.

## Code Style
- Python scripts use minimal dependencies (just `requests`).
- Frontend is vanilla JS with ECharts 5 — no build step, no frameworks.
- Dashboard data is embedded as JSON inside the generated HTML.
- Keep the single-file approach — don't introduce build tools or bundlers.

# Deploying TREMOR (issue #15, ADR-0016)

One small always-on machine runs the dashboard and the scheduled jobs, with the SQLite database on a persistent volume. These steps use **Fly.io** (about $5–10/month). Railway works too with the same Dockerfile.

## What you need

- A Fly.io account with a card on file: <https://fly.io>
- `flyctl`: `brew install flyctl`, then `fly auth login`
- Your passcode for the site, and optionally an Anthropic API key

## 1. Create the app and its disk

```bash
cd ~/globe
fly launch --no-deploy --copy-config        # keep fly.toml; rename the app if "tremor" is taken
fly volumes create tremor_data --size 3 --region iad
```

## 2. Set secrets (never commit these)

```bash
fly secrets set TREMOR_PASSCODE='pick-something-long'
fly secrets set ANTHROPIC_API_KEY='sk-ant-...'      # optional; without it the jobs skip LLM steps
```

## 3. Deploy

```bash
fly deploy
fly open                                         # opens the passcode page
```

## 4. Give it data

The fastest way is to upload your local database, which already has prices, seed Events and the GDELT backfill:

```bash
fly ssh sftp shell
put data/tremor.sqlite /data/tremor.sqlite
```

Then restart: `fly machine restart`.

Or build it on the server (slow, several hours for the backfill):

```bash
fly ssh console -C "uv run --no-sync tremor prices"
fly ssh console -C "uv run --no-sync tremor seed"
fly ssh console -C "uv run --no-sync tremor gdelt backfill"
```

## What runs on its own

`tremor scheduler` (started by `deploy/start.sh`):

| When | Job |
|---|---|
| Every hour (at :05) | GDELT 2.0 pull → LLM refinement of the last 3 days (if a key is set) |
| Weekdays 22:00 UTC (after the US close) | prices → Recommendations for Episodes active in the last 30 days → back-test → score live Recommendations → backup |

Backups go to `/data/backups/` (the newest 7 are kept). Logs: `fly logs`.

## Checking it works ("Done when" for #15)

- the passcode-protected URL loads
- `fly logs` shows `gdelt pull: done` every hour and the daily jobs after 22:00 UTC, for 3 days

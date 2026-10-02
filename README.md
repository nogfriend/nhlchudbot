# goal-bot

An NHL goal bot that posts highlights when goals are scored.  
**This fork posts to Discord via an incoming webhook** (instead of Twitter / Bluesky).

## Required configuration

Create a Discord webhook in your server (Channel settings → Integrations → Webhooks → New Webhook), then set:

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/...."
```

Or put it in a `.env` file in the project root:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/....
```

## Run locally

```bash
pip install -r requirements.txt
python main.py
```

Dry-run (no Discord posts, only logs):

```bash
python main.py --dry-run
```

Process yesterday’s games once and exit:

```bash
python main.py --yesterday
```

## Docker

```bash
docker compose up --build
```

The container expects `DISCORD_WEBHOOK_URL` (via `.env` or environment).

## Tests / lint

```bash
make test
make coverage
make lint
make analyze
```

## Deploy without keeping your laptop on

See the deployment instructions below (GitHub + free always-on host, or GitHub Actions). The bot is a long-running process that must stay online during games, so a simple cron job is not enough.

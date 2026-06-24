# Deploy — Equity Research API

The repo had **no deploy configuration** (no Dockerfile, Procfile, or platform config). Cloud platforms cancel or fail deploys when they cannot detect how to build or start the app.

**Start command (all platforms):**

```bash
uvicorn api:app --host 0.0.0.0 --port $PORT
```

Set these environment variables in the platform dashboard:

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Optional | AI reports & briefs |
| `FINNHUB_API_KEY` | Optional | Analyst consensus |
| `FMP_API_KEY` | Optional | Fundamentals & peers |
| `FRED_API_KEY` | Optional | Macro data |
| `PORT` | Auto | Set by Render/Railway |

**Note:** SQLite (`portfolio.db`) is ephemeral on free tiers unless you attach persistent storage. Portfolio and alerts reset on redeploy unless you use a persistent disk or external DB.

---

## Render (recommended)

1. [render.com](https://render.com) → **New** → **Blueprint** (or Web Service)
2. Connect repo: `ryanappuhamy/equity-research-platform-ryanappuhamy`
3. Render reads `render.yaml` automatically for Blueprint deploy
4. Or manual Web Service:
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn api:app --host 0.0.0.0 --port $PORT`
   - **Health check path:** `/docs`
5. Add env vars in **Environment**
6. Deploy

---

## Railway

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
2. Select this repo — Railway detects `Procfile`
3. Add env vars under **Variables**
4. Deploy (Railway sets `PORT` automatically)

---

## Docker (any host)

```bash
docker build -t equity-research-api .
docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=... \
  -e FINNHUB_API_KEY=... \
  equity-research-api
```

API docs: `http://localhost:8000/docs`

---

## Verify locally before deploy

```bash
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

```bash
python -c "from api import app; print(app.title)"
```

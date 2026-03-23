# NBA Playoff Predictor 2026 — Deployment Guide

## Live URLs
- **Backend (Railway):** https://nba-playoff-predictor-production.up.railway.app
- **Frontend (Vercel):** https://https-github-com-agamital-nba-playo.vercel.app

## Deploy in ~15 minutes: Railway (backend) + Vercel (frontend)

---

## Step 1 — Deploy Backend to Railway

1. Go to https://railway.app and sign up (free, no credit card)
2. Click **New Project** → **Deploy from GitHub repo**
   - Or: **Deploy from local directory** and upload the `backend/` folder
3. Railway auto-detects Python via `requirements.txt` + `Procfile`
4. After deploy, go to **Settings → Networking → Generate Domain**
5. Copy your backend URL, e.g. `https://nba-playoff-backend-production.up.railway.app`

**Environment variables to set in Railway dashboard:**
| Variable | Value |
|---|---|
| `PORT` | Set automatically by Railway |
| `FRONTEND_URL` | Your Vercel URL (set after Step 3) |

---

## Step 2 — Update Frontend Config

Open `frontend/.env.production` and replace the placeholder URL:

```
VITE_API_URL=https://YOUR-RAILWAY-URL.railway.app
```

---

## Step 3 — Deploy Frontend to Vercel

### Option A — Vercel CLI (recommended)

```bash
npm install -g vercel
cd "C:\Users\TalAgami\Desktop\nba playoff\frontend"
npm run build          # verify build works locally first
vercel --prod
```

Follow the prompts:
- Project name: `nba-playoff-predictor` (or anything)
- Framework: Vite (auto-detected)
- Build command: `npm run build`
- Output directory: `dist`

### Option B — Vercel Web UI

1. Go to https://vercel.com → New Project
2. Import from GitHub, or drag-and-drop the `frontend/` folder
3. Set environment variable: `VITE_API_URL` = your Railway URL
4. Deploy

Your frontend URL: `https://nba-playoff-predictor.vercel.app`

---

## Step 4 — Final CORS wiring

Go back to Railway → your project → **Variables** → add:
```
FRONTEND_URL = https://nba-playoff-predictor.vercel.app
```
Then **Redeploy** the backend (or it auto-redeploys on variable change).

---

## Step 5 — Create QR Code

1. Go to https://qr.io or https://www.qr-code-generator.com
2. Paste your Vercel URL
3. Download the QR code PNG
4. Share with friends — they scan and play!

---

## Updating the App

**Frontend only** (most common):
```bash
cd frontend
vercel --prod
```

**Backend only:**
```bash
# If using GitHub: push to main branch, Railway auto-redeploys
# Otherwise: Railway dashboard → Redeploy
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| CORS errors in browser | Add your Vercel URL to `FRONTEND_URL` env var in Railway and redeploy |
| API calls fail | Check `VITE_API_URL` in `.env.production` matches Railway URL exactly |
| Railway app sleeps | Free tier sleeps after 30 min inactivity — first request takes ~10s to wake |
| Build fails on Vercel | Run `npm run build` locally first to catch errors |
| DB resets on Railway | Railway's filesystem is ephemeral — see "Persistent DB" below |

### Persistent Database on Railway

Railway's filesystem resets on redeploy. For production, either:
- **Option A**: Use Railway's Postgres addon (free tier available) — requires porting SQLite queries to Postgres
- **Option B**: Mount a Railway Volume (persistent disk) — set `DB_PATH` env var to `/data/nba_predictor.db`
- **Option C**: Keep SQLite and re-run `seed_standings.py` after each deploy via a startup script

For a hobby project with a small group of friends, Option C is simplest — add this to your startup:
```python
# In startup(), after init_db():
if not Path(DB_PATH).exists() or DB_PATH.stat().st_size < 1000:
    # Fresh DB — run seed data
    exec(open('seed_standings.py').read())
```

---

## Free Tier Limits

| Service | Limit | Notes |
|---|---|---|
| Railway | $5 credit/month | ~500 hrs runtime, enough for hobby use |
| Vercel | Unlimited deploys | 100 GB bandwidth/month |

---

## Going Live Checklist

- [ ] Backend deployed to Railway and URL copied
- [ ] `frontend/.env.production` updated with Railway URL
- [ ] Frontend deployed to Vercel
- [ ] `FRONTEND_URL` set in Railway env vars
- [ ] Backend redeployed after setting `FRONTEND_URL`
- [ ] Login/Signup works on live URL
- [ ] Standings load
- [ ] Bracket displays
- [ ] Predictions save
- [ ] Leaderboard works
- [ ] Tested on mobile (iOS Safari + Android Chrome)
- [ ] PWA install prompt appears on Android
- [ ] QR code created and shared

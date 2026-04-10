# GenPredict NG — Deployment Guide (GitHub → Render)

## Step 1: Initialize Git Repository

Open PowerShell in `c:\Users\USER\Desktop\Dr. AP\genpredict-ng\` and run:

```powershell
git init
git add .
git commit -m "Initial commit: GenPredict NG predictive maintenance system"
```

## Step 2: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `genpredict-ng`
3. Set to **Private** or Public (your choice)
4. **Do NOT** initialize with README (you already have files)
5. Click **Create repository**

Then push your code:
```powershell
git remote add origin https://github.com/YOUR_USERNAME/genpredict-ng.git
git branch -M main
git push -u origin main
```

## Step 3: Deploy to Render.com

1. Go to https://render.com and sign in
2. Click **New → Web Service**
3. Connect your GitHub account and select `genpredict-ng`
4. Fill in:
   - **Name**: `genpredict-ng`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
5. Under **Environment Variables**, add:
   - `SECRET_KEY` → click "Generate" to auto-create
   - `FLASK_ENV` → `production`
6. Scroll to **Add a Database** → Create a free PostgreSQL database
   - Name: `genpredict-db`
   - Render will auto-inject `DATABASE_URL` into your service

7. Click **Create Web Service**

## Step 4: Your Live URL

After deployment (takes ~3-5 minutes), your app will be live at:
```
https://genpredict-ng.onrender.com
```
(or similar Render URL)

## Auto-Deployment

Every time you push to GitHub, Render will automatically redeploy:
```powershell
git add .
git commit -m "Your change description"
git push
```

## Notes

- **Free tier**: Render free tier may sleep after 15 min of inactivity (first request takes ~30s)
- **Paid tier ($7/month)**: Always-on, no cold starts — recommended for 24/7 access
- **Database**: Free PostgreSQL is persistent — your data survives restarts

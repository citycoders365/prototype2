# 🚀 TravelloBus Deployment Guide

Welcome! Here is exactly how to get the TravelloBus prototype onto the internet so anyone can see it, and your backend connects directly to Supabase. This setup ensures you can effectively present your workflow to the judges.

## Step 1: Push to GitHub
1. Open GitHub and create a new repository called `travellobus-prototype`.
2. Upload this entire folder (the `TravelloBus Prototype` folder you are currently in) to that repository.
3. Make sure your `backend/` folder and HTML files are all there.

## Step 2: Deploy the Backend (Render.com)
1. Go to [Render.com](https://render.com) and create a free account if you don't have one.
2. Click **New +** and select **Web Service**.
3. Choose **Build and deploy from a Git repository**, and connect the GitHub repository you just created.
4. Use the following settings:
    * **Name**: `travellobus-backend` (or similar)
    * **Root Directory**: `backend` (This is very important!)
    * **Environment**: `Python 3`
    * **Build Command**: `pip install -r requirements.txt`
    * **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
    * **Plan**: Free
5. Scroll down to **Environment Variables** and add:
    * `SUPABASE_URL` = `https://aohtgcjyhocbzvxnmdwk.supabase.co`
    * `SUPABASE_KEY` = `sb_publishable_vBoZvNOIgcSfeYcp4PjnHQ_2pcnqNVG`
6. Click **Create Web Service**. Wait about 3-4 minutes for it to build and give you a green "Live" status.
7. Copy the URL Render gives you (e.g., `https://travellobus-backend.onrender.com`).

## Step 3: Connect Frontend to the New Backend
1. Open `citycoders.html` in Notepad or VS Code on your computer.
2. Find `const BACKEND_URL = "http://localhost:8000";` near line 2270 inside the `<script>` tag.
3. Change it to your new Render URL: `const BACKEND_URL = "https://travellobus-backend.onrender.com";`
4. Do the exact same thing in `ETM Sample.html` (around line 372).

## Step 4: Deploy the Frontend (Netlify Drop)
1. Go to [Netlify Drop](https://app.netlify.com/drop).
2. Simply drag and drop your `TravelloBus Prototype` folder straight onto the page.
3. It will instantly upload and give you a public URL for your passenger app!
4. You can rename the site in Netlify settings to something like `travellobus.netlify.app`.

---
**Done!** Now you can open the Netlify URL for the ETM on your phone (or presentation laptop), print a ticket, and immediately see it reflect on the passenger's Citycoders view on another device. Good luck with the judges!

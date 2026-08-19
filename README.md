Job Search — Daily Job Matcher

This project scrapes recent LinkedIn job posts, scores them against your resume using Google Gemini, and emails a daily digest with a top-5 table and an attached Excel file.

Quick setup

1. Create the local project (already scaffolded here):

```bash
cd ~/VSCodeProjects
ls -la job-search
```

2. Create a GitHub repository (recommended) and push:

- Create a repo via the GitHub website, or use the `gh` CLI:

```bash
cd ~/VSCodeProjects/job-search
git init
git add .
git commit -m "Initial job matcher scaffold"
gh repo create YOUR_USERNAME/job-search --private --source=. --remote=origin --push
```

3. Add repository secrets (Settings → Secrets and variables → Actions):
- `APIFY_TOKEN` — your Apify personal API token
- `GEMINI_API_KEY` — Google AI Studio API key
- `SENDER_EMAIL` — your Gmail address
- `EMAIL_APP_PASSWORD` — 16-character Gmail app password
- `RECEIVER_EMAIL` — where digests will be sent

4. Test the pipeline manually from GitHub Actions (Actions → Daily 7 AM Job Matcher → Run workflow).

Environment

Install dependencies locally for testing:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run locally (ensure env vars are set):

```bash
export APIFY_TOKEN=...
export GEMINI_API_KEY=...
export SENDER_EMAIL=you@gmail.com
export EMAIL_APP_PASSWORD=abcdefghijklmnop
export RECEIVER_EMAIL=you@gmail.com
python job_matcher.py
```

Notes

- Make sure `resume.txt` contains your plain-text resume.
- The GitHub Actions schedule triggers at 07:00 AM IST (01:30 UTC cron). Adjust cron if needed.
- Keep the repo private if you prefer; GitHub Actions minutes are available on personal accounts.

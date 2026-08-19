import os, smtplib, json
import pandas as pd
import argparse
import random
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from apify_client import ApifyClient
import google.generativeai as genai

# 1. Initialize APIs
apify = ApifyClient(os.getenv("APIFY_TOKEN"))
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true", help="Run locally without calling external APIs (for testing)")
args = parser.parse_args()

# 2. Scrape Jobs from LinkedIn (Last 24 Hours)
print("Scraping jobs via Apify for multiple titles and locations...")
# Titles to include (in this order): data engineer, java springboot backend, full stack, then a broad catch-all
titles = ["Data Engineer", "Java Spring Boot Backend", "Full Stack", ""]
# Preferred locations in this order: Hyderabad, Banglore, Pune
locations = ["Hyderabad", "Banglore", "Pune"]
rows_per_search = 20

# Collect jobs across title/location combinations, include remote searches, and deduplicate by URL
raw_jobs = []
seen_urls = set()
actor_id = "curious_coder/linkedin-post-search-scraper"

def fetch_and_accumulate(run_input, searched_title="", searched_location=""):
    try:
        run = apify.actor(actor_id).call(run_input=run_input)
        items = list(apify.dataset(run["defaultDatasetId"]).iterate_items())
        for it in items:
            # attach metadata about what title/location produced this item
            it["searched_title"] = searched_title
            it["searched_location"] = searched_location
            url = it.get("jobUrl") or it.get("link") or it.get("url")
            if not url:
                # fallback: create a pseudo-unique key from title/company
                url = f"{it.get('title','')}-{it.get('companyName','')}-{it.get('publishedAt','') }"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            raw_jobs.append(it)
    except Exception as e:
        print(f"Warning: scraper actor call failed for input {run_input}: {e}")

# Search by title and preferred locations in order
for title in titles:
    for loc in locations:
        run_input = {
            "title": title,
            "location": loc,
            "rows": rows_per_search,
            "publishedAt": "r86400",
        }
        fetch_and_accumulate(run_input, searched_title=title, searched_location=loc)

# Also include remote jobs for the same set of titles
for title in titles:
    run_input = {
        "title": title,
        "location": "Remote",
        "rows": rows_per_search,
        "publishedAt": "r86400",
    }
    fetch_and_accumulate(run_input, searched_title=title, searched_location="Remote")

# If still empty, fall back to a broader India-wide search once
if not raw_jobs:
    run_input = {"title": "", "location": "India", "rows": 50, "publishedAt": "r86400"}
    fetch_and_accumulate(run_input, searched_title="", searched_location="India")

# If dry-run, replace raw_jobs with sample data and skip external calls
if args.dry_run:
    print("Dry-run mode: using sample jobs and skipping external API calls.")
    raw_jobs = [
        {
            "title": "Senior Data Engineer",
            "companyName": "Acme Analytics",
            "description": "Work with Spark, AWS, and SQL. Remote friendly.",
            "jobUrl": "https://example.com/job/1",
            "searched_title": "Data Engineer",
            "searched_location": "Hyderabad",
        },
        {
            "title": "Java Spring Boot Backend",
            "companyName": "FinTech Co",
            "description": "Spring Boot microservices for payments. On-site in Pune.",
            "jobUrl": "https://example.com/job/2",
            "searched_title": "Java Spring Boot Backend",
            "searched_location": "Pune",
        },
        {
            "title": "Full Stack Engineer",
            "companyName": "StartupX",
            "description": "React + Java backend. Open to relocation to Banglore.",
            "jobUrl": "https://example.com/job/3",
            "searched_title": "Full Stack",
            "searched_location": "Banglore",
        },
        {
            "title": "Backend Engineer",
            "companyName": "RemoteWorks",
            "description": "Cloud services, remote work allowed.",
            "jobUrl": "https://example.com/job/4",
            "searched_title": "Backend Engineer",
            "searched_location": "Remote",
        },
    ]

# 3. Read Resume (support .tex resume)
resume_path = os.getenv("RESUME_PATH", "aditya_resume.tex")
with open(resume_path, "r", encoding="utf-8") as f:
    resume_content = f.read()

# 4. Filter & Match via Gemini AI
print("Scoring listings against resume...")
scored_jobs = []

for job in raw_jobs[:20]:
    title = job.get("title", "N/A")
    company = job.get("companyName", "N/A")
    description = job.get("description", "")[:1200]
    url = job.get("jobUrl", job.get("link", "N/A"))
    searched_role = job.get("searched_title", "")
    searched_location = job.get("searched_location", "")
    desc_lower = description.lower()
    remote_flag = (searched_location.lower() == "remote") or ("remote" in desc_lower) or ("work from home" in desc_lower)

    prompt = f"""
    You are a hiring manager. Compare the candidate's resume with the job description below.
    
    Candidate Resume:
    {resume_content}

    Job Title: {title}
    Company: {company}
    Job Description:
    {description}

    Output ONLY valid JSON with this exact schema:
    {{
        "score": <integer from 0 to 100>,
        "verdict": "<1-2 sentence explanation of match or missing skills>"
    }}
    """
    try:
        if args.dry_run:
            # deterministic mock scoring for dry-run
            score = max(50, min(95, 50 + (len(title) % 50)))
            # simple verdict based on keywords
            if "spark" in description.lower() or "sql" in description.lower():
                verdict = "Strong data and SQL experience matches this role."
            elif "spring" in description.lower() or "java" in description.lower():
                verdict = "Relevant Java/Spring backend experience."
            else:
                verdict = "Relevant full-stack and backend experience."
        else:
            res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            data = json.loads(res.text)
            score = int(data.get("score", 0))
            verdict = data.get("verdict", "")
    except Exception:
        score, verdict = 0, "Evaluation error"

    scored_jobs.append({
        "Job Title": title,
        "Company": company,
        "Match Score (%)": score,
        "Match Analysis": verdict,
        "Apply Link": url,
        "Searched Role": searched_role,
        "Searched Location": searched_location,
        "Remote": "Yes" if remote_flag else "No",
    })

# 5. Sort by Match Score & Save to Excel
if scored_jobs:
    df = pd.DataFrame(scored_jobs)
    df.sort_values(by="Match Score (%)", ascending=False, inplace=True)
    excel_path = "Top_Matched_Jobs.xlsx"
    df.to_excel(excel_path, index=False)
else:
    print("No jobs found by the scraper.")
    df = pd.DataFrame()

# 6. Format Clean Email Summary
top_5 = df.head(5) if not df.empty else pd.DataFrame()
html_rows = ""
for _, r in top_5.iterrows():
        html_rows += f"""
        <tr style=\"border-bottom:1px solid #e5e7eb;\">
            <td style=\"padding:8px; font-weight:600;\">{r['Job Title']}</td>
            <td style=\"padding:8px;\">{r['Company']}</td>
            <td style=\"padding:8px; color: {'green' if r['Match Score (%)']>=75 else '#d97706'}; font-weight:600;\">{r['Match Score (%)']}%</td>
            <td style=\"padding:8px;\">{r['Searched Role']}</td>
            <td style=\"padding:8px;\">{r['Searched Location']}{' (Remote)' if r.get('Remote','No')=='Yes' else ''}</td>
            <td style=\"padding:8px; font-size:13px;\">{r['Match Analysis']}</td>
            <td style=\"padding:8px;\"><a href=\"{r['Apply Link']}\" style=\"background:#0284c7;color:#fff;padding:6px 10px;text-decoration:none;border-radius:4px;\">Apply</a></td>
        </tr>
        """

html_content = f"""
<html>
  <body>
    <h2>🎯 Your Daily Job Matches (7:00 AM)</h2>
    <p>Top roles posted in the last 24 hours matched against your profile:</p>
    <table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">
            <tr style=\"background:#f3f4f6;\">
                <th style=\"padding:8px;\">Title</th>
                <th style=\"padding:8px;\">Company</th>
                <th style=\"padding:8px;\">Score</th>
                <th style=\"padding:8px;\">Searched Role</th>
                <th style=\"padding:8px;\">Location</th>
                <th style=\"padding:8px;\">Why Matched</th>
                <th style=\"padding:8px;\">Link</th>
            </tr>
      {html_rows}
    </table>
    <p>Full dataset with all 20 jobs attached in the Excel sheet.</p>
  </body>
</html>
"""

# 7. Dispatch Email
sender = os.getenv("SENDER_EMAIL")
receivers_env = os.getenv("RECEIVER_EMAIL", "")
receivers = [e.strip() for e in receivers_env.split(",") if e.strip()]
if sender and sender not in receivers:
    receivers.insert(0, sender)
if not receivers:
    raise ValueError("No recipient configured: set RECEIVER_EMAIL or SENDER_EMAIL environment variables")

msg = MIMEMultipart("alternative")
msg["From"] = f"Job Matcher Bot <{sender}>"
msg["To"] = ", ".join(receivers)
msg["Subject"] = f"🎯 Daily Job Digest: Top Roles for Today"
msg.attach(MIMEText(html_content, "html"))

if os.path.exists("Top_Matched_Jobs.xlsx"):
    with open("Top_Matched_Jobs.xlsx", "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename=Top_Matched_Jobs.xlsx")
        msg.attach(part)

if args.dry_run:
    print("--- DRY RUN OUTPUT ---")
    print("Top 5 matches (printed):")
    print(df.head(5).to_string(index=False))
    print("\nHTML preview:\n")
    print(html_content)
    print("Excel saved as Top_Matched_Jobs.xlsx")
else:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, os.getenv("EMAIL_APP_PASSWORD"))
        server.send_message(msg, from_addr=sender, to_addrs=receivers)
    print("Daily digest sent successfully!")

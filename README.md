# Job Finder

Job Finder sends a Telegram message within minutes of a new design job being posted, so you can apply before the applicant pile grows. It looks for UI/UX, product, visual, interaction and design-engineering roles in India, plus remote roles open to India. It skips roles that are too senior, too old, underpaid or already crowded.

It runs for free on GitHub Actions, around the clock. Your computer doesn't need to be on.

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Set it up](#set-it-up)
- [Change what it looks for](#change-what-it-looks-for)
- [Day-to-day use](#day-to-day-use)
- [Pause or stop it](#pause-or-stop-it)
- [Troubleshooting](#troubleshooting)
- [Known limits](#known-limits)
- [Files](#files)

---

## What you get

Each matching job arrives as its own Telegram message:

```
🟢 Posted within the hour

UI/UX Designer
Acme Technologies  ·  Indiranagar, Bengaluru

🕒  12 min ago  ·  5 applicants  ·  7 views  ·  2 openings
💼  1-3 Yrs  ·  ₹5–7 LPA (₹42k–58k/mo)
🏢  Direct employer  ·  4.1 (120 reviews) on AmbitionBox
✉️  careers@acme.in  (job post)

View on Naukri →   Recruiter  ·  Design manager
```

- **The coloured dot** shows how fresh and uncrowded the job is:
  - 🟢 posted in the last hour, under 25 applicants
  - 🟡 last 6 hours, under 50 applicants
  - ⚪ last 24 hours, under 100 applicants
- **Contact details** come from the job post or the company's website, when it can find them.
- **Recruiter** and **Design manager** open a LinkedIn people search at that company, so you can message someone directly.
- **Quiet check-ins.** When a check finds nothing new, you get a silent message (no sound) such as "No new matching roles · 10:40 PM", with how many roles each site returned. This tells you the bot is still running.

Each job is sent once. The bot remembers what it has sent for 21 days. If a role is posted in several cities, you get one message.

## How it works

Two checks run on GitHub Actions:

| Check | Sites | How often |
|---|---|---|
| **LinkedIn + Naukri** | LinkedIn (public job search, no login) and Naukri (opened in a real Chrome browser, because Naukri blocks simple scripts) | every 10 min |
| **Company sites** | Careers pages of about 65 companies (Greenhouse, Lever, Ashby, SmartRecruiters), plus Hirist, Cutshort, Wellfound, Foundit, Remotive and RemoteOK | every 15 min |

Each check:

1. Fetches recent jobs.
2. Drops anything that fails the filters (title, location, experience, salary, age, applicant count).
3. Sends new matches to Telegram.
4. Saves the jobs it has sent to a file in `state/` and commits that file back to the repo, so the next run doesn't repeat them.

GitHub sometimes starts scheduled runs a few minutes late, especially at busy times. "Every 10 minutes" usually means every 10–20 minutes.

You can also run the LinkedIn + Naukri check on a Mac. This is optional, either as a backup or instead of the cloud. See [Optional: run on a Mac](#optional-run-on-a-mac).

---

## Set it up

You need:

- A GitHub account
- A Telegram account
- About 15 minutes

### 1. Make your own copy of the repo

Fork this repository on GitHub, or create a new repository and push these files to it.

**Keep the repository public.** GitHub Actions is free and unlimited for public repositories. On a private repository the free allowance (2,000 minutes a month) runs out in about a week at these schedules. Being public means anyone can see your filters (`config.json`) and the list of jobs already sent (`state/`). Your Telegram token stays secret (step 3).

### 2. Create a Telegram bot

1. In Telegram, open **@BotFather**, send `/newbot` and follow the prompts. It gives you a **bot token** that looks like `123456789:AAH...`.
2. Open your new bot's chat, press **Start**, and send it any message, such as `hi`.
3. Find your **chat ID**. On your computer, inside this folder, run:

   ```
   python3 setup_telegram.py
   ```

   Paste the token when asked. The script finds your chat ID, saves both values to a local `.env` file, and sends you a test message.

   No terminal handy? Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser after sending `hi`. Your chat ID is the number after `"chat":{"id":`.

### 3. Give GitHub your Telegram details

In your repository on GitHub, go to **Settings → Secrets and variables → Actions → New repository secret** and add two secrets:

| Name | Value |
|---|---|
| `TG_BOT_TOKEN` | the bot token from BotFather |
| `TG_CHAT_ID` | your chat ID |

### 4. Turn on GitHub Actions

Open the **Actions** tab. On a fork, GitHub keeps workflows off until you click **I understand my workflows, go ahead and enable them**.

### 5. Start fresh

The `state/` folder holds the jobs the previous owner was already sent. Delete these files and commit, so your copy starts clean:

- `state/seen-cloud.json`
- `state/seen-feeds.json`
- `state/seen-mac.json`, if present

On its first run, each check sends a "Job Finder is live" message, then **every matching job from the last 24 hours**. That can be 20–60 messages at once. After that, you only get new posts.

### 6. Run it once to check

On the **Actions** tab, open **LinkedIn + Naukri check** and click **Run workflow**. Do the same for **Company sites check**. Each run takes 2–5 minutes, and your Telegram should start filling up. After that, both run on their own schedule.

---

## Change what it looks for

All filters live in **`config.json`**. Edit it on GitHub (pencil icon) or locally, then commit. The next run uses the new settings.

### Job titles: `titles`

| Key | What it does |
|---|---|
| `design` | A title must contain one of these words to count as a design role (e.g. `ui/ux`, `product designer`). |
| `design_engineering` | These titles also count (e.g. `ux engineer`, `design technologist`). In India "design engineer" often means mechanical or chip design, so if the title has only these words, the job description must also mention at least two words from `design_signals`. |
| `design_signals` | Words that prove a design-engineering job is about screens: `figma`, `prototype`, `css`, … |
| `exclude` | Any title containing one of these words is dropped: `lead`, `manager`, `intern`, `mechanical`, `trainer`, … Add `senior` and `sr` here to drop senior roles. |

Words match as whole words. `ux` matches "UX Designer" but not "Luxury".

### Limits: `filters`

| Key | Default | Meaning |
|---|---|---|
| `max_experience_min_years` | `5` | Drop jobs that ask for **more than** this many years as their *minimum*. A "3–6 years" job passes, a "6–10 years" job doesn't. Jobs that don't state experience pass. |
| `min_salary_lpa` | `5.4` | Drop jobs whose stated **top** salary is below this, in lakh per year. Jobs without a salary pass. |
| `max_age_hours` | `24` | Drop jobs posted longer ago than this. |
| `max_applicants` | `100` | Drop jobs that already have this many applicants or more. Jobs without a count pass. |

### Places: `locations`

- `allow`: a job passes if its location contains one of these (`india`, city names, `anywhere`, …).
- `remote_words` and `remote_blocked`: a remote job passes unless it's limited to a blocked region, such as `remote - US only`.

### Searches

| Key | Used by | Meaning |
|---|---|---|
| `search_keywords` | LinkedIn, Naukri | What to search for. More keywords means more results, but each run gets slower. |
| `linkedin_max_results_per_keyword` | LinkedIn | How many results to read per keyword (10 per page). |
| `linkedin_max_details_per_run` | LinkedIn | How many jobs per run get their full page opened, which gives the applicant count, salary and description. Newest first. Jobs beyond this limit are still sent, just without those details. |
| `naukri_pages_per_keyword` | Naukri | Result pages read per keyword. |
| `naukri_max_details_per_run` | Naukri | Same as the LinkedIn one, for Naukri. Each detail page takes about 5 seconds. |

Hirist, Cutshort and Wellfound use their own short query lists at the top of `src_boards.py`.

### Companies: `companies`

The bot reads the careers pages of companies that use one of four applicant-tracking systems. Each company is listed by its short name (slug) in that system:

| System | Find the slug in the company's job URL |
|---|---|
| `greenhouse` | `boards.greenhouse.io/`**`groww`** or `job-boards.greenhouse.io/`**`groww`** |
| `lever` | `jobs.lever.co/`**`cred`** |
| `ashby` | `jobs.ashbyhq.com/`**`notion`** |
| `smartrecruiters` | `jobs.smartrecruiters.com/`**`swiggy`** |

To check a slug before adding it, open `https://boards-api.greenhouse.io/v1/boards/<slug>/jobs` (or the Lever, Ashby or SmartRecruiters equivalent). If you see a list of jobs, the slug works.

### Mac only: `night`

These settings only affect the optional Mac check. Between `start_hour` and `end_hour` (Indian time), it checks only every `every_hours` hours. The cloud checks ignore this and run at full speed all night.

---

## Day-to-day use

| To… | Do this |
|---|---|
| See whether the checks are running | **Actions** tab on GitHub. Green ticks are good. Click a run to see its log, e.g. `LinkedIn + Naukri: 53 checked, 8 alerted, skipped {...}`. |
| Run a check right now | **Actions** → pick the check → **Run workflow** |
| See why jobs were skipped | The `skipped {...}` part of the log line counts the reasons: `too old`, `experience`, `salary`, `too many applicants`, `location`, `design-eng without UI signals` |
| Send a sample alert to test Telegram | Locally: `python3 run.py --test` (reads `.env`) |

The repo gets a small "Update seen jobs" commit after most runs. That's the bot saving its memory. It's expected, and it also keeps GitHub from switching off the schedule for inactivity.

## Pause or stop it

| To… | Do this |
|---|---|
| Mute alerts for a while | Mute the bot's chat in Telegram. Checks keep running. |
| Stop a cloud check | **Actions** → pick the check → **⋯** → **Disable workflow**. Or in a terminal: `gh workflow disable feeds.yml` (LinkedIn + Naukri) and `gh workflow disable company-sites.yml` (company sites). |
| Start it again | **Enable workflow** in the same place, or `gh workflow enable …` |
| Stop the Mac check | `./install_mac.sh --uninstall` |

---

## Optional: run on a Mac

The Mac runs only the LinkedIn + Naukri check, every 10 minutes while the Mac is awake, and every 2 hours at night. Use it as a backup if GitHub ever gets blocked by LinkedIn or Naukri, or instead of the cloud check. If both run, you'll get some duplicate alerts, because the Mac and the cloud keep separate lists of what they've sent.

Requirements: macOS, Python 3.10 or newer, and **Google Chrome** installed.

```
cd "path/to/Job Finder"
python3 -m venv .venv
.venv/bin/pip install playwright
python3 setup_telegram.py     # skip if .env already exists
.venv/bin/python run.py --test
./install_mac.sh
```

`install_mac.sh` schedules the check and keeps the Mac awake while it's plugged in (the screen can still turn off). The log is in `logs/mac.log`. While a check runs, Chrome opens a window off-screen for Naukri. That's normal.

The first time, macOS may ask whether Python can access the folder (for example Downloads). Allow it, or the check can't save its memory file.

---

## Troubleshooting

**No Telegram messages at all**
- Check the **Actions** tab: are the runs green?
- Open a run's log. `telegram not configured` means the `TG_BOT_TOKEN` / `TG_CHAT_ID` secrets are missing or misspelled. `telegram failed: 401` means the token is wrong. `400 chat not found` means the chat ID is wrong, or you never pressed **Start** in the bot's chat.

**Runs are red (failed)**
- If the failing step is **Save seen jobs**, the bot isn't allowed to commit. Go to **Settings → Actions → General → Workflow permissions** and choose **Read and write permissions**.
- Otherwise, read the error in the log. A single failed run is usually a site hiccup, and the next run catches up.

**Messages from one site have stopped**
- A log line like `linkedin search … HTTP Error 429`, `naukri search … Timeout` or `foundit … 403` means that site is limiting or blocking GitHub's servers. LinkedIn limits clear on their own. If Naukri keeps failing in the cloud, run the Mac check instead.

**Too many or too few alerts**
- Adjust `config.json` (see [Change what it looks for](#change-what-it-looks-for)). The `skipped {...}` counts in the log show which filter removes the most jobs.

**Duplicate alerts**
- Expected if both the Mac and the cloud are running. Stop one.

## Known limits

- **Sites can change or block without warning.** None of these sites offer an official API for this. The bot reads the same data their own web pages load. If a site changes its format, that site's results drop to zero until the code is updated. The other sites keep working.
- **Foundit blocks GitHub's servers** (HTTP 403), so it currently adds nothing in the cloud. Most Foundit results are copies of LinkedIn posts anyway.
- **Not covered:** Indeed and Glassdoor block automated access. Instahyre doesn't show posting dates, so new jobs can't be told apart from old ones.
- **Applicant counts are only for some jobs:** LinkedIn, Naukri, Hirist and Foundit show them. Company career pages don't. Jobs without a count still pass the filters.
- **Experience and salary are best guesses** when a site doesn't give them as data. The bot reads phrases like "2–4 years of experience" from the description. A job that states neither always passes.

---

## Files

| File | What it is |
|---|---|
| `config.json` | All filters, keywords and company lists |
| `run.py` | Entry point. `--feeds` (LinkedIn + Naukri, cloud), `--cloud` (company sites, cloud), `--mac` (LinkedIn + Naukri, Mac), `--test` (sample alert) |
| `core.py` | Shared logic: filters, the coloured tiers, duplicate checks, contact lookup, Telegram messages |
| `src_linkedin.py` | LinkedIn public job search |
| `src_naukri.py` | Naukri, through a Chrome browser |
| `src_ats.py` | Company careers pages (Greenhouse, Lever, Ashby, SmartRecruiters), Remotive, RemoteOK |
| `src_boards.py` | Hirist, Foundit, Cutshort, Wellfound |
| `setup_telegram.py` | One-time Telegram setup; writes `.env` |
| `install_mac.sh` | Turns the Mac schedule on or off |
| `.github/workflows/feeds.yml` | Cloud schedule for LinkedIn + Naukri |
| `.github/workflows/company-sites.yml` | Cloud schedule for company sites |
| `state/` | What each check has already sent (managed by the bot; delete a file to reset that check) |
| `prototypes/` | Early experiments; not used |
| `.env` | Your Telegram token and chat ID for local runs. Never committed. |

# JobBot 🤖

A personal, fully automated job application pipeline for Kerala tech job boards — **Infopark**, **Technopark**, **UL Cyberpark** (Kozhikode), and **SmartCity Kochi**. JobBot scrapes postings, filters and scores them against your profile, tailors a LaTeX resume using an LLM, compiles it via Tectonic, validates it through 6 quality gates, and sends personalized emails — all from the command line.

> **Scope:** Personal tool. Targets entry-level / fresher engineering roles in Kochi, Trivandrum, Kozhikode/Calicut, Remote, and Kerala. Built for and around one candidate's resume workspace — adapt the config and profile files for your own use.

---

## Features

- **Multi-source scraping** — Infopark (HTML table), Technopark (Laravel JSON API), UL Cyberpark (HTML vacancy directory), and SmartCity Kochi (news entries), 1 req/s, polite `User-Agent`
- **Hard filtering** — seniority keywords, excluded categories (sales, marketing, BPO, etc.), expired deadlines, location rejection, 2+ year experience requirements
- **Walk-in detection** — title regex *and* `is_walk_in` flag; walk-ins are exported to `.ics` calendar files and never emailed
- **Scoring (0–100)** — skill keyword density, title/seniority fit, location, recency, role family confidence, novel company bonus
- **Band assignment** — A ≥ 70 (auto-shortlist), B 55–69 (review queue), C < 55 (hidden)
- **LLM resume tailoring** — Gemini Flash edits only confirmed bullets/skills; the model is configurable with `GEMINI_MODEL` and all fabrication gates are enforced in prompt *and* validator
- **6-gate PDF validation** — single A4 page, correct size, zero ligatures, zero forbidden terms, fact-diff against pinned facts, clean build log
- **Personalized email drafting** — Jinja2 template, role-specific pitch, plain text + PDF attachment, BCC self
- **Idempotency** — `UNIQUE(source, source_job_id)` in DB; `applications.job_id UNIQUE` prevents duplicate sends
- **Company cooldown** — 30-day suppression per company after contact
- **IMAP reply/bounce tracking** — matches `In-Reply-To` / `References` against stored `Message-ID`
- **Walk-in `.ics` export** — calendar events for walk-in drives
- **Daily digest** — Markdown summary of pipeline state, Band A opportunities
- **Fully offline-capable ranking** — no LLM needed for scrape/rank/review
- **Model Context Protocol (MCP) Server** — expose JobBot tools, resources, and prompts over stdio to Claude Desktop, Cursor, Antigravity, and other MCP clients

---

## Requirements

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.13+ | |
| [uv](https://docs.astral.sh/uv/) | 0.12+ | replaces pip/venv/poetry |
| [Tectonic](https://tectonic-typesetting.github.io/) | 0.17.0 | bootstrapped via script |
| `pdfinfo` / `pdftotext` | any | usually from `poppler-utils` |
| Gmail account | — | with 2-Step Verification enabled |

---

## Quickstart

### 1. Clone and bootstrap

```bash
git clone https://github.com/<you>/jobbot.git ~/jobot
cd ~/jobot

# Install Tectonic to ~/.local/bin/tectonic
./scripts/bootstrap_tectonic.sh

# Install Python dependencies
uv sync
```

### 2. Configure your profile

```bash
cp config.yaml config.yaml   # already present — edit as needed
```

Edit [`config.yaml`](config.yaml) — update `candidate:` section with your name, email, phone, LinkedIn, GitHub, portfolio, and the path to your resume folder (`resume_root`).

```bash
# Copy your confirmed facts (resume source of truth) into profile/
cp /path/to/your/AGENTS.md profile/facts.md

# Review and update skill keyword lists
nano profile/skills.yaml

# Review the suppressed companies seeded from your resume folder
nano profile/suppressed.yaml
```

### 3. Set up Gmail App Password

> **Never use your actual Google account password.**

1. Enable 2-Step Verification at [myaccount.google.com/security](https://myaccount.google.com/security)
2. Generate an App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) → name it `JobBot`
3. Create `.env` in the project root:

```bash
cat > .env << 'EOF'
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=abcdefghijklmnop
EOF
chmod 600 .env
```

### 4. Add Gemini API key (for LLM tailoring)

```bash
echo 'GEMINI_API_KEY=your_key_here' >> .env
# Optional: override the Gemini model for your API project.
# Default: gemini-3.8-flash
# echo 'GEMINI_MODEL=gemini-3.8-flash' >> .env
```

Get a free key at [aistudio.google.com](https://aistudio.google.com). Without this, `tailor` falls back to copying the base resume unmodified.

### 5. Run your first scrape

```bash
uv run jobbot scrape     # scrapes both Infopark and Technopark
uv run jobbot rank       # filter + score all new jobs
uv run jobbot review --band A   # inspect Band A shortlist
```

---

## CLI Reference

```
jobbot scrape    [--source all|infopark|technopark|ulcyberpark|smartcity] [--max-pages N] [--full]
jobbot rank      [--min-score 55]
jobbot review    [--band A|B|C] [--limit N]
jobbot tailor    <id...> | --top 8
jobbot draft     <id...> | --approved
jobbot approve   <id...> | --all-band-A
jobbot send      [--limit 6] [--dry-run] [--force]
jobbot followup
jobbot status
jobbot report    [--week]
jobbot suppress  <company|email> --reason "..."
jobbot daily     # full pipeline: scrape → rank → tailor → draft → digest
jobbot mcp       # start JobBot as a Model Context Protocol (MCP) server
```

| Flag | Meaning |
|------|---------|
| `--dry-run` | Renders `.eml` files to `out/preview/`; no SMTP connection opened |
| `--force` | Sends outside the configured 10:00–17:00 IST window |
| `--full` | Re-fetches detail pages for already-seen jobs |
| `--all-band-A` | Operates on all jobs in Band A |

---

## Model Context Protocol (MCP) Server

JobBot includes a built-in MCP server compliant with standard MCP transports (stdio). This allows AI assistants like **Claude Desktop**, **Antigravity**, **Cursor**, or **Zed** to directly query your job pipeline, search postings, tailor resumes, and send applications.

### Connecting to Claude Desktop / Antigravity / Cursor

Add the following configuration to your client's `mcp_config.json` (or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "jobbot": {
      "command": "/path/to/jobot/.venv/bin/jobbot",
      "args": ["mcp"],
      "cwd": "/path/to/jobot"
    }
  }
}
```

Or using `uv`:

```json
{
  "mcpServers": {
    "jobbot": {
      "command": "uv",
      "args": ["--directory", "/path/to/jobot", "run", "jobbot", "mcp"]
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `get_pipeline_status` | Returns counts by state (shortlisted, tailored, sent, etc.) and band (A, B, C) |
| `list_jobs` | Lists active jobs filtered by band (`A`, `B`), state, or role family |
| `get_job_details` | Full JD text, contact emails, deadline, and score breakdown for a job ID |
| `search_jobs` | Full-text search across titles, companies, and JDs |
| `tailor_resume` | Runs Tectonic compile and 6-gate validation to produce a tailored PDF |
| `draft_application` | Renders personalized email draft and previews `.eml` |
| `approve_application` | Marks a job as approved for sending |
| `send_application` | Sends application via Gmail SMTP (`dry_run=True` for safe preview) |
| `suppress_company` | Adds a company to the suppression list |
| `get_candidate_facts` | Reads verified facts from `profile/facts.md` |

### MCP Resources & Prompts

- **Resources**: `jobbot://status`, `jobbot://jobs/band-a`, `jobbot://facts`
- **Prompts**: `review_and_tailor` (evaluates top Band A candidates and prompts tailoring actions)

---

## Pipeline State Machine

```
new → ranked → shortlisted → tailored → drafted → approved → sent → replied
                                                                   ↘ bounced
                        ↘ skipped   (hard-filtered)
                        ↘ manual    (tailor failed twice, or ATS-only)
```

---

## Scoring

| Component | Max | Rule |
|-----------|-----|------|
| Must-have skill hits | 45 | 3 pts each, capped at 45 |
| Title / seniority fit | 20 | Family keyword in title +10; fresher/junior/trainee/intern +10 |
| Location fit | 10 | Kochi / Trivandrum / Remote = 10; Kerala / unspecified = 6 |
| Recency | 10 | ≤3 days = 10; ≤7 = 7; ≤14 = 3; older = 0 |
| Role family confidence | 10 | Trigger keyword density in JD, capped at 10 |
| Novel company | 5 | Company not in DB or `resume_root` folders |

**Bands:** A ≥ 70 · B 55–69 · C < 55

---

## Role Families & Base Resumes

| Family | Trigger keywords | Base resume folder |
|--------|----------------|--------------------|
| `php_laravel` | php, laravel, eloquent, filament, blade | `MEDOWA_GLOBAL_LARAVEL_PHP_DEVELOPER` |
| `qa_testing` | qa, testing, playwright, postman, regression | `SCALGO_QA_Intern` → `AUGUSTA_HITECH_QA_ENGINEER` |
| `devops_cloud` | devops, docker, linux, aws, cloud | `LOGIOLOGY_JUNIOR_CLOUD_DEVOPS_ENGINEER` |
| `python_django` | python, django, flask, fastapi | `IVBM_JUNIOR_DEVELOPER_PYTHON_DJANGO` |
| `fullstack_js` | react, node, javascript, mern, typescript | `THALES_SOFTWARE_ENGINEER` |
| `ai_ml` | ml, ai, llm, rag, data science, nlp | `LATENTFORCE_RESEARCH_INTERN_AGENTIC_AI` |

> Base resumes are your existing tailored `.tex` files stored in `resume_root`. **Replace folder names** in `config.yaml` and `jobbot/tailor.py` with your own.

---

## Resume Validation Gates

All 6 must pass before an email is sent. Second failure moves the job to `manual`.

| Gate | Check |
|------|-------|
| **Pages** | `pdfinfo` → `Pages: 1` |
| **Size** | `pdfinfo` → `595 × 842 pts` (A4) |
| **Ligatures** | `pdftotext -layout` → no `ﬂ ﬁ ﬀ ﬃ` glyphs |
| **Forbidden terms** | Configurable list (e.g. Selenium, JIRA, Kubernetes) absent from PDF text |
| **Fact diff** | Every year and CGPA in the PDF exists verbatim in `profile/facts.md` |
| **Build log** | No `Overfull` / `Underfull` / `LaTeX Warning` in Tectonic output |

---

## Project Layout

```
~/jobot/
├── config.yaml                 # all runtime settings
├── .env                        # Gmail credentials (chmod 600, gitignored)
├── jobbot/
│   ├── cli.py                  # Typer entry-point
│   ├── db.py                   # SQLite schema + helpers
│   ├── models.py               # Pydantic v2 models
│   ├── normalize.py            # HTML→text, email extraction, company key, hashes
│   ├── rank.py                 # hard filters, scoring, band assignment
│   ├── tailor.py               # base selection, LLM edit, Tectonic compile, rename
│   ├── validate.py             # 6 PDF validation gates
│   ├── mailer.py               # SMTP + MIME, dry-run, IST window enforcement
│   ├── tracker.py              # IMAP reply/bounce match
│   ├── report.py               # digest + weekly stats
│   ├── sources/
│   │   ├── infopark.py         # HTML table scraper, 1 req/s
│   │   └── technopark.py       # JSON API, exponential backoff on 429/5xx
│   └── templates/
│       └── email.j2            # Jinja2 email body
├── profile/
│   ├── facts.md                # pinned candidate facts (source of truth for LLM)
│   ├── skills.yaml             # must/nice-to-have keywords per role family
│   ├── suppressed.yaml         # companies to never contact
│   └── tailor_prompt.md        # LLM system prompt for resume editing
├── scripts/
│   ├── bootstrap_tectonic.sh   # download Tectonic → ~/.local/bin/tectonic
│   ├── install_cron.sh         # install crontab entries
│   └── fetch_details.py        # one-shot: enrich jobs that have no JD yet
├── tests/
│   ├── fixtures/               # saved HTML/JSON from live sources
│   └── test_*.py               # 21 unit tests
└── out/
    ├── preview/                # dry-run .eml snapshots
    ├── ics/                    # walk-in .ics calendar exports
    ├── digests/                # daily digest .md files
    └── cron.log                # cron job output
```

---

## Scheduling (optional)

Install the crontab to run automatically every weekday:

```bash
./scripts/install_cron.sh
```

This sets up:

```cron
CRON_TZ=Asia/Kolkata
# Daily pipeline — 08:45 IST, Mon–Fri
45 8 * * 1-5  cd ~/jobot && flock -n .cron.lock .venv/bin/jobbot daily >> out/cron.log 2>&1

# Send approved applications — hourly 10:30–16:30 IST, Mon–Fri
30 10-16 * * 1-5  cd ~/jobot && flock -n .send.lock .venv/bin/jobbot send --limit 6 >> out/cron.log 2>&1

# Weekly report — Friday 18:00 IST
0 18 * * 5  cd ~/jobot && .venv/bin/jobbot report --week >> out/cron.log 2>&1
```

---

## Sending Limits

| Limit | Value | Where enforced |
|-------|-------|----------------|
| Daily cap | 12 emails | `config.yaml` |
| Per-run cap | 6 emails | `--limit` flag |
| Company cooldown | 30 days | `companies` table |
| Sending window | 10:00–17:00 IST, Mon–Fri | `mailer.py` (bypass with `--force`) |

---

## Configuration Reference (`config.yaml`)

```yaml
candidate:
  name: Your Name
  email: you@gmail.com
  phone: "+91 xxxxxxxxxx"
  linkedin: linkedin.com/in/yourhandle
  github: github.com/yourusername
  portfolio: https://yoursite.com
  facts: profile/facts.md           # LLM source of truth
  resume_root: /home/you/Resume     # where base + output folders live

sources:
  infopark:
    enabled: true
    max_pages: 30
    delay: 1.0                      # seconds between requests
  technopark:
    enabled: true
    per_page: 20
    delay: 1.0

ranking:
  shortlist_threshold: 70           # Band A
  review_threshold: 55              # Band B

tailoring:
  enabled: true
  max_per_day: 8
  model: opencode                   # falls back to gemini-2.5-flash
  tectonic: ~/.local/bin/tectonic
  forbidden_terms: [Selenium, Cypress, STLC, JIRA, Kubernetes, CI/CD, Terraform, TestRail]

sending:
  mode: approve                     # approve | auto | off
  daily_cap: 12
  per_run: 6
  window: "10:00-17:00"
  weekdays_only: true
```

---

## Running Tests

```bash
uv run pytest
```

```
21 passed in 0.50s
```

Tests cover: source parser contracts, company normalization, location classification, email ranking, subject-override extraction, walk-in hard filter, scoring golden set, PDF validation gates, scrape idempotency, and mailer dry-run MIME snapshot.

---

## Security Notes

- `.env` is `chmod 600` and gitignored — credentials never leave the machine
- LLM only receives JD text + `profile/facts.md` — mailbox contents stay local
- No scraping behind logins, no CAPTCHA interaction
- 1 req/s on both sources with identifying `User-Agent`

---

## Adapting for Your Own Use

1. **Replace `profile/facts.md`** with your own confirmed resume facts
2. **Update `profile/skills.yaml`** with the keywords relevant to your target roles
3. **Update `profile/suppressed.yaml`** with companies you have already applied to
4. **Replace base resume folder names** in `config.yaml` → `tailoring` and in `jobbot/tailor.py` → `ROLE_FAMILY_BASE_MAP` with your own `~/Resume/<COMPANY_ROLE>/` folders containing a compilable `resume.tex`
5. **Update `config.yaml`** → `candidate:` section with your details

---

## License

MIT — personal use, adapt freely.

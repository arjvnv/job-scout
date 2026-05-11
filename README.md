# job-scout

A command-line job search tool that searches LinkedIn, Indeed, Glassdoor, and more simultaneously — and optionally uses AI to score results against your resume, surface skills gaps, and let you search in plain English.

```bash
python3 main.py "product manager" --type internship
```

No API keys required to get started. AI features are optional and work with OpenAI, Anthropic, or Gemini.

---

## Features

- Search by partial or full role name (`"product"` matches product manager, product marketing, etc.)
- **Query expansion** — type abbreviations like `SWE`, `PM`, `DS`, `MLE` and the tool expands them automatically
- Filter by job type: `full-time`, `internship`, `contract`, `research`, or `any`
- **Filter by seniority** with `--level`: `junior`, `mid`, `senior`, `lead`, or `intern`
- **Filter by recency** with `--posted-within N`: only show jobs posted in the last N days
- Filter by location or `remote`
- Results from multiple sources fetched concurrently and deduplicated — including cross-source fuzzy deduplication so the same job on LinkedIn and Indeed only appears once
- Live progress spinner showing each source as it completes
- Numbered application links printed below every result table
- Open any result directly in your browser with `--open N`
- **Interactive result browser** with `--browse` — navigate with arrow keys, press Enter to open
- Optional CSV export
- **AI chat mode** — describe what you want in plain English, refine results conversationally
- **AI resume matching** — score listings against your resume, see a skills gap summary and resume tips
- One-time setup wizard on first run for optional API keys

---

## Sources

| Source | Method | Key Required | Covers |
|---|---|---|---|
| JobSpy | Scrape | No | LinkedIn, Indeed, Glassdoor, ZipRecruiter |
| Remotive | API | No | Remote tech roles |
| RemoteOK | API | No | Remote roles |
| We Work Remotely | Scrape | No | Remote roles |
| Adzuna | API | Yes (free, optional) | Broad aggregator |
| USAJobs | API | Yes (free, optional) | Government + research |

The first four sources work with zero configuration. Adzuna and USAJobs are optional extras — the first-run wizard will ask if you want to set them up.

---

## Requirements

- Python 3.10+
- pip

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/arjvnv/job-scout.git
cd job-scout
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run it

```bash
python3 main.py "software engineer"
```

On first run, a setup wizard will appear. You can skip all prompts — the tool works immediately without any keys. If you want AI features (chat mode, resume matching), the wizard will ask for an AI provider key.

---

## Usage

### Standard search

```
python3 main.py QUERY [OPTIONS]
```

| Flag | Short | Description | Default |
|---|---|---|---|
| `--type` | `-t` | `full-time`, `internship`, `contract`, `research`, `any` | `any` |
| `--level` | | `junior`, `mid`, `senior`, `lead`, `intern`, `any` | `any` |
| `--location` | `-l` | City, country, or `remote` | (none) |
| `--posted-within` | `-w` | Only show jobs posted within the last N days | (none) |
| `--limit` | `-n` | Max results per source (1–500) | `50` |
| `--open` | | Open result #N in your browser | (none) |
| `--browse` | | Launch interactive result browser after search | `false` |
| `--export` | `-e` | Save results to a CSV file | (none) |
| `--force` | `-f` | Overwrite existing export file | `false` |
| `--sources` | `-s` | Comma-separated list of sources to query | (all) |
| `--resume` | | Path to resume (PDF or .txt) — scores results with AI | (none) |
| `--chat` | | Launch the interactive AI chat REPL | `false` |

### Examples

```bash
# All open product manager roles
python3 main.py "product manager"

# Abbreviations expand automatically — "SWE" becomes "software engineer"
python3 main.py "SWE" --type internship

# Senior roles only, posted in the last 7 days
python3 main.py "data scientist" --level senior --posted-within 7

# Remote full-time roles, 10 results per source
python3 main.py "data scientist" --type full-time --location remote --limit 10

# Open result #5 directly in your browser
python3 main.py "product manager" --open 5

# Browse results interactively with arrow keys
python3 main.py "PM" --browse

# Research roles (government + academia via USAJobs)
python3 main.py "research scientist" --type research --sources usajobs

# Export to CSV
python3 main.py "data analyst" --export results.csv

# Score results against your resume
python3 main.py "MLE" --resume ~/resume.pdf

# Launch AI chat mode
python3 main.py --chat

# Chat mode with resume pre-loaded
python3 main.py --chat --resume ~/resume.pdf
```

---

## Query expansion

You don't need to know the exact job title to search. Common abbreviations are expanded automatically:

| You type | Searches for |
|---|---|
| `SWE` | software engineer |
| `PM` | product manager |
| `DS` | data scientist |
| `MLE` | machine learning engineer |
| `ML` | machine learning |
| `SRE` | site reliability engineer |
| `DevOps` | devops engineer |
| `UX` | UX designer |
| `QA` | QA engineer |
| `BA` | business analyst |

When a query is expanded, the tool tells you: `Searching for "software engineer" (expanded from "SWE")`.

---

## Seniority filter

`--level` infers experience level from each listing's title and filters accordingly:

```bash
python3 main.py "engineer" --level senior
python3 main.py "SWE" --type internship --level intern
```

Levels: `intern`, `junior`, `mid`, `senior`, `lead`. Listings that can't be inferred are shown under `any`.

---

## Interactive browser

`--browse` launches a keyboard-driven result browser after the table renders:

```bash
python3 main.py "product manager" --browse
```

| Key | Action |
|---|---|
| `↑` / `k` | Move up |
| `↓` / `j` | Move down |
| `Enter` | Open highlighted result in browser |
| `q` | Quit browser |

---

## AI chat mode

Chat mode lets you search and explore job listings in plain English — no flags to remember. Just describe what you want, then keep refining.

```bash
python3 main.py --chat
```

```
job-scout chat  ·  provider: openai (gpt-4o-mini)  ·  resume: none
Type /help for commands, /exit to quit.

you> find ml engineering internships in new york

[searching…]
Found 18 internships. Here are the top results:

 #  Title                  Company     Location  Posted      Match
 1  ML Research Intern     Hudson AI   NYC       2026-05-06
 2  Applied ML Intern      Two Sigma   NYC       2026-05-04
 3  ML Platform Intern     Citadel     NYC       2026-05-03
...

you> filter to only startups, drop the finance companies
Filtered to 7 listings.

you> open 1
Opening https://... in browser.

you> what skills does #2 need?
Two Sigma — Applied ML Intern:
  • Python, PyTorch, distributed training
  • Strong stats / probability fundamentals
  • Experience with large datasets (Spark or equivalent)

you> save these to ~/Desktop/ml-internships.csv
Exported 7 listing(s) to /Users/.../ml-internships.csv.

you> /exit
Goodbye.
```

### Built-in chat commands

| Command | Description |
|---|---|
| `/help` | Show available commands and agent capabilities |
| `/results` | Re-render the current results table |
| `/clear` | Clear results and conversation history |
| `/resume PATH` | Load or replace a resume mid-session |
| `/exit`, `/quit` | Exit. Ctrl-D also exits. |

Chat mode requires an AI key — see [AI setup](#ai-setup) below.

---

## AI resume matching

Pass `--resume` to any standard search to score every listing against your resume. Results are re-sorted by match score and a skills gap summary + resume tips are printed below the table.

```bash
python3 main.py "ml engineer" --resume ~/resume.pdf
```

```
Searching... (spinner per source)
Scoring 23 listings against resume...

                    job-scout results for "ml engineer"
 #  Title                  Company  Location  Type       Posted      Salary  Match
 1  Senior ML Engineer     Acme     Remote    full-time  2026-05-08  $180k   92%
 2  ML Platform Engineer   Globex   NYC       full-time  2026-05-07          88%
 3  Applied ML Engineer    Initech  Austin    full-time  2026-05-06  $150k   74%
...

Skills Gap (frequent in top listings, not found in your resume):
  • Kubernetes (in 14 listings)
  • Ray / distributed training (in 9 listings)
  • Online feature stores (in 6 listings)

Resume Tips:
  • Quantify model impact — most listings screen for production metrics (latency, accuracy lift).
  • Add a one-line MLOps summary; half of these roles require K8s or CI for ML pipelines.
  • Move your Spark/Ray experience above the fold — it's the most-asked distributed computing skill here.
```

Match score colors: green (90%+), cyan (70–89%), yellow (50–69%), red (below 50%).

PDF and plain-text resumes are both supported. If no AI key is present, `--resume` prints a warning and falls back to the standard unscored table.

---

## AI setup

AI features (chat mode and resume matching) work with any one of these providers:

| Provider | Environment variable | Get a key |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| Anthropic | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| Gemini | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |

You only need one. Add it to your `.env` file:

```
OPENAI_API_KEY=sk-...
```

Or let the first-run setup wizard collect it interactively — it will prompt for a provider and key as part of its setup flow.

You can also set a default resume path so you don't have to pass `--resume` every time:

```
RESUME_PATH=/Users/you/resume.pdf
```

Models used (cheapest/fastest in each family): `gpt-4o-mini`, `claude-haiku`, `gemini-1.5-flash`.

---

## Output

After each search, job-scout displays:

1. **A color-coded table** — job type is highlighted: internship = yellow, full-time = green, research = cyan, contract = magenta
2. **A numbered application link list** — every result's URL printed below the table

To jump straight to an application:

```bash
python3 main.py "product manager" --limit 20 --open 3
```

---

## Optional API keys (non-AI)

The setup wizard handles these on first run, but you can also configure them manually. Copy `.env.example` to `.env` and fill in any of:

```
ADZUNA_APP_ID=your_app_id_here
ADZUNA_APP_KEY=your_app_key_here
USAJOBS_USER_AGENT=your_email@example.com
USAJOBS_AUTH_KEY=your_usajobs_api_key_here
```

- **Adzuna** — [developer.adzuna.com](https://developer.adzuna.com) — free, 250 req/day
- **USAJobs** — [developer.usajobs.gov](https://developer.usajobs.gov) — free, no rate limit

Any missing keys are silently skipped — the rest of the sources still run.

---

## Project structure

```
job-scout/
├── main.py                  # CLI entry point
├── config.py                # Source registry and env config
├── models.py                # JobListing dataclass
├── ai/
│   ├── provider.py          # AI provider detection (OpenAI / Anthropic / Gemini)
│   ├── agent.py             # Chat mode REPL and LangChain agent
│   ├── tools.py             # Agent tools (search, filter, open, score, export)
│   ├── resume_parser.py     # PDF and text resume loading
│   └── scorer.py            # Batched resume scoring + skills gap + tips
├── sources/
│   ├── base.py              # Abstract JobSource interface
│   ├── jobspy_source.py     # LinkedIn, Indeed, Glassdoor, ZipRecruiter
│   ├── adzuna.py
│   ├── remotive.py
│   ├── remoteok.py
│   ├── usajobs.py
│   └── weworkremotely.py
├── search/
│   ├── query.py             # Query normalization and relevance filtering
│   └── pipeline.py          # Shared fetch + filter + dedupe pipeline
├── output/
│   ├── table.py             # Terminal table renderer
│   └── csv_writer.py        # CSV export
├── requirements.txt
├── requirements.lock        # Pinned versions for reproducible installs
└── .env.example
```

---

## Adding a new source

1. Create `sources/your_source.py` implementing the `JobSource` base class
2. Implement `search(self, query, job_type, location, limit) -> list[JobListing]`
3. Register an instance in `config.py` inside `_build_registry()`

---

## License

MIT

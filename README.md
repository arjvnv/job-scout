# job-scout

A command-line tool that searches job listings across LinkedIn, Indeed, Glassdoor, and more simultaneously. Enter a role name and get back a unified, deduplicated list of open positions — full-time, internship, contract, or research.

```
python3 main.py "product manager" --type internship
```

No API keys required to get started.

---

## Features

- Search by partial or full role name (`"product"` matches product manager, product marketing, etc.)
- Filter by job type: `full-time`, `internship`, `contract`, `research`, or `any`
- Filter by location or `remote`
- Results from multiple sources fetched concurrently and deduplicated
- Live progress spinner showing each source as it completes
- Numbered application links printed below every result table
- Open any result directly in your browser with `--open N`
- Optional CSV export
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

The first four sources work with zero configuration. Adzuna and USAJobs are optional extras — the tool's first-run wizard will ask if you want to set them up.

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

On first run, a setup wizard will appear asking if you want to configure optional API keys. You can skip it entirely — LinkedIn, Indeed, and the other sources work immediately without any keys.

---

## Usage

```
python3 main.py QUERY [OPTIONS]
```

### Options

| Flag | Short | Description | Default |
|---|---|---|---|
| `--type` | `-t` | `full-time`, `internship`, `contract`, `research`, `any` | `any` |
| `--location` | `-l` | City, country, or `remote` | (none) |
| `--limit` | `-n` | Max results per source | `50` |
| `--open` | | Open result #N in your browser | (none) |
| `--export` | `-e` | Save results to a CSV file | (none) |
| `--force` | `-f` | Overwrite existing export file | `false` |
| `--sources` | `-s` | Comma-separated list of sources to query | (all) |
| `--resume` | | Path to a resume (PDF or .txt) to score listings against | (none) |
| `--chat` | | Launch the interactive AI chat REPL | `false` |

### Examples

```bash
# All open product manager roles
python3 main.py "product manager"

# Internships matching "software" (software engineer intern, software dev intern, etc.)
python3 main.py "software" --type internship

# Remote full-time roles, 10 results per source
python3 main.py "data scientist" --type full-time --location remote --limit 10

# Open result #5 directly in your browser
python3 main.py "product manager" --open 5

# Research roles (government + academia via USAJobs)
python3 main.py "research scientist" --type research --sources usajobs

# Export to CSV for filtering in a spreadsheet
python3 main.py "data analyst" --export results.csv

# Score results against your resume (requires an AI key)
python3 main.py "ml engineer" --type full-time --resume ~/resume.pdf

# Launch the interactive AI chat REPL
python3 main.py --chat
```

---

## Chat mode

`python3 main.py --chat` starts an interactive REPL where you can describe what you want in natural language. The agent uses the same search pipeline as the standard CLI and can search, filter, score against your resume, open results in the browser, summarize listings, and export to CSV.

```
$ python3 main.py --chat

job-scout chat  ·  provider: openai (gpt-4o-mini)  ·  resume: loaded (~/resume.pdf)
Type /help for commands, /exit to quit.

you> find ml internships in nyc
you> filter to companies with under 500 people
you> open 1
you> save these to ~/Desktop/ml-internships.csv
you> /exit
```

Built-in commands:

| Command | Description |
|---|---|
| `/help` | List commands and agent capabilities. |
| `/results` | Re-render the current results table. |
| `/clear` | Clear results and conversation history. |
| `/resume PATH` | Load or replace the resume in-session. |
| `/exit`, `/quit` | Exit chat. Ctrl-D also exits. |

Chat mode requires an AI provider key — see [AI setup](#ai-setup) below.

---

## Resume matching

Pass `--resume PATH` to any standard search to score listings against a resume. PDF and plain-text resumes are supported. The results table gets a new colored `Match` column, results are re-sorted by score, and a `Skills Gap` + `Resume Tips` block is printed below the table.

```bash
python3 main.py "ml engineer" --resume ~/resume.pdf
```

Without an AI key, `--resume` prints a yellow warning and falls back to the standard table.

---

## AI setup

AI features (chat mode + resume matching) work with any of OpenAI, Anthropic, or Gemini. Add one of the following to your `.env`:

```
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
RESUME_PATH=/path/to/resume.pdf   # optional default resume for --chat
```

The setup wizard (first run) will prompt for an AI provider and an optional default resume path. If multiple keys are set, the first match in the order above wins.

---

## Output

After each search, job-scout displays:

1. **A color-coded table** — job type is highlighted (internship = yellow, full-time = green, research = cyan, contract = magenta)
2. **A numbered application link list** — every result's URL printed below the table for easy copying

To jump straight to an application, pass `--open N` where N is the result number:

```bash
python3 main.py "product manager" --limit 20 --open 3
```

---

## Optional API keys

The setup wizard handles this on first run, but you can also configure keys manually. Copy `.env.example` to `.env` and fill in any of:

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

## Project Structure

```
job-scout/
├── main.py                  # CLI entry point
├── config.py                # Source registry and env config
├── models.py                # JobListing dataclass
├── sources/
│   ├── base.py              # Abstract JobSource interface
│   ├── jobspy_source.py     # LinkedIn, Indeed, Glassdoor, ZipRecruiter
│   ├── adzuna.py
│   ├── remotive.py
│   ├── remoteok.py
│   ├── usajobs.py
│   └── weworkremotely.py
├── search/
│   └── query.py             # Query normalization and relevance filtering
├── output/
│   ├── table.py             # Terminal table renderer
│   └── csv_writer.py        # CSV export
├── requirements.txt
├── requirements.lock        # Pinned versions for reproducible installs
└── .env.example
```

---

## Adding a New Source

1. Create `sources/your_source.py` implementing the `JobSource` base class
2. Implement `search(self, query, job_type, location, limit) -> list[JobListing]`
3. Register an instance in `config.py` inside `_build_registry()`

---

## License

MIT

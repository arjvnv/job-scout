# job-scout

A command-line tool that searches job listings across multiple platforms simultaneously. Enter a role name and get back a unified, deduplicated list of open positions — full-time, internship, contract, or research.

```
python main.py "product manager" --type internship --limit 20
```

---

## Features

- Search by partial or full role name (`"product"` matches product manager, product marketing, etc.)
- Filter by job type: `full-time`, `internship`, `contract`, `research`, or `any`
- Filter by location or `remote`
- Results from multiple sources fetched concurrently and deduplicated
- Rich color-coded terminal table output
- Optional CSV export

---

## Sources

| Source | API / Scrape | Key Required | Specialty |
|---|---|---|---|
| Adzuna | API | Yes (free) | Broad — aggregates Indeed, Glassdoor, and others |
| Remotive | API | No | Remote tech roles |
| RemoteOK | API | No | Remote roles |
| USAJobs | API | Yes (free) | Government and research positions |
| We Work Remotely | Scrape | No | Remote roles |

Remotive, RemoteOK, and We Work Remotely work out of the box with no configuration. Adzuna and USAJobs require free API keys (see [Setup](#setup)).

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

Or, for a reproducible install using the pinned lockfile:

```bash
pip install -r requirements.lock
```

### 3. Configure API keys

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

Open `.env` and set the values:

```
ADZUNA_APP_ID=your_app_id_here
ADZUNA_APP_KEY=your_app_key_here
USAJOBS_USER_AGENT=your_email@example.com
USAJOBS_AUTH_KEY=your_usajobs_api_key_here
```

**Getting free API keys:**

- **Adzuna** — Register at [developer.adzuna.com](https://developer.adzuna.com). Free tier: 250 requests/day.
- **USAJobs** — Register at [developer.usajobs.gov](https://developer.usajobs.gov). Free, no rate limit. Use your email as the `User-Agent` value and your assigned key as `USAJOBS_AUTH_KEY`.

If a key is missing, that source is skipped and the others still run.

---

## Usage

```
python main.py QUERY [OPTIONS]
```

### Options

| Flag | Short | Description | Default |
|---|---|---|---|
| `--type` | `-t` | `full-time`, `internship`, `contract`, `research`, `any` | `any` |
| `--location` | `-l` | City, country, or `remote` | (none) |
| `--limit` | `-n` | Max results per source | `20` |
| `--export` | `-e` | Save results to a CSV file | (none) |
| `--force` | `-f` | Overwrite existing export file without prompting | `false` |
| `--sources` | `-s` | Comma-separated list of sources to query | (all) |

### Examples

```bash
# All open "product manager" roles
python main.py "product manager"

# Internships matching "product" (product manager, product marketing, etc.)
python main.py "product" --type internship

# Remote software engineering roles, limit 10 per source
python main.py "software engineer" --type full-time --location remote --limit 10

# Research scientist roles from USAJobs only
python main.py "research scientist" --type research --sources usajobs

# Export results to CSV
python main.py "data analyst" --export results.csv

# Query only the keyless sources
python main.py "designer" --sources remotive,remoteok,weworkremotely
```

---

## Output

Results are displayed as a color-coded table in the terminal:

- Full-time: green
- Internship: yellow
- Research: cyan
- Contract: magenta

If `--export` is passed, results are also saved to a CSV with all fields (title, company, location, type, URL, source, posted date, salary).

---

## Project Structure

```
job-scout/
├── main.py                  # CLI entry point
├── config.py                # Source registry and env config
├── models.py                # JobListing dataclass
├── sources/
│   ├── base.py              # Abstract JobSource interface
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

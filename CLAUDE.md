# Singing Clock - Claude Code Session Guide

## Project Overview

Singing Clock is a convergence countdown dashboard for AI-assisted software projects. It scans git repos, scores commits against a capability rubric, fits logistic growth models, and predicts when a project reaches self-sufficiency.

**Public repo:** https://github.com/mickdarling/singing-clock-public
**Private repo (full history):** `~/Developer/singing-clock` (not this repo)

## Architecture

- `scan.py` — main scanner: repo discovery, commit extraction, regex scoring, LLM enrichment (--enrich), diffstat weighting, logistic model fitting, data.json output
- `server.py` — local HTTP server with /api/scan endpoint
- `index.html` — dashboard UI (Chart.js, vanilla JS, no build step)
- All Python is pure stdlib (no pip dependencies). LLM enrichment uses urllib.request.

## Key Design Decisions

- AGPL-3.0 with dual commercial license
- SCAN_DIRS is intentionally empty — users configure for their own repos
- Private repo names from the original project have been scrubbed
- All cache/data files are gitignored (local-only)
- `--enrich` is opt-in, requires ANTHROPIC_API_KEY env var
- LLM classifications cached in enrich_cache.json, never re-fetched
- Score cache version is 3 (SCORE_CACHE_VERSION) — bump when scoring formula changes

## Scoring System

9 categories with weights 1-5. Regex patterns match commit messages. LLM enrichment replaces regex with semantic classification. Diffstat weighting adjusts scores based on code volume. Constants for all thresholds are at module level (LARGE_SOURCE_THRESHOLD, CONFIG_ONLY_MULTIPLIER, etc.).

## Open Issues

- #1: Improve sophistication metric beyond category ratios
- #2: Schema validation for cache files on load
- #3: Externalize configuration (repos, rubric, goal definition) — HIGH PRIORITY for public repo
- #4: npm package with easy install
- #5: Robust test infrastructure
- #6: Dual-scoring graph overlays (regex vs LLM vs combined)
- #7: Track/graph scoring snapshots over time (convergence drift)
- #8: Score open issues by projected convergence impact

## Git Workflow

- `main` branch only (fresh public repo, no develop branch yet)
- Create feature branches for non-trivial work
- PR into main with Claude review via @claude comment
- GitHub Actions: `claude.yml` (on @claude mention), `claude-code-review.yml` (on PR events)
- Both workflows need CLAUDE_CODE_OAUTH_TOKEN secret configured

## Local Testing

```bash
# Regex-only scan (no API key needed, but SCAN_DIRS must be configured)
python3 scan.py

# LLM-enriched scan
ANTHROPIC_API_KEY=<key> python3 scan.py --enrich

# Dashboard
python3 server.py  # http://localhost:8080
```

## What NOT to Do

- Don't commit cache files, data.json, or history.json
- Don't hardcode paths to specific user directories or private repo names
- Don't add external Python dependencies (stdlib only for core scanner)

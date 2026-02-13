# Singing Clock

**Convergence countdown dashboard for AI-assisted software projects.**

Singing Clock scans git repositories, scores commits against a capability rubric, fits logistic growth models, and predicts when a project will reach self-sufficiency. It answers the question: *"When does the AI stop needing the human?"*

## How It Works

1. **Discover** — finds all git repos under configured directories
2. **Extract** — pulls commit history and diffstats across all repos
3. **Score** — classifies each commit against 9 capability categories (regex or LLM)
4. **Model** — fits logistic curves to cumulative capability, commit rate, and sophistication
5. **Predict** — estimates a convergence date where growth plateaus
6. **Visualize** — renders a live dashboard with charts and countdown timer

## Quick Start

```bash
# Clone and run (pure Python, no dependencies)
git clone https://github.com/mickdarling/singing-clock.git
cd singing-clock

# Scan your repos and generate data.json
python3 scan.py

# Start the dashboard
python3 server.py
# Open http://localhost:8080
```

## LLM Enrichment (Optional)

By default, commits are scored with regex pattern matching. For much better accuracy, enable LLM-based semantic classification:

```bash
# Uses Anthropic API (Claude Haiku by default)
ANTHROPIC_API_KEY=your-key python3 scan.py --enrich

# Or use Sonnet for higher quality
ANTHROPIC_API_KEY=your-key python3 scan.py --enrich --enrich-model sonnet
```

LLM classifications are cached in `enrich_cache.json` — subsequent runs are instant with zero API calls. Falls back to regex on any API failure.

## Capability Categories

| Category | Weight | What It Detects |
|----------|--------|-----------------|
| foundation | 1 | Setup, scaffolding, boilerplate |
| elements | 2 | CRUD operations, element management |
| safety | 2 | Trust, permissions, validation |
| integration | 2 | IDE, API, deployment, external services |
| agents | 3 | Autonomous execution, goal-directed behavior |
| ecosystem | 3 | Collections, portfolios, marketplace |
| aql | 4 | Query language, tool dispatch, resolvers |
| self_modify | 5 | Self-improvement, runtime creation, adaptation |
| meta | 5 | Introspection, relationships, orchestration |

## Configuration

Edit the constants at the top of `scan.py`:

- `SCAN_DIRS` — specific directories to scan for git repos
- `BROAD_SCAN_DIR` / `BROAD_SCAN_MAX_DEPTH` — broad recursive scan
- `SKIP_PATTERNS` — substring patterns to exclude repos
- `CATEGORIES` — scoring rubric (weights and regex patterns)

## Files

| File | Tracked | Purpose |
|------|---------|---------|
| `scan.py` | Yes | Main scanner and scoring engine |
| `server.py` | Yes | Local dashboard web server |
| `index.html` | Yes | Dashboard UI |
| `data.json` | No | Generated scan output |
| `score_cache.json` | No | Cached regex+diffstat scores |
| `diffstat_cache.json` | No | Cached git diffstats |
| `enrich_cache.json` | No | Cached LLM classifications |
| `history.json` | No | Convergence date history |

## License

This project is dual-licensed:

- **AGPL-3.0** — free for open source use (see [LICENSE](LICENSE))
- **Commercial License** — available for proprietary/commercial use. Contact the maintainer for terms.

## Requirements

- Python 3.8+
- Git
- No external Python packages (pure stdlib)
- Optional: `ANTHROPIC_API_KEY` for LLM enrichment

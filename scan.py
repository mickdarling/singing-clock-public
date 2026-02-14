#!/usr/bin/env python3
"""
Singing Clock - Convergence Scanner
====================================
Scans all git repositories, scores commits against a self-sufficiency
capability rubric, fits decay/growth models, and outputs data.json
for the countdown clock dashboard.

Usage: python3 scan.py [--enrich] [--enrich-model haiku|sonnet]

No external dependencies - pure Python stdlib.
Optional --enrich uses Anthropic API (requires ANTHROPIC_API_KEY env var).
"""

import datetime
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "config.json"
CONFIG_EXAMPLE = Path(__file__).parent / "config.example.json"

# Defaults (used when no config.json exists)
INCEPTION_DATE = "2025-06-30"
DEVELOPER_DIR = Path.home() / "Developer"

# Directories to scan for git repos (customize for your setup)
SCAN_DIRS = [
    # Add specific directories containing your git repos, e.g.:
    # DEVELOPER_DIR / "my-org" / "projects",
]

# Also search broadly under Developer (depth-limited)
BROAD_SCAN_DIR = DEVELOPER_DIR
BROAD_SCAN_MAX_DEPTH = 4

# Skip patterns (substring match on full path)
SKIP_PATTERNS = [
    "/archive/",
    "/backup/",
    "node_modules",
    ".Trash",
    "singing-clock",
    "singing-clock-public",
]

OUTPUT_FILE = Path(__file__).parent / "data.json"
HISTORY_FILE = Path(__file__).parent / "history.json"
SCORE_CACHE_FILE = Path(__file__).parent / "score_cache.json"
DIFFSTAT_CACHE_FILE = Path(__file__).parent / "diffstat_cache.json"
# Bump SCORE_CACHE_VERSION when scoring formula changes (pattern weights,
# diffstat multipliers, category definitions). This invalidates all cached
# scores and forces re-scoring with the new formula.
SCORE_CACHE_VERSION = 3  # bumped: review fixes to diffstat weights and config-only rule

ENRICH_CACHE_FILE = Path(__file__).parent / "enrich_cache.json"
ENRICH_CACHE_VERSION = 1
ENRICH_BATCH_SIZE = 50
ENRICH_MAX_RETRIES = 3
ENRICH_API_URL = "https://api.anthropic.com/v1/messages"
ENRICH_MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
}

SOURCE_EXTS = {".ts", ".js", ".py", ".sh", ".mjs", ".cjs", ".go", ".rs", ".tsx", ".jsx"}
TEST_PATTERNS = (".test.", ".spec.", "__tests__/", "test_", "_test.")
CONFIG_EXTS = {".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".env"}
DOC_EXTS = {".md", ".txt", ".rst"}

# Diffstat scoring thresholds and weights
LARGE_SOURCE_THRESHOLD = 100   # lines added — major refactor/feature
MEDIUM_SOURCE_THRESHOLD = 30   # lines added — significant change
LARGE_SOURCE_BONUS = 0.30
MEDIUM_SOURCE_BONUS = 0.15
MAJOR_NEW_FILES_THRESHOLD = 3  # new files — new module/feature
MINOR_NEW_FILES_THRESHOLD = 1  # new files — single new file
MAJOR_NEW_FILES_BONUS = 0.20
MINOR_NEW_FILES_BONUS = 0.10
CONFIG_ONLY_MULTIPLIER = 0.8   # dampening for config-only commits
DELETION_HEAVY_THRESHOLD = 50  # lines deleted — significant removal
DELETION_HEAVY_MULTIPLIER = 0.85
MULTIPLIER_FLOOR = 0.4
MULTIPLIER_CEILING = 2.0
TEST_LINES_THRESHOLD = 10     # test lines added to trigger safety bonus
TEST_SAFETY_BONUS = 2


# ─── Config File Loading ─────────────────────────────────────────────────

def load_config():
    """Load configuration from config.json, falling back to built-in defaults.

    Returns the parsed config dict, or None if no config file exists.
    On parse error, prints a warning and returns None (uses defaults).
    """
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text())
        if not isinstance(data, dict):
            print(f"  Warning: config.json is not a JSON object, using defaults")
            return None
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: config.json could not be loaded ({e}), using defaults")
        return None


def apply_config(config):
    """Apply a loaded config dict to the module-level constants.

    Only overrides values that are present in the config. Missing keys
    keep the built-in defaults. This function mutates module globals.
    """
    global INCEPTION_DATE, SCAN_DIRS, BROAD_SCAN_DIR, BROAD_SCAN_MAX_DEPTH
    global SKIP_PATTERNS, CATEGORIES, HIGH_LEVEL_CATS, LOW_LEVEL_CATS
    global LARGE_SOURCE_THRESHOLD, MEDIUM_SOURCE_THRESHOLD
    global LARGE_SOURCE_BONUS, MEDIUM_SOURCE_BONUS
    global MAJOR_NEW_FILES_THRESHOLD, MINOR_NEW_FILES_THRESHOLD
    global MAJOR_NEW_FILES_BONUS, MINOR_NEW_FILES_BONUS
    global CONFIG_ONLY_MULTIPLIER, DELETION_HEAVY_THRESHOLD
    global DELETION_HEAVY_MULTIPLIER, MULTIPLIER_FLOOR, MULTIPLIER_CEILING
    global TEST_LINES_THRESHOLD, TEST_SAFETY_BONUS

    if not config:
        return

    # Goal settings
    goal = config.get("goal", {})
    if "inception_date" in goal:
        INCEPTION_DATE = goal["inception_date"]

    # Repo settings
    repos = config.get("repos", {})
    if "scan_dirs" in repos:
        SCAN_DIRS = [Path(os.path.expanduser(d)) for d in repos["scan_dirs"]]
    broad = repos.get("broad_scan", {})
    if "root" in broad:
        BROAD_SCAN_DIR = Path(os.path.expanduser(broad["root"]))
    if "max_depth" in broad:
        BROAD_SCAN_MAX_DEPTH = int(broad["max_depth"])
    if "skip_patterns" in repos:
        SKIP_PATTERNS = repos["skip_patterns"]

    # Scoring thresholds
    scoring = config.get("scoring", {})
    if scoring:
        LARGE_SOURCE_THRESHOLD = scoring.get("large_source_threshold", LARGE_SOURCE_THRESHOLD)
        MEDIUM_SOURCE_THRESHOLD = scoring.get("medium_source_threshold", MEDIUM_SOURCE_THRESHOLD)
        LARGE_SOURCE_BONUS = scoring.get("large_source_bonus", LARGE_SOURCE_BONUS)
        MEDIUM_SOURCE_BONUS = scoring.get("medium_source_bonus", MEDIUM_SOURCE_BONUS)
        MAJOR_NEW_FILES_THRESHOLD = scoring.get("major_new_files_threshold", MAJOR_NEW_FILES_THRESHOLD)
        MINOR_NEW_FILES_THRESHOLD = scoring.get("minor_new_files_threshold", MINOR_NEW_FILES_THRESHOLD)
        MAJOR_NEW_FILES_BONUS = scoring.get("major_new_files_bonus", MAJOR_NEW_FILES_BONUS)
        MINOR_NEW_FILES_BONUS = scoring.get("minor_new_files_bonus", MINOR_NEW_FILES_BONUS)
        CONFIG_ONLY_MULTIPLIER = scoring.get("config_only_multiplier", CONFIG_ONLY_MULTIPLIER)
        DELETION_HEAVY_THRESHOLD = scoring.get("deletion_heavy_threshold", DELETION_HEAVY_THRESHOLD)
        DELETION_HEAVY_MULTIPLIER = scoring.get("deletion_heavy_multiplier", DELETION_HEAVY_MULTIPLIER)
        MULTIPLIER_FLOOR = scoring.get("multiplier_floor", MULTIPLIER_FLOOR)
        MULTIPLIER_CEILING = scoring.get("multiplier_ceiling", MULTIPLIER_CEILING)
        TEST_LINES_THRESHOLD = scoring.get("test_lines_threshold", TEST_LINES_THRESHOLD)
        TEST_SAFETY_BONUS = scoring.get("test_safety_bonus", TEST_SAFETY_BONUS)

    # Rubric (category definitions)
    rubric = config.get("rubric", {})
    if "categories" in rubric:
        CATEGORIES.clear()
        for cat_name, cat_def in rubric["categories"].items():
            CATEGORIES[cat_name] = {
                "weight": cat_def.get("weight", 1),
                "patterns": cat_def.get("patterns", []),
            }
        # Recompile regex patterns
        for cat in CATEGORIES.values():
            cat["compiled"] = [re.compile(p) for p in cat["patterns"]]
    if "high_level_categories" in rubric:
        HIGH_LEVEL_CATS = set(rubric["high_level_categories"])
    if "low_level_categories" in rubric:
        LOW_LEVEL_CATS = set(rubric["low_level_categories"])


# ─── Capability Scoring Rubric ───────────────────────────────────────────

CATEGORIES = {
    "foundation": {
        "weight": 1,
        "patterns": [
            r"initial commit", r"setup", r"scaffold", r"boilerplate",
            r"package\.json", r"tsconfig", r"eslint", r"prettier",
            r"basic.*structure", r"foundation", r"directory structure",
        ],
    },
    "elements": {
        "weight": 2,
        "patterns": [
            r"persona", r"skill", r"template", r"memory", r"element type",
            r"element.*system", r"crud", r"create.*element", r"edit.*element",
            r"delete.*element", r"list.*element", r"get.*element",
            r"element.*manager", r"element.*handler", r"element.*storage",
            r"element.*validator", r"element.*loader",
        ],
    },
    "agents": {
        "weight": 3,
        "patterns": [
            r"agent", r"execute", r"execution", r"autonomy", r"autonomous",
            r"agentic", r"goal", r"objective", r"step", r"execution.*state",
            r"execution.*lifecycle", r"complete.*execution", r"continue.*execution",
            r"update.*execution", r"agent.*loop", r"budget",
        ],
    },
    "self_modify": {
        "weight": 5,
        "patterns": [
            r"self.?modif", r"self.?improv", r"self.?evolv", r"self.?updat",
            r"dynamic.*creat", r"runtime.*creat", r"programmatic.*creat",
            r"auto.?generat", r"element.*creat.*element", r"meta.?element",
            r"create.*from.*template", r"derive", r"compose",
            r"addentry", r"add.*entry", r"append.*memory",
            r"evolv", r"adapt", r"learn",
        ],
    },
    "meta": {
        "weight": 5,
        "patterns": [
            r"introspect", r"relationship", r"find.*similar", r"search.*by.*verb",
            r"relationship.*stats", r"element.*relationship", r"dependency",
            r"self.?aware", r"meta.?cogni", r"reflect", r"reason.*about",
            r"ensemble", r"compose", r"orchestrat",
            r"active.*element", r"render", r"context.*build",
        ],
    },
    "ecosystem": {
        "weight": 3,
        "patterns": [
            r"collection", r"portfolio", r"install", r"import",
            r"marketplace", r"catalog", r"browse", r"search.*collection",
            r"submit", r"publish", r"share", r"github.*auth",
            r"sync.*portfolio", r"portfolio.*element",
        ],
    },
    "safety": {
        "weight": 2,
        "patterns": [
            r"safety", r"trust", r"operator", r"security", r"permission",
            r"validation", r"sanitiz", r"escape", r"guard", r"tier",
            r"safety.*tier", r"operator.*safety", r"secure",
        ],
    },
    "integration": {
        "weight": 2,
        "patterns": [
            r"ide", r"studio", r"electron", r"bridge",
            r"api.*endpoint", r"rest.*api", r"websocket", r"stream",
            r"external", r"connect", r"oauth", r"zulip",
            r"ci.?cd", r"deploy", r"docker",
        ],
    },
    "aql": {
        "weight": 4,
        "patterns": [
            r"aql", r"query.*language", r"query.*element", r"search.*element",
            r"filter", r"narrow", r"resolver", r"disambigu",
            r"mcp.*tool", r"tool.*registr", r"tool.*handler",
            r"crude", r"operation.*dispatch",
        ],
    },
}

# Compile regex patterns
for cat in CATEGORIES.values():
    cat["compiled"] = [re.compile(p) for p in cat["patterns"]]

HIGH_LEVEL_CATS = {"agents", "self_modify", "meta", "aql"}
LOW_LEVEL_CATS = {"foundation", "elements", "integration"}


# ─── Repo Discovery ─────────────────────────────────────────────────────

def should_skip(path_str):
    for pattern in SKIP_PATTERNS:
        if pattern in path_str:
            return True
    return False


def find_repos():
    repos = set()

    # Scan specific directories
    for scan_dir in SCAN_DIRS:
        scan_dir = Path(scan_dir)
        if not scan_dir.exists():
            continue
        if (scan_dir / ".git").exists():
            if not should_skip(str(scan_dir)):
                repos.add(str(scan_dir))
        else:
            for child in scan_dir.iterdir():
                if child.is_dir() and (child / ".git").exists():
                    if not should_skip(str(child)):
                        repos.add(str(child))

    # Broad scan
    if BROAD_SCAN_DIR.exists():
        try:
            result = subprocess.run(
                ["find", str(BROAD_SCAN_DIR), "-maxdepth", str(BROAD_SCAN_MAX_DEPTH),
                 "-name", ".git", "-type", "d"],
                capture_output=True, text=True, timeout=30
            )
            for line in result.stdout.strip().split("\n"):
                if line:
                    repo_path = str(Path(line).parent)
                    if not should_skip(repo_path):
                        repos.add(repo_path)
        except (subprocess.TimeoutExpired, Exception) as e:
            print(f"  Warning: broad scan failed: {e}")

    return sorted(repos)


# ─── Commit Extraction ──────────────────────────────────────────────────

def extract_commits(repos):
    all_commits = {}  # hash -> (date, message, repo_name)

    for repo_path in repos:
        repo_name = os.path.basename(repo_path)
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "log", "--format=%H|%ai|%s", "--all"],
                capture_output=True, text=True, timeout=30
            )
            count = 0
            for line in result.stdout.strip().split("\n"):
                if not line or "|" not in line:
                    continue
                parts = line.split("|", 2)
                if len(parts) < 3:
                    continue
                hash_id, date_str, message = parts
                if hash_id not in all_commits:
                    all_commits[hash_id] = (date_str.strip(), message.strip(), repo_name)
                    count += 1
            print(f"  {repo_name}: {count} new commits")
        except (subprocess.TimeoutExpired, Exception) as e:
            print(f"  {repo_name}: ERROR - {e}")

    # Sort by date
    commits = []
    for hash_id, (date_str, message, repo_name) in all_commits.items():
        try:
            date = datetime.date.fromisoformat(date_str[:10])
            commits.append((date, message, repo_name, hash_id))
        except ValueError:
            pass

    commits.sort(key=lambda x: x[0])
    return commits


# ─── Capability Scoring ─────────────────────────────────────────────────

def score_commit(message):
    msg_lower = message.lower()
    scores = {}
    total = 0

    for cat_name, cat in CATEGORIES.items():
        hits = sum(1 for p in cat["compiled"] if p.search(msg_lower))
        if hits > 0:
            score = cat["weight"] * min(hits, 3)
            scores[cat_name] = score
            total += score

    if "merge pull request" in msg_lower and ("feat" in msg_lower or "feature" in msg_lower):
        total = int(total * 1.5) if total > 0 else 2

    if total == 0:
        total = 0.5

    return total, scores


# ─── File Classification ─────────────────────────────────────────────────

def _resolve_rename(filepath):
    """Resolve git rename syntax to the new filename.

    Handles both forms (with or without spaces around =>):
      - arrow:  "old.py => new.py"
      - brace:  "path/{old.py => new.py}"  or  "{old => new}/file.py"
    Multiple brace renames in one path are handled iteratively.
    """
    if "=>" not in filepath:
        return filepath
    # Brace form: src/{old.py => new.py}/rest — handle all brace renames
    while True:
        brace = re.search(r"\{[^}]*?=>\s*([^}]*?)\}", filepath)
        if not brace:
            break
        new_part = brace.group(1).strip()
        filepath = filepath[:brace.start()] + new_part + filepath[brace.end():]
    # Plain arrow form: old.py => new.py (only if no braces remain)
    if "=>" in filepath:
        filepath = filepath.split("=>")[-1].strip()
    return filepath


def classify_file(filepath):
    """Classify a file path as source, test, config, doc, or other."""
    filepath = _resolve_rename(filepath)
    filepath_lower = filepath.lower()
    # Test detection takes priority over source
    if any(p in filepath_lower for p in TEST_PATTERNS):
        return "test"
    ext = Path(filepath).suffix.lower()
    if ext in SOURCE_EXTS:
        return "source"
    if ext in CONFIG_EXTS:
        return "config"
    if ext in DOC_EXTS:
        return "doc"
    return "other"


# ─── Diffstat Extraction ────────────────────────────────────────────────

DIFFSTAT_CACHE_VERSION = 1

_HEX = set("0123456789abcdef")


def _is_hash(line):
    return len(line) == 40 and all(c in _HEX for c in line)


def load_diffstat_cache():
    if not DIFFSTAT_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(DIFFSTAT_CACHE_FILE.read_text())
        if isinstance(data, dict) and data.get("_v") == DIFFSTAT_CACHE_VERSION:
            return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: diffstat_cache.json corrupted ({e}), starting fresh")
    return {"_v": DIFFSTAT_CACHE_VERSION}


def save_diffstat_cache(cache):
    cache["_v"] = DIFFSTAT_CACHE_VERSION
    try:
        DIFFSTAT_CACHE_FILE.write_text(json.dumps(cache))
    except OSError as e:
        print(f"  Warning: could not write diffstat_cache.json: {e}")


def extract_diffstats(repos, cache):
    """Run git log --numstat per repo, then --diff-filter=A for accurate new file counts.

    Two passes per repo:
      1. --numstat for line counts (adds, dels, file classifications)
      2. --diff-filter=A --name-only for truly new files (not append-only edits)

    Blank lines in git log output (between hash and stats) are skipped;
    commit boundaries are detected by hash lines and EOF only.
    """
    for repo_path in repos:
        repo_name = os.path.basename(repo_path)
        try:
            # Pass 1: full numstat for line counts
            result = subprocess.run(
                ["git", "-C", repo_path, "log", "--numstat", "--format=%H", "--all"],
                capture_output=True, text=True, timeout=60
            )
            pending = {}  # hash -> {a, d, f, s, t, c} — new_files added in pass 2
            current_hash = None
            adds = dels = files = src_adds = test_adds = cfg_adds = 0

            def _flush():
                nonlocal current_hash
                if current_hash and current_hash not in cache:
                    pending[current_hash] = {
                        "a": adds, "d": dels, "f": files,
                        "s": src_adds, "t": test_adds, "c": cfg_adds,
                    }
                current_hash = None

            for line in result.stdout.split("\n"):
                line = line.strip()
                if not line:
                    continue  # skip blank lines — boundaries are hash lines
                if _is_hash(line):
                    _flush()
                    current_hash = line
                    if current_hash in cache:
                        current_hash = None
                        continue
                    adds = dels = files = src_adds = test_adds = cfg_adds = 0
                    continue
                if current_hash:
                    parts = line.split("\t", 2)
                    if len(parts) == 3:
                        a_str, d_str, filepath = parts
                        if a_str == "-" or d_str == "-":
                            continue  # binary file
                        try:
                            a = int(a_str)
                            d = int(d_str)
                        except ValueError:
                            continue
                        adds += a
                        dels += d
                        files += 1
                        ftype = classify_file(filepath)
                        if ftype == "source":
                            src_adds += a
                        elif ftype == "test":
                            test_adds += a
                        elif ftype == "config":
                            cfg_adds += a
            _flush()

            if not pending:
                continue  # all hashes already cached

            # Pass 2: count truly new files via --diff-filter=A
            result2 = subprocess.run(
                ["git", "-C", repo_path, "log", "--diff-filter=A", "--name-only",
                 "--format=COMMIT:%H", "--all"],
                capture_output=True, text=True, timeout=60
            )
            new_file_counts = {}
            current_hash = None
            for line in result2.stdout.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("COMMIT:"):
                    h = line[7:]
                    current_hash = h if h in pending else None
                    continue
                if current_hash:
                    new_file_counts[current_hash] = new_file_counts.get(current_hash, 0) + 1

            # Merge new_files counts and save to cache
            for h, stats in pending.items():
                stats["n"] = new_file_counts.get(h, 0)
                cache[h] = stats

            print(f"  {repo_name}: {len(pending)} new diffstats")
        except (subprocess.TimeoutExpired, Exception) as e:
            print(f"  {repo_name}: diffstat ERROR - {e}")
    return cache


def apply_diffstat_weight(total, cats, diffstat):
    """Apply diffstat-based weight adjustments to a commit's score."""
    if not diffstat:
        return total, cats

    # Make a copy of cats to avoid mutating the original
    cats = dict(cats)

    src_adds = diffstat.get("s", 0)
    test_adds = diffstat.get("t", 0)
    cfg_adds = diffstat.get("c", 0)
    adds = diffstat.get("a", 0)
    dels = diffstat.get("d", 0)
    new_files = diffstat.get("n", 0)

    multiplier = 1.0

    # Large source diff
    if src_adds >= LARGE_SOURCE_THRESHOLD:
        multiplier += LARGE_SOURCE_BONUS
    elif src_adds >= MEDIUM_SOURCE_THRESHOLD:
        multiplier += MEDIUM_SOURCE_BONUS

    # Config-only commit (no source or test changes, only config touched)
    if src_adds == 0 and test_adds == 0 and cfg_adds > 0:
        multiplier *= CONFIG_ONLY_MULTIPLIER

    # New files bonus
    if new_files >= MAJOR_NEW_FILES_THRESHOLD:
        multiplier += MAJOR_NEW_FILES_BONUS
    elif new_files >= MINOR_NEW_FILES_THRESHOLD:
        multiplier += MINOR_NEW_FILES_BONUS

    # Deletion-heavy
    if dels > adds and dels > DELETION_HEAVY_THRESHOLD:
        multiplier *= DELETION_HEAVY_MULTIPLIER

    # Clamp multiplier (warn if it triggers — may indicate a formula bug)
    raw = multiplier
    multiplier = max(MULTIPLIER_FLOOR, min(MULTIPLIER_CEILING, multiplier))
    if multiplier != raw:
        print(f"  Warning: diffstat multiplier clamped {raw:.2f} -> {multiplier:.2f}")

    total = total * multiplier

    # Floor score
    total = max(0.5, total)

    # Test file bonus — additive to cats dict
    if test_adds >= TEST_LINES_THRESHOLD:
        cats["safety"] = cats.get("safety", 0) + TEST_SAFETY_BONUS

    return total, cats


# ─── Math Helpers ────────────────────────────────────────────────────────

def linreg(x, y):
    n = len(x)
    if n < 2:
        return 0, 0
    sx = sum(x)
    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sx2 = sum(xi ** 2 for xi in x)
    denom = n * sx2 - sx * sx
    if abs(denom) < 1e-12:
        return 0, 0
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    return a, b


def r_squared(y_actual, y_pred):
    mean_y = sum(y_actual) / len(y_actual) if y_actual else 0
    ss_tot = sum((yi - mean_y) ** 2 for yi in y_actual)
    ss_res = sum((yi - pi) ** 2 for yi, pi in zip(y_actual, y_pred))
    if ss_tot < 1e-12:
        return 0
    return 1 - ss_res / ss_tot


def logistic(t, L, r, t_mid):
    ex = r * (t - t_mid)
    if ex > 50:
        return L
    elif ex < -50:
        return 0.0
    else:
        return L / (1.0 + math.exp(-ex))


def logistic_deriv(t, L, r, t_mid):
    ex = r * (t - t_mid)
    if abs(ex) > 50:
        return 0.0
    sig = 1.0 / (1.0 + math.exp(-ex))
    return L * r * sig * (1 - sig)


def fit_logistic(t_values, y_values, L_range, r_range, tmid_range):
    best = None
    for L in L_range:
        for r_10x in r_range:
            r = r_10x / 10.0
            for tmid_10x in tmid_range:
                tmid = tmid_10x / 10.0
                pred = [logistic(ti, L, r, tmid) for ti in t_values]
                r2 = r_squared(y_values, pred)
                if best is None or r2 > best[0]:
                    best = (r2, L, r, tmid)
    return best


# ─── Model Fitting ───────────────────────────────────────────────────────

def fit_models(monthly_data, epoch_date):
    t = list(range(len(monthly_data)))
    commits = [m["commits"] for m in monthly_data]
    capability = [m["capability"] for m in monthly_data]
    sophistication = [m["sophistication"] for m in monthly_data]
    cum_commits = [m["cumulative_commits"] for m in monthly_data]
    cum_capability = [m["cumulative_capability"] for m in monthly_data]

    total_commits = cum_commits[-1] if cum_commits else 0
    total_capability = cum_capability[-1] if cum_capability else 0

    models = {}

    # Commit rate logistic (on cumulative)
    print("  Fitting commit rate model...")
    L_range = range(int(total_commits * 1.01), int(total_commits * 1.5), max(1, int(total_commits * 0.02)))
    best = fit_logistic(t, cum_commits, L_range, range(3, 30), range(5, 50))
    if best:
        r2, L, r, tmid = best
        # Find when rate < 10/month
        zero_t = None
        for check in range(int(tmid * 10), 360):
            ct = check / 10.0
            rate = logistic_deriv(ct, L, r, tmid)
            if rate < 10:
                zero_t = ct
                break
        zero_date = (epoch_date + datetime.timedelta(days=(zero_t or 20) * 30.44)).isoformat() if zero_t else None

        # Generate projection points
        projection = []
        for future_t in range(len(monthly_data), len(monthly_data) + 12):
            rate = logistic_deriv(future_t, L, r, tmid)
            month_date = epoch_date + datetime.timedelta(days=future_t * 30.44)
            projection.append({"month": month_date.strftime("%Y-%m"), "predicted_commits": round(rate)})

        models["commit_rate"] = {
            "L": L, "r": round(r, 2), "t_mid": round(tmid, 2),
            "r_squared": round(r2, 4), "zero_date": zero_date,
            "projection": projection,
        }
        print(f"    L={L}, r={r:.1f}, t_mid={tmid:.1f}, R2={r2:.4f}, zero={zero_date}")

    # Capability logistic (on cumulative)
    print("  Fitting capability model...")
    L_range = range(int(total_capability * 1.01), int(total_capability * 2.0), max(1, int(total_capability * 0.02)))
    best = fit_logistic(t, cum_capability, L_range, range(3, 50), range(5, 50))
    if best:
        r2, L, r, tmid = best
        t95 = tmid + math.log(19) / r if r > 0 else 99
        t99 = tmid + math.log(99) / r if r > 0 else 99
        d95 = (epoch_date + datetime.timedelta(days=t95 * 30.44)).isoformat()
        d99 = (epoch_date + datetime.timedelta(days=t99 * 30.44)).isoformat()
        pct_now = total_capability / L * 100 if L > 0 else 0

        # Generate projection points
        projection = []
        for future_t in range(len(monthly_data), len(monthly_data) + 12):
            cap = logistic(future_t, L, r, tmid)
            month_date = epoch_date + datetime.timedelta(days=future_t * 30.44)
            projection.append({
                "month": month_date.strftime("%Y-%m"),
                "predicted_capability": round(cap),
                "pct_of_L": round(cap / L * 100, 1),
            })

        models["capability"] = {
            "L": round(L), "r": round(r, 2), "t_mid": round(tmid, 2),
            "r_squared": round(r2, 4),
            "pct_95_date": d95, "pct_99_date": d99,
            "pct_now": round(pct_now, 1),
            "projection": projection,
        }
        print(f"    L={L:.0f}, r={r:.1f}, t_mid={tmid:.1f}, R2={r2:.4f}, now={pct_now:.1f}%")

    # Sophistication linear trend
    print("  Fitting sophistication model...")
    nz = [(ti, si) for ti, si in zip(t, sophistication) if si > 0]
    if len(nz) >= 2:
        intercept, slope = linreg([x[0] for x in nz], [x[1] for x in nz])
        pct100_t = (1.0 - intercept) / slope if slope > 0 else 99
        pct100_date = (epoch_date + datetime.timedelta(days=pct100_t * 30.44)).isoformat()
        models["sophistication"] = {
            "slope": round(slope, 4), "intercept": round(intercept, 4),
            "pct_100_date": pct100_date,
        }
        print(f"    slope={slope:.4f}, intercept={intercept:.4f}, 100%={pct100_date}")

    # Convergence date (weighted average of model dates)
    dates_for_avg = []
    if "commit_rate" in models and models["commit_rate"]["zero_date"]:
        dates_for_avg.append(datetime.date.fromisoformat(models["commit_rate"]["zero_date"]))
    if "capability" in models:
        dates_for_avg.append(datetime.date.fromisoformat(models["capability"]["pct_95_date"]))
        dates_for_avg.append(datetime.date.fromisoformat(models["capability"]["pct_99_date"]))
    if "sophistication" in models:
        dates_for_avg.append(datetime.date.fromisoformat(models["sophistication"]["pct_100_date"]))

    if dates_for_avg:
        avg_ordinal = sum(d.toordinal() for d in dates_for_avg) // len(dates_for_avg)
        convergence = datetime.date.fromordinal(avg_ordinal)
        models["convergence_date"] = convergence.isoformat()
        print(f"  Convergence date: {convergence}")

    return models


# ─── History Tracking ────────────────────────────────────────────────────

def load_history():
    """Load existing history, returning [] on any corruption."""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text())
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: history.json corrupted ({e}), starting fresh")
    return []


def record_history(models, current):
    """Append a snapshot to history.json and return the full history."""
    history = load_history()
    entry = {
        "scan_time": datetime.datetime.now().isoformat(timespec="seconds"),
        "convergence_date": models.get("convergence_date"),
        "component_dates": {
            "commit_zero": models.get("commit_rate", {}).get("zero_date"),
            "capability_95": models.get("capability", {}).get("pct_95_date"),
            "capability_99": models.get("capability", {}).get("pct_99_date"),
            "sophistication_100": models.get("sophistication", {}).get("pct_100_date"),
        },
        "days_until_convergence": (
            (datetime.date.fromisoformat(models["convergence_date"]) - datetime.date.today()).days
            if models.get("convergence_date") else None
        ),
        "total_commits": current.get("total_commits", 0),
        "pct_of_asymptote": current.get("pct_of_asymptote", 0),
    }
    history.append(entry)
    try:
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
        print(f"  History recorded ({len(history)} entries)")
    except OSError as e:
        print(f"  Warning: could not write history.json: {e}")
    return history


# ─── Score Cache ─────────────────────────────────────────────────────────

def load_score_cache():
    if not SCORE_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(SCORE_CACHE_FILE.read_text())
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: score_cache.json corrupted ({e}), starting fresh")
    return {}


def save_score_cache(cache):
    try:
        SCORE_CACHE_FILE.write_text(json.dumps(cache))
    except OSError as e:
        print(f"  Warning: could not write score_cache.json: {e}")


# ─── CLI Arguments ───────────────────────────────────────────────────────

def parse_args():
    args = {"enrich": False, "enrich_model": "haiku"}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--enrich":
            args["enrich"] = True
        elif argv[i] == "--enrich-model" and i + 1 < len(argv):
            i += 1
            model = argv[i].lower()
            if model in ENRICH_MODELS:
                args["enrich_model"] = model
            else:
                print(f"Unknown model '{model}', using haiku")
        i += 1
    return args


# ─── Enrich Cache ────────────────────────────────────────────────────────

def load_enrich_cache():
    if not ENRICH_CACHE_FILE.exists():
        return {"_v": ENRICH_CACHE_VERSION}
    try:
        data = json.loads(ENRICH_CACHE_FILE.read_text())
        if isinstance(data, dict) and data.get("_v") == ENRICH_CACHE_VERSION:
            return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: enrich_cache.json corrupted ({e}), starting fresh")
    return {"_v": ENRICH_CACHE_VERSION}


def save_enrich_cache(cache):
    cache["_v"] = ENRICH_CACHE_VERSION
    try:
        ENRICH_CACHE_FILE.write_text(json.dumps(cache))
    except OSError as e:
        print(f"  Warning: could not write enrich_cache.json: {e}")


# ─── LLM Enrichment ─────────────────────────────────────────────────────

def build_category_descriptions():
    lines = []
    for cat_name, cat in CATEGORIES.items():
        # Extract representative keywords from regex patterns
        keywords = []
        for p in cat["patterns"]:
            # Strip regex syntax to get readable keywords
            clean = re.sub(r"[\\.*?+\[\](){}|^$]", " ", p).strip()
            clean = re.sub(r"\s+", " ", clean)
            if clean:
                keywords.append(clean)
        lines.append(f"- **{cat_name}** (weight {cat['weight']}): {', '.join(keywords[:6])}")
    return "\n".join(lines)


ENRICH_SYSTEM_PROMPT = """You classify git commits against a software capability rubric.

Categories:
{categories}

For each commit, output a JSON object with key "c" mapping category names to hit_count (1-3).
- 1 = minor/tangential relevance
- 2 = directly relevant
- 3 = deeply relevant, core implementation
- Omit categories with 0 relevance (empty dict for no matches)

Output a JSON array with one object per commit, in the exact input order.
Example for 3 commits: [{{"c": {{"agents": 2, "self_modify": 1}}}}, {{"c": {{}}}}, {{"c": {{"foundation": 1}}}}]

Output ONLY the JSON array, no other text."""


def call_anthropic_api(system_prompt, user_message, model_id, api_key):
    payload = json.dumps({
        "model": model_id,
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }).encode("utf-8")

    req = urllib.request.Request(
        ENRICH_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    # Extract text from the response
    for block in body.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    raise ValueError("No text content in API response")


def enrich_score(raw_cats):
    cats = {}
    total = 0
    for cat_name, hits in raw_cats.items():
        if cat_name not in CATEGORIES:
            continue
        hits = max(1, min(3, int(hits)))
        score = CATEGORIES[cat_name]["weight"] * hits
        cats[cat_name] = score
        total += score
    return (total or 0.5), cats


def enrich_commits(commits, enrich_cache, model_name):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("  Error: ANTHROPIC_API_KEY not set. Falling back to regex for all commits.")
        # Fall back to regex for all uncached commits
        fallback_count = 0
        for date, message, repo, hash_id in commits:
            if hash_id not in enrich_cache or hash_id.startswith("_"):
                total, cats = score_commit(message)
                enrich_cache[hash_id] = cats
                fallback_count += 1
        return 0, fallback_count

    model_id = ENRICH_MODELS[model_name]
    categories_text = build_category_descriptions()
    system_prompt = ENRICH_SYSTEM_PROMPT.format(categories=categories_text)

    # Filter to uncached commits
    uncached = [(date, message, repo, hash_id) for date, message, repo, hash_id in commits
                if hash_id not in enrich_cache or hash_id.startswith("_")]

    if not uncached:
        print("  All commits already cached.")
        return 0, 0

    print(f"  {len(uncached)} commits need enrichment ({len(commits) - len(uncached)} cached)")

    enriched_count = 0
    fallback_count = 0

    # Process in batches
    for batch_start in range(0, len(uncached), ENRICH_BATCH_SIZE):
        batch = uncached[batch_start:batch_start + ENRICH_BATCH_SIZE]
        batch_num = batch_start // ENRICH_BATCH_SIZE + 1
        total_batches = (len(uncached) + ENRICH_BATCH_SIZE - 1) // ENRICH_BATCH_SIZE
        print(f"  Batch {batch_num}/{total_batches} ({len(batch)} commits)...", end=" ", flush=True)

        # Build user message
        user_lines = []
        for i, (date, message, repo, hash_id) in enumerate(batch):
            user_lines.append(f"{i+1}. [{repo}] {message}")
        user_message = "\n".join(user_lines)

        success = False
        for attempt in range(ENRICH_MAX_RETRIES):
            try:
                response_text = call_anthropic_api(system_prompt, user_message, model_id, api_key)
                # Parse JSON array from response
                # Strip any markdown fences if present
                text = response_text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()
                results = json.loads(text)

                if not isinstance(results, list) or len(results) != len(batch):
                    raise ValueError(f"Expected array of {len(batch)}, got {type(results).__name__} of length {len(results) if isinstance(results, list) else '?'}")

                # Process each result
                batch_enriched = 0
                batch_fallback = 0
                for j, (date, message, repo, hash_id) in enumerate(batch):
                    try:
                        entry = results[j]
                        if not isinstance(entry, dict) or "c" not in entry:
                            raise ValueError("missing 'c' key")
                        raw_cats = entry["c"]
                        if not isinstance(raw_cats, dict):
                            raise ValueError("'c' is not a dict")
                        # Validate category names and hit counts
                        clean_cats = {}
                        for cat_name, hits in raw_cats.items():
                            if cat_name in CATEGORIES:
                                clean_cats[cat_name] = max(1, min(3, int(hits)))
                        enrich_cache[hash_id] = clean_cats
                        batch_enriched += 1
                    except (ValueError, TypeError, KeyError):
                        # Individual parse error — fall back to regex for this commit
                        total, cats = score_commit(message)
                        enrich_cache[hash_id] = cats
                        batch_fallback += 1

                enriched_count += batch_enriched
                fallback_count += batch_fallback
                success = True
                print(f"ok ({batch_enriched} enriched, {batch_fallback} fallback)")
                break

            except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
                    ValueError, OSError) as e:
                if attempt < ENRICH_MAX_RETRIES - 1:
                    delay = 2 ** attempt  # 1s, 2s, 4s
                    print(f"retry ({e})...", end=" ", flush=True)
                    time.sleep(delay)
                else:
                    # All retries failed — fall back to regex for entire batch
                    print(f"failed ({e}), using regex fallback")
                    for date, message, repo, hash_id in batch:
                        if hash_id not in enrich_cache or hash_id.startswith("_"):
                            total, cats = score_commit(message)
                            enrich_cache[hash_id] = cats
                            fallback_count += 1

        # Save cache after every batch for crash resilience
        save_enrich_cache(enrich_cache)

    return enriched_count, fallback_count


# ─── Main ────────────────────────────────────────────────────────────────

def main(args=None):
    args = args or parse_args()
    print("=" * 60)
    print("Singing Clock - Scanning repositories...")
    print("=" * 60)

    # Load configuration
    config = load_config()
    if config:
        print(f"\n  Loaded configuration from {CONFIG_FILE.name}")
        apply_config(config)
    elif not CONFIG_FILE.exists() and CONFIG_EXAMPLE.exists():
        print(f"\n  No config.json found. Using built-in defaults.")
        print(f"  To customize, copy config.example.json to config.json:")
        print(f"    cp config.example.json config.json")
        print(f"  Then edit config.json with your repo paths and preferences.")

    # Discover repos
    print("\nDiscovering repositories...")
    repos = find_repos()
    print(f"Found {len(repos)} repositories\n")

    # Extract commits
    print("Extracting commits (deduplicating by hash)...")
    commits = extract_commits(repos)
    print(f"\nTotal unique commits: {len(commits)}")

    if not commits:
        print("No commits found!")
        sys.exit(1)

    epoch_date = datetime.date.fromisoformat(INCEPTION_DATE)
    today = datetime.date.today()
    print(f"Date range: {commits[0][0]} to {commits[-1][0]}")

    # Extract diffstats
    print("\nExtracting diffstats...")
    diffstat_cache = load_diffstat_cache()
    before = len(diffstat_cache) - 1  # exclude _v key
    diffstat_cache = extract_diffstats(repos, diffstat_cache)
    save_diffstat_cache(diffstat_cache)
    print(f"  {max(0, before)} cached, {len(diffstat_cache) - 1 - max(0, before)} new")

    # Enrich commits via LLM (optional)
    enrich_cache = None
    if args["enrich"]:
        print("\nEnriching commits via LLM...")
        enrich_cache = load_enrich_cache()
        enriched, fallbacks = enrich_commits(commits, enrich_cache, args["enrich_model"])
        save_enrich_cache(enrich_cache)
        print(f"  {enriched} enriched via LLM, {fallbacks} fell back to regex")

    # Score commits
    print("\nScoring commits...")
    cache = load_score_cache()
    scored = []
    cache_hits = 0
    for date, message, repo, hash_id in commits:
        if enrich_cache is not None and hash_id in enrich_cache and not hash_id.startswith("_"):
            # Enriched: use LLM classification + diffstat weighting
            total, cats = enrich_score(enrich_cache[hash_id])
            ds = diffstat_cache.get(hash_id)
            total, cats = apply_diffstat_weight(total, cats, ds)
        elif hash_id in cache and cache[hash_id]["v"] == SCORE_CACHE_VERSION:
            total, cats = cache[hash_id]["total"], cache[hash_id]["cats"]
            cache_hits += 1
        else:
            base_total, base_cats = score_commit(message)
            ds = diffstat_cache.get(hash_id)
            total, cats = apply_diffstat_weight(base_total, base_cats, ds)
            cache[hash_id] = {"v": SCORE_CACHE_VERSION, "total": total, "cats": cats}
        scored.append((date, total, cats, message, repo, hash_id))
    save_score_cache(cache)
    print(f"  {cache_hits} cached, {len(commits) - cache_hits} scored fresh")

    # Aggregate by month
    print("Aggregating by month...")
    all_months = []
    y, m = epoch_date.year, epoch_date.month
    while (y, m) <= (today.year, today.month):
        all_months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    monthly_commits = defaultdict(int)
    monthly_capability = defaultdict(float)
    monthly_cat_scores = defaultdict(lambda: defaultdict(float))
    daily_counts = Counter()

    for date, total, cats, message, repo, _ in scored:
        key = (date.year, date.month)
        monthly_commits[key] += 1
        monthly_capability[key] += total
        daily_counts[date] += 1
        for cat, score in cats.items():
            monthly_cat_scores[key][cat] += score

    cum_commits = 0
    cum_capability = 0
    monthly_data = []

    for ym in all_months:
        c = monthly_commits.get(ym, 0)
        cap = monthly_capability.get(ym, 0)
        cum_commits += c
        cum_capability += cap

        cats = monthly_cat_scores.get(ym, {})
        high = sum(v for k, v in cats.items() if k in HIGH_LEVEL_CATS)
        total_cat = sum(cats.values()) if cats else 1
        soph = high / total_cat if total_cat > 0 else 0

        monthly_data.append({
            "month": f"{ym[0]}-{ym[1]:02d}",
            "commits": c,
            "capability": round(cap),
            "sophistication": round(soph, 3),
            "cumulative_commits": cum_commits,
            "cumulative_capability": round(cum_capability),
        })

    # Aggregate by week
    print("Aggregating by week...")

    def week_of(d):
        return (d - epoch_date).days // 7

    total_weeks = week_of(today) + 1
    weekly_commits = defaultdict(int)
    weekly_capability = defaultdict(float)

    for date, total, cats, message, repo, _ in scored:
        w = week_of(date)
        weekly_commits[w] += 1
        weekly_capability[w] += total

    weekly_data = []
    for w in range(total_weeks):
        wdate = epoch_date + datetime.timedelta(weeks=w)
        weekly_data.append({
            "week": w,
            "start": wdate.isoformat(),
            "commits": weekly_commits.get(w, 0),
            "capability": round(weekly_capability.get(w, 0)),
        })

    # Category breakdown by month
    category_monthly = {}
    for ym in all_months:
        key = f"{ym[0]}-{ym[1]:02d}"
        cats = monthly_cat_scores.get(ym, {})
        category_monthly[key] = {cat: round(cats.get(cat, 0)) for cat in CATEGORIES}

    # Fit models
    print("\nFitting models...")
    models = fit_models(monthly_data, epoch_date)

    # Current state
    latest_date = commits[-1][0] if commits else today
    current_soph = monthly_data[-1]["sophistication"] if monthly_data else 0
    pct_asymptote = models.get("capability", {}).get("pct_now", 0)

    current = {
        "total_commits": len(commits),
        "total_capability": round(cum_capability),
        "pct_of_asymptote": pct_asymptote,
        "latest_commit_date": latest_date.isoformat(),
        "current_sophistication": current_soph,
        "days_since_inception": (today - epoch_date).days,
    }

    # Record history
    print("\nRecording convergence history...")
    convergence_history = record_history(models, current)

    # Build output
    output = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "inception_date": INCEPTION_DATE,
        "repos_scanned": len(repos),
        "total_commits": len(commits),
        "monthly": monthly_data,
        "weekly": weekly_data,
        "models": models,
        "current": current,
        "category_monthly": category_monthly,
        "convergence_history": convergence_history,
    }

    # Write JSON
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Output written to {OUTPUT_FILE}")
    print(f"{'='*60}")
    print(f"  Repos scanned:      {len(repos)}")
    print(f"  Total commits:      {len(commits):,}")
    print(f"  Capability score:   {cum_capability:,.0f}")
    print(f"  % of asymptote:     {pct_asymptote:.1f}%")
    print(f"  Sophistication:     {current_soph:.1%}")
    if "convergence_date" in models:
        conv = datetime.date.fromisoformat(models["convergence_date"])
        days_left = (conv - today).days
        print(f"  Convergence date:   {conv} ({days_left} days)")
    print()


if __name__ == "__main__":
    main()

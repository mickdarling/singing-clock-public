#!/usr/bin/env node
"use strict";

const { execSync, spawn } = require("child_process");
const { existsSync, copyFileSync, readFileSync, writeFileSync } = require("fs");
const { join, dirname } = require("path");
const readline = require("readline");

const ROOT = join(dirname(__filename), "..");
const CONFIG_FILE = join(ROOT, "config.json");
const CONFIG_EXAMPLE = join(ROOT, "config.example.json");
const SCAN_PY = join(ROOT, "scan.py");
const SERVER_PY = join(ROOT, "server.py");

// ─── Helpers ────────────────────────────────────────────────────────────

function checkPython() {
  const candidates = ["python3", "python"];
  for (const cmd of candidates) {
    try {
      const version = execSync(`${cmd} --version 2>&1`, { encoding: "utf8" }).trim();
      const match = version.match(/Python (\d+)\.(\d+)/);
      if (match && parseInt(match[1]) >= 3 && parseInt(match[2]) >= 8) {
        return cmd;
      }
    } catch (_) {
      // not found, try next
    }
  }
  return null;
}

function checkGit() {
  try {
    execSync("git --version", { stdio: "ignore" });
    return true;
  } catch (_) {
    return false;
  }
}

function runPython(pythonCmd, script, args = []) {
  const proc = spawn(pythonCmd, [script, ...args], {
    cwd: ROOT,
    stdio: "inherit",
  });
  proc.on("close", (code) => process.exit(code || 0));
  proc.on("error", (err) => {
    console.error(`Error running ${script}: ${err.message}`);
    process.exit(1);
  });
}

// ─── Setup Wizard ───────────────────────────────────────────────────────

async function ask(rl, question, defaultValue) {
  return new Promise((resolve) => {
    const prompt = defaultValue ? `${question} [${defaultValue}]: ` : `${question}: `;
    rl.question(prompt, (answer) => {
      resolve(answer.trim() || defaultValue || "");
    });
  });
}

async function setupWizard() {
  console.log("\n  Singing Clock - First Run Setup");
  console.log("  " + "=".repeat(40) + "\n");

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  try {
    const scanDir = await ask(rl, "  Directory containing your git repos", "~/Developer");
    const projectName = await ask(rl, "  Project name / goal description", "Self-sufficient AI system");
    const inceptionDate = await ask(rl, "  Inception date (YYYY-MM-DD)", new Date().toISOString().slice(0, 10));

    // Load example config and customize
    let config;
    if (existsSync(CONFIG_EXAMPLE)) {
      config = JSON.parse(readFileSync(CONFIG_EXAMPLE, "utf8"));
    } else {
      config = { repos: {}, goal: {}, scoring: {} };
    }

    config.repos = config.repos || {};
    config.repos.scan_dirs = config.repos.scan_dirs || [];
    config.repos.broad_scan = config.repos.broad_scan || {};
    config.repos.broad_scan.root = scanDir;
    config.goal = config.goal || {};
    config.goal.name = projectName;
    config.goal.inception_date = inceptionDate;

    writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2) + "\n");
    console.log(`\n  Config written to ${CONFIG_FILE}`);
    console.log("  Edit this file anytime to customize scoring, categories, and repos.\n");

    return true;
  } finally {
    rl.close();
  }
}

// ─── Commands ───────────────────────────────────────────────────────────

function printUsage() {
  console.log(`
  Singing Clock - Convergence countdown for AI-assisted projects

  Usage: singing-clock [command] [options]

  Commands:
    scan           Run the scanner (generates data.json)
    serve          Start the dashboard server (default port 8080)
    init           Re-run the setup wizard

  Scan options:
    --enrich       Use LLM enrichment (requires ANTHROPIC_API_KEY)
    --enrich-model haiku|sonnet  Choose enrichment model (default: haiku)

  Serve options:
    <port>         Specify port number (default: 8080)

  Examples:
    singing-clock                    # first run: setup wizard, then scan + serve
    singing-clock scan               # run the scanner
    singing-clock scan --enrich      # scan with LLM enrichment
    singing-clock serve              # start dashboard on port 8080
    singing-clock serve 3000         # start dashboard on port 3000
    singing-clock init               # re-run setup wizard
`);
}

// ─── Main ───────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const command = args[0] || "";

  // Check prerequisites
  const pythonCmd = checkPython();
  if (!pythonCmd) {
    console.error("\n  Error: Python 3.8+ is required but not found.");
    console.error("  Install it from https://www.python.org/downloads/\n");
    process.exit(1);
  }

  if (!checkGit()) {
    console.error("\n  Error: git is required but not found.");
    console.error("  Install it from https://git-scm.com/downloads\n");
    process.exit(1);
  }

  // Handle --help
  if (command === "--help" || command === "-h" || command === "help") {
    printUsage();
    return;
  }

  // Handle init
  if (command === "init" || command === "--init") {
    await setupWizard();
    return;
  }

  // First-run setup
  if (!existsSync(CONFIG_FILE)) {
    console.log("\n  No config.json found — running first-time setup...");
    const ok = await setupWizard();
    if (!ok) return;

    // After setup, run scan then serve
    console.log("  Running first scan...\n");
    const scanProc = spawn(pythonCmd, [SCAN_PY], { cwd: ROOT, stdio: "inherit" });
    scanProc.on("close", (code) => {
      if (code !== 0) {
        console.error("\n  Scan failed. Check your config.json and try again.");
        process.exit(code);
      }
      console.log("\n  Starting dashboard...\n");
      runPython(pythonCmd, SERVER_PY);
    });
    return;
  }

  // Route subcommands
  switch (command) {
    case "scan": {
      const scanArgs = args.slice(1);
      runPython(pythonCmd, SCAN_PY, scanArgs);
      break;
    }
    case "serve": {
      const serveArgs = args.slice(1);
      runPython(pythonCmd, SERVER_PY, serveArgs);
      break;
    }
    case "": {
      // No command: show usage
      printUsage();
      break;
    }
    default: {
      console.error(`  Unknown command: ${command}`);
      printUsage();
      process.exit(1);
    }
  }
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});

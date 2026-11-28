#!/usr/bin/env node
/**
 * npm launcher for Pull1sec.
 *
 * The app is written in Python, so this shim keeps the Python side out of the
 * user's way: on first run it creates a private virtual environment under the
 * user data directory, installs requirements.txt into it, and then runs
 * `python -m pull1sec` with the bundled source. No `pip install`, no venv to
 * activate, and upgrading the npm package reuses (or refreshes) the same
 * environment.
 */
"use strict";

const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PKG_ROOT = path.resolve(__dirname, "..");
const REQUIREMENTS = path.join(PKG_ROOT, "requirements.txt");
const WINDOWS = process.platform === "win32";

function die(message, code = 1) {
  console.error(`pull1sec: ${message}`);
  process.exit(code);
}

function dataDir() {
  if (process.env.PULL1SEC_HOME) {
    return path.resolve(process.env.PULL1SEC_HOME);
  }
  if (WINDOWS) {
    const base =
      process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
    return path.join(base, "pull1sec");
  }
  const xdg = process.env.XDG_DATA_HOME;
  const base =
    xdg && path.isAbsolute(xdg)
      ? xdg
      : path.join(os.homedir(), ".local", "share");
  return path.join(base, "pull1sec");
}

const DATA_DIR = dataDir();
const VENV_DIR = path.join(DATA_DIR, "venv");
const VENV_PYTHON = path.join(
  VENV_DIR,
  WINDOWS ? path.join("Scripts", "python.exe") : path.join("bin", "python"),
);
const STAMP = path.join(DATA_DIR, "venv.requirements");
const LOCK = path.join(DATA_DIR, "install.lock");

const MIN_VERSION = [3, 11];
const LOCK_STALE_MS = 20 * 60 * 1000;

function probe(command, prefix = [], code = "import sys") {
  return spawnSync(command, [...prefix, "-c", code], {
    stdio: ["ignore", "pipe", "pipe"],
    encoding: "utf8",
    windowsHide: true,
  });
}

/** Return {command, prefix} for a Python >= 3.11, or null. */
function usablePython(command, prefix) {
  const result = probe(
    command,
    prefix,
    "import sys; print('%d.%d' % sys.version_info[:2])",
  );
  if (result.error || result.status !== 0) return null;
  const [major, minor] = String(result.stdout || "")
    .trim()
    .split(".")
    .map(Number);
  if (major !== 3 || !(minor >= MIN_VERSION[1])) return null;
  return { command, prefix, version: `${major}.${minor}` };
}

function findPython() {
  const explicit = process.env.PULL1SEC_PYTHON;
  if (explicit) {
    const found = usablePython(explicit, []);
    if (!found) {
      die(
        `PULL1SEC_PYTHON=${explicit} çalışmıyor ya da Python ${MIN_VERSION.join(".")}+ değil.`,
      );
    }
    return found;
  }
  const candidates = WINDOWS
    ? [
        ["py", ["-3"]],
        ["python", []],
        ["python3", []],
      ]
    : [
        ["python3", []],
        ["python", []],
      ];
  for (const [command, prefix] of candidates) {
    const found = usablePython(command, prefix);
    if (found) return found;
  }
  die(
    `Python ${MIN_VERSION.join(".")}+ bulunamadı. Python kurun ` +
      "(https://www.python.org/downloads/) ya da PULL1SEC_PYTHON ile yolunu belirtin.",
  );
  return null;
}

function hasCommand(command) {
  const result = spawnSync(command, ["--version"], {
    stdio: "ignore",
    windowsHide: true,
  });
  return !result.error && result.status === 0;
}

function requirementsHash() {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(REQUIREMENTS))
    .digest("hex");
}

function readStamp() {
  try {
    return fs.readFileSync(STAMP, "utf8").trim();
  } catch {
    return "";
  }
}

function venvInterpreterWorks() {
  if (!fs.existsSync(VENV_PYTHON)) return false;
  const result = spawnSync(VENV_PYTHON, ["-c", "pass"], {
    stdio: "ignore",
    windowsHide: true,
  });
  return !result.error && result.status === 0;
}

function envReady() {
  if (!fs.existsSync(VENV_PYTHON)) return false;
  const result = spawnSync(
    VENV_PYTHON,
    ["-c", "import fastapi, uvicorn, yt_dlp"],
    { stdio: "ignore", windowsHide: true },
  );
  return !result.error && result.status === 0;
}

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function acquireLock() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const started = Date.now();
  for (;;) {
    try {
      fs.mkdirSync(LOCK);
      fs.writeFileSync(path.join(LOCK, "pid"), String(process.pid));
      return;
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      let age = 0;
      try {
        age = Date.now() - fs.statSync(LOCK).mtimeMs;
      } catch {
        continue; // released between exists and stat
      }
      if (age > LOCK_STALE_MS) {
        fs.rmSync(LOCK, { recursive: true, force: true });
        continue;
      }
      if (Date.now() - started > LOCK_STALE_MS) {
        die("başka bir kurulum çok uzun sürdü; kilidi elle silin: " + LOCK);
      }
      sleep(300);
    }
  }
}

function releaseLock() {
  fs.rmSync(LOCK, { recursive: true, force: true });
}

function runStep(command, args, label) {
  console.error(`pull1sec: ${label}`);
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.error) {
    die(`${label} başlatılamadı: ${result.error.message}`);
  }
  if (result.status !== 0) {
    die(`${label} başarısız (çıkış kodu ${result.status}).`);
  }
}

function createVenv(python) {
  const uv = hasCommand("uv");
  if (uv) {
    runStep(
      "uv",
      ["venv", "--python", python.command, VENV_DIR],
      "Python ortamı hazırlanıyor (uv)",
    );
  } else {
    runStep(
      python.command,
      [...python.prefix, "-m", "venv", VENV_DIR],
      "Python ortamı hazırlanıyor",
    );
  }
  if (!fs.existsSync(VENV_PYTHON)) {
    die(
      `Python ortamı oluşturulamadı: ${VENV_DIR}. ` +
        "python3-venv paketini kurun ya da uv kullanın.",
    );
  }
}

function installRequirements() {
  if (hasCommand("uv")) {
    runStep(
      "uv",
      [
        "pip",
        "install",
        "--python",
        VENV_PYTHON,
        "--upgrade",
        "-r",
        REQUIREMENTS,
      ],
      "Bağımlılıklar kuruluyor (uv)",
    );
    return;
  }
  const pip = spawnSync(VENV_PYTHON, ["-m", "pip", "--version"], {
    stdio: "ignore",
    windowsHide: true,
  });
  if (pip.error || pip.status !== 0) {
    runStep(
      VENV_PYTHON,
      ["-m", "ensurepip", "--upgrade"],
      "pip hazırlanıyor",
    );
  }
  runStep(
    VENV_PYTHON,
    ["-m", "pip", "install", "--upgrade", "-r", REQUIREMENTS],
    "Bağımlılıklar kuruluyor",
  );
}

function ensureEnvironment() {
  if (!fs.existsSync(REQUIREMENTS)) {
    die(`requirements.txt bulunamadı: ${REQUIREMENTS}`);
  }
  const wanted = requirementsHash();
  if (readStamp() === wanted && envReady()) return;

  fs.mkdirSync(DATA_DIR, { recursive: true });
  acquireLock();
  try {
    // Another process may have finished while we waited for the lock.
    if (readStamp() === wanted && envReady()) return;

    fs.rmSync(STAMP, { force: true });

    if (!venvInterpreterWorks()) {
      // A stale environment (moved Python, OS upgrade) is rebuilt instead of
      // failing with a confusing interpreter error.
      fs.rmSync(VENV_DIR, { recursive: true, force: true });
    }
    const python = findPython();
    if (!fs.existsSync(VENV_PYTHON)) createVenv(python);
    installRequirements();

    if (!envReady()) {
      die(
        "bağımlılıklar kuruldu ama içe aktarılamadı. " +
          `Ortamı silip yeniden deneyin: rm -rf "${VENV_DIR}"`,
      );
    }
    fs.writeFileSync(STAMP, `${wanted}\n`);
  } finally {
    releaseLock();
  }
}

function main() {
  ensureEnvironment();

  const env = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH
    ? `${PKG_ROOT}${path.delimiter}${env.PYTHONPATH}`
    : PKG_ROOT;

  const child = spawn(VENV_PYTHON, ["-m", "pull1sec", ...process.argv.slice(2)], {
    stdio: "inherit",
    env,
    windowsHide: false,
  });
  child.on("error", (error) => die(`başlatılamadı: ${error.message}`));
  child.on("exit", (code, signal) => {
    if (signal) {
      try {
        process.kill(process.pid, signal);
      } catch {
        process.exit(1);
      }
      return;
    }
    process.exit(code === null ? 1 : code);
  });
}

main();

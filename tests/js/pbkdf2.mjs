/* Verify the browser PBKDF2/SHA-256 against node's crypto (and therefore
 * against Python's hashlib). Run: node tests/js/pbkdf2.mjs */
import { createHash, createHmac, pbkdf2Sync } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "..", "..", "pull1sec", "static", "auth.js"), "utf8");

// The file is written to also work as a CommonJS module; evaluate it in a sandbox.
const module_ = { exports: {} };
new Function("module", "window", source)(module_, undefined);
const lib = module_.exports;

let failures = 0;

function check(name, actual, expected) {
  const ok = actual === expected;
  if (!ok) {
    failures += 1;
    console.error(`FAIL ${name}\n  actual   ${actual}\n  expected ${expected}`);
  } else {
    console.log(`ok   ${name}  ${String(actual).slice(0, 32)}…`);
  }
}

const hex = (buffer) => Buffer.from(buffer).toString("hex");

// --- SHA-256 -----------------------------------------------------------------
for (const message of ["", "abc", "a".repeat(55), "a".repeat(56), "a".repeat(64), "a".repeat(1000)]) {
  const bytes = new TextEncoder().encode(message);
  check(
    `sha256(len=${message.length})`,
    hex(lib.sha256(bytes)),
    createHash("sha256").update(bytes).digest("hex"),
  );
}

// --- HMAC-SHA256 -------------------------------------------------------------
for (const [key, message] of [
  ["k", "message"],
  ["a".repeat(64), "message"],
  ["a".repeat(65), "message"],
  ["a".repeat(200), "x".repeat(300)],
]) {
  check(
    `hmac(key=${key.length})`,
    hex(lib.hmacSha256(new TextEncoder().encode(key), new TextEncoder().encode(message))),
    createHmac("sha256", key).update(message).digest("hex"),
  );
}

// --- PBKDF2-HMAC-SHA256 ------------------------------------------------------
const cases = [
  ["password", "73616c74", 1],
  ["password", "73616c74", 2],
  ["password", "73616c74", 4096],
  ["pāsswörd ünïcode", "00ff10ab", 1000],
  ["x".repeat(300), "aa".repeat(16), 500],
  ["supersecret1", "9f2b3c4d5e6f708192a3b4c5d6e7f809", 210000],
];

for (const [password, saltHex, iterations] of cases) {
  const salt = Buffer.from(saltHex, "hex");
  const expected = pbkdf2Sync(password, salt, iterations, 32, "sha256").toString("hex");
  const actual = hex(lib._pbkdf2(new TextEncoder().encode(password), new Uint8Array(salt), iterations));
  check(`pbkdf2(it=${iterations}, pw=${password.length})`, actual, expected);
}

// --- The two-step handshake, end to end --------------------------------------
const salt = Buffer.from("9f2b3c4d5e6f708192a3b4c5d6e7f809", "hex");
const nonce = "5f3d2c1b0a99887766554433221100ffaabbccddeeff0011";
const verifier = Buffer.from(lib._pbkdf2(new TextEncoder().encode("supersecret1"), new Uint8Array(salt), 1000));
const proof = lib._pbkdf2(new Uint8Array(verifier), lib.fromHex(nonce), 1000);
check(
  "handshake proof",
  hex(proof),
  pbkdf2Sync(verifier, Buffer.from(nonce, "hex"), 1000, 32, "sha256").toString("hex"),
);

// The verifier must never equal the proof: a captured proof is not reusable.
check("proof != verifier", String(hex(proof) !== hex(verifier)), "true");

console.log(failures === 0 ? "\nAll crypto checks passed." : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);

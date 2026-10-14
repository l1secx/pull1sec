/* Client-side PBKDF2-HMAC-SHA256 for the Pull1sec login handshake.
 *
 * Why a hand-rolled implementation: `crypto.subtle` only exists in a *secure
 * context* — HTTPS or localhost. Pull1sec is opened over plain HTTP on a LAN
 * address, where `crypto.subtle` is undefined. Native is used when available
 * and this fallback otherwise; both are verified to produce identical bytes.
 *
 * The password never leaves the browser. The server hands out a single-use
 * nonce, the client derives the stored verifier locally, mixes it with the
 * nonce and sends only that proof.
 */
(function () {
  "use strict";

  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);

  const H0 = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);

  const BLOCK = 64;
  const rotr = (value, bits) => (value >>> bits) | (value << (32 - bits));

  function sha256(bytes) {
    // Pad to a multiple of 64: 0x80, zeros, then the 64-bit big-endian bit length.
    const blocks = (bytes.length + 9 + 63) >> 6;
    const padded = new Uint8Array(blocks * BLOCK);
    padded.set(bytes);
    padded[bytes.length] = 0x80;

    const view = new DataView(padded.buffer);
    const bits = bytes.length * 8;
    view.setUint32(padded.length - 8, Math.floor(bits / 0x100000000));
    view.setUint32(padded.length - 4, bits >>> 0);

    const h = new Uint32Array(H0);
    const w = new Uint32Array(64);

    for (let offset = 0; offset < padded.length; offset += BLOCK) {
      for (let i = 0; i < 16; i += 1) w[i] = view.getUint32(offset + i * 4);
      for (let i = 16; i < 64; i += 1) {
        const x = w[i - 15];
        const y = w[i - 2];
        const s0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3);
        const s1 = rotr(y, 17) ^ rotr(y, 19) ^ (y >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }

      let a = h[0];
      let b = h[1];
      let c = h[2];
      let d = h[3];
      let e = h[4];
      let f = h[5];
      let g = h[6];
      let hh = h[7];

      for (let i = 0; i < 64; i += 1) {
        const bigS1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        const ch = (e & f) ^ (~e & g);
        const t1 = (hh + bigS1 + ch + K[i] + w[i]) >>> 0;
        const bigS0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        const maj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (bigS0 + maj) >>> 0;

        hh = g;
        g = f;
        f = e;
        e = (d + t1) >>> 0;
        d = c;
        c = b;
        b = a;
        a = (t1 + t2) >>> 0;
      }

      h[0] = (h[0] + a) >>> 0;
      h[1] = (h[1] + b) >>> 0;
      h[2] = (h[2] + c) >>> 0;
      h[3] = (h[3] + d) >>> 0;
      h[4] = (h[4] + e) >>> 0;
      h[5] = (h[5] + f) >>> 0;
      h[6] = (h[6] + g) >>> 0;
      h[7] = (h[7] + hh) >>> 0;
    }

    const out = new Uint8Array(32);
    const outView = new DataView(out.buffer);
    for (let i = 0; i < 8; i += 1) outView.setUint32(i * 4, h[i]);
    return out;
  }

  function hmacSha256(key, message) {
    let blockKey = key;
    if (blockKey.length > BLOCK) blockKey = sha256(blockKey);

    const inner = new Uint8Array(BLOCK + message.length);
    const outer = new Uint8Array(BLOCK + 32);
    for (let i = 0; i < BLOCK; i += 1) {
      const byte = i < blockKey.length ? blockKey[i] : 0;
      inner[i] = byte ^ 0x36;
      outer[i] = byte ^ 0x5c;
    }
    inner.set(message, BLOCK);
    outer.set(sha256(inner), BLOCK);
    return sha256(outer);
  }

  /** PBKDF2-HMAC-SHA256 with a 32-byte output: exactly one output block. */
  function pbkdf2(passwordBytes, saltBytes, iterations) {
    const salt = new Uint8Array(saltBytes.length + 4);
    salt.set(saltBytes);
    salt[saltBytes.length + 3] = 1; // block index 1, big-endian

    let u = hmacSha256(passwordBytes, salt);
    const result = Uint8Array.from(u);
    for (let i = 1; i < iterations; i += 1) {
      u = hmacSha256(passwordBytes, u);
      for (let j = 0; j < 32; j += 1) result[j] ^= u[j];
    }
    return result;
  }

  const encoder = new TextEncoder();

  function fromHex(hex) {
    const clean = String(hex || "").trim();
    if (clean.length % 2 !== 0) throw new Error("bad hex");
    const out = new Uint8Array(clean.length / 2);
    for (let i = 0; i < out.length; i += 1) {
      const byte = parseInt(clean.substr(i * 2, 2), 16);
      if (Number.isNaN(byte)) throw new Error("bad hex");
      out[i] = byte;
    }
    return out;
  }

  function toHex(bytes) {
    let out = "";
    for (let i = 0; i < bytes.length; i += 1) out += bytes[i].toString(16).padStart(2, "0");
    return out;
  }

  const hasSubtle = () =>
    typeof crypto !== "undefined" && crypto.subtle && typeof crypto.subtle.importKey === "function";

  async function subtleDerive(keyBytes, saltBytes, iterations) {
    const key = await crypto.subtle.importKey("raw", keyBytes, "PBKDF2", false, ["deriveBits"]);
    const bits = await crypto.subtle.deriveBits(
      { name: "PBKDF2", salt: saltBytes, iterations, hash: "SHA-256" },
      key,
      256,
    );
    return new Uint8Array(bits);
  }

  async function derive(keyBytes, saltBytes, iterations) {
    if (hasSubtle()) {
      try {
        return await subtleDerive(keyBytes, saltBytes, iterations);
      } catch (error) {
        // Fall through to the portable implementation.
      }
    }
    return pbkdf2(keyBytes, saltBytes, iterations);
  }

  const pull1secCrypto = {
    /** 1st step: password -> the verifier the server also stores. */
    deriveVerifier(password, saltHex, iterations) {
      return derive(encoder.encode(password), fromHex(saltHex), iterations);
    },
    /** 2nd step: verifier + single-use nonce -> what actually goes on the wire. */
    deriveProof(verifierBytes, nonceHex, iterations) {
      return derive(verifierBytes, fromHex(nonceHex), iterations);
    },
    sha256(bytes) {
      return sha256(bytes);
    },
    hmacSha256(key, message) {
      return hmacSha256(key, message);
    },
    toHex,
    fromHex,
    get backend() {
      return hasSubtle() ? "webcrypto" : "js";
    },
    // Exposed for the test suite.
    _pbkdf2: pbkdf2,
  };

  if (typeof window !== "undefined") window.pull1secCrypto = pull1secCrypto;
  if (typeof module !== "undefined" && module.exports) module.exports = pull1secCrypto;
})();

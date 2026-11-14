const encoder = new TextEncoder();

function toHex(buf: ArrayBuffer) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function fromHex(hex: string) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export function genSalt(len = 16) {
  return toHex(crypto.getRandomValues(new Uint8Array(len)).buffer);
}

export async function hashPassword(password: string, salt: string) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: encoder.encode(salt), iterations: 100_000, hash: "SHA-512" },
    key,
    512,
  );
  return toHex(bits);
}

export async function verifyPassword(password: string, salt: string, expectedHex: string) {
  const computed = fromHex(await hashPassword(password, salt));
  const expected = fromHex(expectedHex);
  if (computed.byteLength !== expected.byteLength) return false;
  return crypto.subtle.timingSafeEqual(computed, expected);
}

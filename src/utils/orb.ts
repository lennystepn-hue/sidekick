/**
 * Deterministic gradient identities ("orbs"): every session gets its own soft multi-hue orb
 * derived from its id, so no two look alike and the same session always looks the same.
 */
export interface OrbHues {
  h1: number;
  h2: number;
  h3: number;
  /** Where the sheen sits, so identical hue triples still differ a little. */
  sheenX: number;
  sheenY: number;
}

function fnv1a(seed: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

export function orbHues(seed: string): OrbHues {
  const h = fnv1a(seed || "sidekick");
  const h1 = h % 360;
  // second hue 45–115° away (analogous but distinct), third roughly opposite for depth
  const h2 = (h1 + 45 + ((h >>> 9) % 70)) % 360;
  const h3 = (h1 + 170 + ((h >>> 17) % 80)) % 360;
  return {
    h1,
    h2,
    h3,
    sheenX: 24 + ((h >>> 5) % 22),
    sheenY: 22 + ((h >>> 13) % 18),
  };
}

/** CSS custom properties for `Orb.vue` (and anything else that wants the same colours). */
export function orbVars(seed: string): Record<string, string> {
  const o = orbHues(seed);
  return {
    "--h1": String(o.h1),
    "--h2": String(o.h2),
    "--h3": String(o.h3),
    "--sheen-x": `${o.sheenX}%`,
    "--sheen-y": `${o.sheenY}%`,
  };
}

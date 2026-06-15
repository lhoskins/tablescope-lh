// Deterministic accent color from an entity id so colors never shift between
// renders (used for project dots, node stripes, avatars, etc.).
const ACCENTS = [
  "#185fa5", // brand blue
  "#0f6e56", // success green
  "#534ab7", // ai purple
  "#854f0b", // warning amber
  "#7d1f1a", // danger red
  "#0c447c", // brand dark
  "#5c5a55", // neutral
];

export function accentFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return ACCENTS[Math.abs(hash) % ACCENTS.length];
}

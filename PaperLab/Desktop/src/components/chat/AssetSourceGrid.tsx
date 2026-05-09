import type { AssetSourceRecord } from "../../usePaperLabStream";

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

export function AssetSourceGrid({ sources }: { sources: AssetSourceRecord[] }) {
  const dedupedSources = dedupeAssetSources(sources);
  if (dedupedSources.length === 0) return null;

  return (
    <div className="asset-grid">
      {dedupedSources.map((src) => (
        <article className="asset-card" key={src.asset_id}>
          {src.file_url ? (
            <img
              src={`${apiBase}${src.file_url}`}
              alt={src.asset_label || src.file_name || "图片证据"}
              loading="lazy"
            />
          ) : (
            <div style={{ height: 120, display: "grid", placeItems: "center", color: "var(--text-tertiary)", background: "var(--bg-subtle)" }}>
              预览不可用
            </div>
          )}
          <div className="asset-card-info">
            <strong>{src.asset_label || src.file_name || "图片证据"}</strong>
            <p>{src.summary || src.caption || "没有图片摘要"}</p>
            <small>{src.page_number ? `p.${src.page_number}` : src.asset_type || ""}</small>
          </div>
        </article>
      ))}
    </div>
  );
}

function dedupeAssetSources(sources: AssetSourceRecord[]): AssetSourceRecord[] {
  const kept: AssetSourceRecord[] = [];

  for (const source of sources) {
    const duplicateIndex = kept.findIndex((candidate) => areLikelyDuplicateAssets(candidate, source));
    if (duplicateIndex === -1) {
      kept.push(source);
      continue;
    }

    if (compareAssetPreference(source, kept[duplicateIndex]) > 0) {
      kept[duplicateIndex] = source;
    }
  }

  return kept;
}

function areLikelyDuplicateAssets(a: AssetSourceRecord, b: AssetSourceRecord): boolean {
  if (a.asset_id && b.asset_id && a.asset_id === b.asset_id) return true;
  if (a.file_url && b.file_url && a.file_url === b.file_url) return true;
  if (a.page_number !== b.page_number) return false;

  const aLabel = normalizeSemanticText(a.asset_label || a.file_name || "");
  const bLabel = normalizeSemanticText(b.asset_label || b.file_name || "");
  const aSummary = normalizeSemanticText(a.summary || a.caption || "");
  const bSummary = normalizeSemanticText(b.summary || b.caption || "");

  if (aLabel && bLabel && aLabel === bLabel) return true;
  if (!aSummary || !bSummary) return false;

  const overlap = tokenOverlap(aSummary, bSummary);
  const labelCompatibility =
    isRawAssetName(a.asset_label || a.file_name || "") || isRawAssetName(b.asset_label || b.file_name || "");

  return overlap >= 0.7 && labelCompatibility;
}

function compareAssetPreference(a: AssetSourceRecord, b: AssetSourceRecord): number {
  return assetPreferenceScore(a) - assetPreferenceScore(b);
}

function assetPreferenceScore(source: AssetSourceRecord): number {
  let score = 0;
  const label = source.asset_label || "";
  const fileName = source.file_name || "";
  if (label && !isRawAssetName(label)) score += 4;
  if (/\b(figure|fig|table)\s*\d+/i.test(label)) score += 4;
  if (source.summary) score += 2;
  if (source.caption) score += 1;
  if (fileName && !isRawAssetName(fileName)) score += 1;
  return score;
}

function isRawAssetName(value: string): boolean {
  const text = value.trim();
  if (!text) return false;
  return /^page[_-]\d+[_-]asset[_-]\d+/i.test(text) || /\.(png|jpg|jpeg|webp)$/i.test(text);
}

function normalizeSemanticText(value: string): string {
  return value
    .toLowerCase()
    .replace(/\.(png|jpg|jpeg|webp)$/g, "")
    .replace(/\b(fig(?:ure)?|table)\b/g, " ")
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function tokenOverlap(a: string, b: string): number {
  const aTokens = new Set(a.split(" ").filter(Boolean));
  const bTokens = new Set(b.split(" ").filter(Boolean));
  if (!aTokens.size || !bTokens.size) return 0;
  let shared = 0;
  for (const token of aTokens) {
    if (bTokens.has(token)) shared += 1;
  }
  return shared / Math.max(aTokens.size, bTokens.size);
}

import type { CitationRecord, AssetCitationRecord } from "../../usePaperLabStream";
import { ExternalLink } from "lucide-react";

export function CitationList({
  citations,
  assetCitations,
}: {
  citations: CitationRecord[];
  assetCitations: AssetCitationRecord[];
}) {
  if (citations.length === 0 && assetCitations.length === 0) return null;

  return (
    <div className="citation-row">
      {citations.map((c) => (
        <span className="citation-chip" key={`${c.chunk_id}-${c.locator ?? c.page ?? "src"}`}>
          <ExternalLink size={10} />
          {c.document_title} {c.locator ?? (c.page ? `p.${c.page}` : "")}
        </span>
      ))}
      {assetCitations.map((c) => (
        <span className="citation-chip" key={`${c.asset_id}-${c.locator ?? c.page ?? "asset"}`}>
          {c.label || "图片证据"} {c.locator ?? (c.page ? `p.${c.page}` : "")}
        </span>
      ))}
    </div>
  );
}

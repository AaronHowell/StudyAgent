import type { AssetSourceRecord } from "../../usePaperLabStream";

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

export function AssetSourceGrid({ sources }: { sources: AssetSourceRecord[] }) {
  if (sources.length === 0) return null;

  return (
    <div className="asset-grid">
      {sources.map((src) => (
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

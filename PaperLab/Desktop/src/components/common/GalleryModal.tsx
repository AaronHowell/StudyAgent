import { Loader } from "lucide-react";
import type { DocumentImage } from "../../types";
import { Modal } from "./Modal";

type GalleryImage = DocumentImage & { preview_url: string };

export function GalleryModal({
  open,
  onClose,
  title,
  subtitle,
  images,
  loading,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  images: GalleryImage[];
  loading: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title} subtitle={subtitle} width="1400px">
      {loading ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, padding: 40, color: "var(--text-tertiary)" }}>
          <Loader size={16} style={{ animation: "spin 1s linear infinite" }} />
          正在加载论文图片...
        </div>
      ) : images.length === 0 ? (
        <div className="empty-state" style={{ minHeight: 200 }}>
          <strong>没有提取到图片</strong>
          <p>当前论文没有可展示的图像资源。</p>
        </div>
      ) : (
        <div className="gallery-grid">
          {images.map((image) => (
            <article className="gallery-card" key={image.id}>
              {image.preview_url ? (
                <img src={image.preview_url} alt={image.asset_label || image.file_name} loading="lazy" />
              ) : (
                <div style={{ height: 200, display: "grid", placeItems: "center", color: "var(--text-tertiary)", background: "var(--bg-subtle)" }}>
                  预览不可用
                </div>
              )}
              <div className="gallery-card-info">
                <strong>{image.figure_label || image.asset_label || `第 ${image.page_number} 页`}</strong>
                <p>{image.summary || image.caption || "没有图片摘要"}</p>
                <small>{image.caption || `${image.asset_type} · 第 ${image.page_number} 页`}</small>
              </div>
            </article>
          ))}
        </div>
      )}
    </Modal>
  );
}

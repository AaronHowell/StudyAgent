import { useState, useCallback, useRef, useEffect } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Maximize,
  Loader,
} from "lucide-react";

// Use CDN worker
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

const MIN_SCALE = 0.5;
const MAX_SCALE = 3;

export function PdfViewer({ url }: { url: string }) {
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [loading, setLoading] = useState(true);
  const [containerWidth, setContainerWidth] = useState(0);
  const [scale, setScale] = useState(1);
  const [fitMode, setFitMode] = useState<"width" | "manual">("width");

  // Outer wrapper whose size is determined by CSS, not by PDF content
  const outerRef = useRef<HTMLDivElement>(null);

  const onDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setPageNumber(1);
    setLoading(false);
  }, []);

  // Observe the outer wrapper (stable size, not affected by PDF rendering)
  useEffect(() => {
    const el = outerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      const w = entries[0].contentRect.width;
      // Guard against sub-pixel noise
      setContainerWidth((prev) => (Math.abs(prev - w) > 1 ? w : prev));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Update scale when container width changes in fit-width mode
  useEffect(() => {
    if (fitMode === "width" && containerWidth > 0) {
      // Page A4 default width = 595pt, subtract padding
      const padding = 48;
      const available = containerWidth - padding;
      setScale(Math.min(MAX_SCALE, Math.max(MIN_SCALE, available / 595)));
    }
  }, [containerWidth, fitMode]);

  // Intercept Ctrl+Wheel to zoom PDF
  useEffect(() => {
    const el = outerRef.current;
    if (!el) return;

    const handleWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();

      setFitMode("manual");
      setScale((prev) => {
        const delta = e.deltaY > 0 ? -0.15 : 0.15;
        return Math.round(Math.min(MAX_SCALE, Math.max(MIN_SCALE, prev + delta)) * 100) / 100;
      });
    };

    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, []);

  const goToPage = (page: number) => {
    setPageNumber(Math.max(1, Math.min(numPages, page)));
  };

  const zoomIn = () => {
    setFitMode("manual");
    setScale((s) => Math.min(MAX_SCALE, Math.round((s + 0.2) * 100) / 100));
  };

  const zoomOut = () => {
    setFitMode("manual");
    setScale((s) => Math.max(MIN_SCALE, Math.round((s - 0.2) * 100) / 100));
  };

  const handleFitWidth = () => {
    setFitMode("width");
    if (containerWidth > 0) {
      const padding = 48;
      const available = containerWidth - padding;
      setScale(Math.min(MAX_SCALE, Math.max(MIN_SCALE, available / 595)));
    }
  };

  return (
    <div className="pdf-viewer-container">
      {/* Toolbar */}
      <div className="pdf-toolbar">
        <div className="pdf-toolbar-center">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => goToPage(pageNumber - 1)} disabled={pageNumber <= 1} title="上一页">
            <ChevronLeft size={14} />
          </button>
          <span className="pdf-page-info">
            {loading ? "--" : pageNumber} / {loading ? "--" : numPages}
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => goToPage(pageNumber + 1)} disabled={pageNumber >= numPages} title="下一页">
            <ChevronRight size={14} />
          </button>
        </div>
        <div className="pdf-toolbar-right">
          <button type="button" className="btn btn-ghost btn-sm" onClick={zoomOut} title="缩小">
            <ZoomOut size={14} />
          </button>
          <span className="pdf-zoom-label">
            {Math.round(scale * 100)}%
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={zoomIn} title="放大">
            <ZoomIn size={14} />
          </button>
          <button type="button" className={`btn btn-ghost btn-sm ${fitMode === "width" ? "active" : ""}`} onClick={handleFitWidth} title="适合宽度">
            <Maximize size={14} />
          </button>
        </div>
      </div>

      {/* Outer wrapper: observed by ResizeObserver, size controlled by CSS only */}
      <div className="pdf-content" ref={outerRef}>
        {loading ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-tertiary)" }}>
            <Loader size={16} style={{ animation: "spin 1s linear infinite" }} />
            加载中...
          </div>
        ) : null}
        <Document
          file={url}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={(error) => console.error("PDF load error:", error)}
          loading={null}
        >
          <div className="pdf-page-wrapper">
            <Page
              pageNumber={pageNumber}
              scale={scale}
              renderTextLayer={true}
              renderAnnotationLayer={true}
            />
          </div>
        </Document>
      </div>
    </div>
  );
}

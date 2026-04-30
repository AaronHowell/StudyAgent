import { useState, useCallback } from "react";
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

export function PdfViewer({ url }: { url: string }) {
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);

  const onDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setPageNumber(1);
    setLoading(false);
  }, []);

  const goToPage = (page: number) => {
    setPageNumber(Math.max(1, Math.min(numPages, page)));
  };

  const zoomIn = () => setScale((s) => Math.min(3, s + 0.2));
  const zoomOut = () => setScale((s) => Math.max(0.5, s - 0.2));
  const fitWidth = () => setScale(1.2);

  return (
    <div className="pdf-viewer-container">
      {/* Toolbar */}
      <div className="pdf-toolbar">
        <div className="pdf-toolbar-center">
          <button className="btn btn-ghost btn-sm" onClick={() => goToPage(pageNumber - 1)} disabled={pageNumber <= 1}>
            <ChevronLeft size={14} />
          </button>
          <span className="pdf-page-info">
            {loading ? "--" : pageNumber} / {loading ? "--" : numPages}
          </span>
          <button className="btn btn-ghost btn-sm" onClick={() => goToPage(pageNumber + 1)} disabled={pageNumber >= numPages}>
            <ChevronRight size={14} />
          </button>
        </div>
        <div className="pdf-toolbar-right">
          <button className="btn btn-ghost btn-sm" onClick={zoomOut} title="缩小">
            <ZoomOut size={14} />
          </button>
          <span style={{ fontSize: 12, color: "var(--text-secondary)", minWidth: 40, textAlign: "center" }}>
            {Math.round(scale * 100)}%
          </span>
          <button className="btn btn-ghost btn-sm" onClick={zoomIn} title="放大">
            <ZoomIn size={14} />
          </button>
          <button className="btn btn-ghost btn-sm" onClick={fitWidth} title="适合宽度">
            <Maximize size={14} />
          </button>
        </div>
      </div>

      {/* PDF Content */}
      <div className="pdf-content">
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

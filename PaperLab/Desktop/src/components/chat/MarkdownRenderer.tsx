import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Check, Copy } from "lucide-react";
import type { AssetSourceRecord } from "../../usePaperLabStream";

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

export function MarkdownRenderer({
  content,
  assetSources = [],
}: {
  content: string;
  assetSources?: AssetSourceRecord[];
}) {
  const segments = splitPictureReferences(content);

  return (
    <>
      {segments.map((segment, index) => {
        if (segment.type === "picture") {
          return (
            <InlinePictureReference
              key={`${segment.refId}-${index}`}
              refId={segment.refId}
              assetSources={assetSources}
            />
          );
        }
        return (
          <ReactMarkdown
            key={`text-${index}`}
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            components={{
              pre: CodeBlock,
              a: LinkRenderer,
            }}
          >
            {segment.text}
          </ReactMarkdown>
        );
      })}
    </>
  );
}

type AnswerSegment =
  | { type: "text"; text: string }
  | { type: "picture"; refId: string };

function splitPictureReferences(content: string): AnswerSegment[] {
  const pattern = /<ref\s+pic>\s*(A\d+)\s*<\/ref\s+pic>/gi;
  const segments: AnswerSegment[] = [];
  let cursor = 0;
  for (const match of content.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > cursor) {
      segments.push({ type: "text", text: content.slice(cursor, start) });
    }
    segments.push({ type: "picture", refId: match[1].toUpperCase() });
    cursor = start + match[0].length;
  }
  if (cursor < content.length) {
    segments.push({ type: "text", text: content.slice(cursor) });
  }
  return segments.length ? segments : [{ type: "text", text: content }];
}

function InlinePictureReference({
  refId,
  assetSources,
}: {
  refId: string;
  assetSources: AssetSourceRecord[];
}) {
  const source = assetSources.find((item, index) => (item.ref_id || `A${index + 1}`) === refId);
  if (!source) {
    return <span className="citation-chip">{refId}</span>;
  }

  return (
    <figure className="asset-card inline-asset-reference">
      {source.file_url ? (
        <img
          src={`${apiBase}${source.file_url}`}
          alt={source.asset_label || source.file_name || refId}
          loading="lazy"
        />
      ) : (
        <div style={{ height: 120, display: "grid", placeItems: "center", color: "var(--text-tertiary)", background: "var(--bg-subtle)" }}>
          预览不可用
        </div>
      )}
      <figcaption className="asset-card-info">
        <strong>{source.asset_label || source.file_name || refId}</strong>
        <p>{source.summary || source.caption || "没有图片摘要"}</p>
        <small>{source.page_number ? `p.${source.page_number}` : source.asset_type || ""}</small>
      </figcaption>
    </figure>
  );
}

function CodeBlock({ children, ...props }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);

  const text = extractText(children);
  const language = extractLanguage(children);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span>{language || "code"}</span>
        <button className="code-copy-btn" onClick={handleCopy}>
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <pre {...props}>{children}</pre>
    </div>
  );
}

function LinkRenderer({ href, children }: { href?: string; children?: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

function extractText(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(extractText).join("");
  if (children && typeof children === "object" && "props" in children) {
    return extractText((children as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

function extractLanguage(children: ReactNode): string {
  if (
    children &&
    typeof children === "object" &&
    "props" in children
  ) {
    const props = (children as { props: { className?: string } }).props;
    if (props.className) {
      const match = props.className.match(/language-(\w+)/);
      if (match) return match[1];
    }
  }
  return "";
}

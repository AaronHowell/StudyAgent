import { type KeyboardEvent } from "react";
import { Send, Square } from "lucide-react";

export function ChatComposer({
  value,
  onChange,
  onSend,
  onStop,
  toolsEnabled,
  onToolsEnabledChange,
  isLoading,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  toolsEnabled: boolean;
  onToolsEnabledChange: (enabled: boolean) => void;
  isLoading: boolean;
  placeholder: string;
}) {
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSend();
    }
  }

  return (
    <div className="chat-composer">
      <textarea
        className="input textarea chat-composer-input"
        rows={3}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
      />
      <div className="chat-composer-actions">
        <div className="chat-composer-left">
          <span className={`chat-status ${isLoading ? "loading" : ""}`}>
            <span className="dot" />
            {isLoading ? "生成中..." : "就绪"}
          </span>
        </div>
        <div className="chat-composer-right">
          <label className="chat-tools-toggle">
            <input
              type="checkbox"
              checked={toolsEnabled}
              onChange={(e) => onToolsEnabledChange(e.target.checked)}
            />
            工具
          </label>
          {isLoading ? (
            <button className="btn btn-sm" onClick={onStop}>
              <Square size={12} />
              停止
            </button>
          ) : null}
          <button
            className="btn btn-primary btn-sm"
            onClick={onSend}
            disabled={isLoading || !value.trim()}
          >
            <Send size={12} />
            发送
          </button>
        </div>
      </div>
    </div>
  );
}

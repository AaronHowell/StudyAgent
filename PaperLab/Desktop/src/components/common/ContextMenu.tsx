import { useEffect, type ReactNode } from "react";

type ContextMenuProps = {
  x: number;
  y: number;
  visible: boolean;
  onClose: () => void;
  children: ReactNode;
};

export function ContextMenu({ x, y, visible, onClose, children }: ContextMenuProps) {
  useEffect(() => {
    if (!visible) return;
    const handleClick = () => onClose();
    window.addEventListener("click", handleClick);
    return () => window.removeEventListener("click", handleClick);
  }, [visible, onClose]);

  if (!visible) return null;

  return (
    <div className="context-menu" style={{ left: x, top: y }} onClick={(e) => e.stopPropagation()}>
      {children}
    </div>
  );
}

export function ContextMenuItem({
  onClick,
  children,
}: {
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button className="context-menu-item" onClick={onClick}>
      {children}
    </button>
  );
}

import { FileText } from "lucide-react";

type EmptyStateProps = {
  icon?: React.ReactNode;
  title: string;
  description?: string;
};

export function EmptyState({ icon, title, description }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon || <FileText className="empty-state-icon" />}
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
    </div>
  );
}

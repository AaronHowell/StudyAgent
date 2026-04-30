export type AppModuleStatus = "planned" | "in-progress" | "ready";

export interface ModuleCard {
  name: string;
  description: string;
  status: AppModuleStatus;
}

export interface ScannedDocument {
  id: string;
  title: string;
  file_name: string;
  path: string;
  doc_type: string;
  status: string;
  ingested: boolean;
  modified_at: string;
  content_hash: string;
}

export interface DocumentImage {
  id: string;
  document_id: string;
  page_number: number;
  file_name: string;
  file_path: string;
  file_url: string;
  preview_data_url: string;
  asset_kind: string;
  asset_label: string;
  asset_index: number | null;
  figure_label: string;
  figure_index: number | null;
  caption: string;
  summary: string;
  asset_type: string;
  keywords: string[];
}

export interface ChatSessionSummary {
  session_id: string;
  title: string;
  project_id: string;
  updated_at: string;
  message_count: number;
  resume_capable: boolean;
}

export interface ReproductionTask {
  task_id: string;
  title: string;
  description: string;
  task_type: string;
  status: string;
  assigned_to?: string | null;
  blocked_by: string[];
  artifact_ids: string[];
  notes: string;
}

export interface ReproductionRun {
  run_id: string;
  project_id: string;
  objective: string;
  status: string;
  tasks: Record<string, ReproductionTask>;
  artifacts: Record<string, Record<string, unknown>>;
  workspace_path: string;
  report_path: string;
  error: string;
}

import { useEffect, useState } from "react";

type DesktopPreferences = {
  rootPath: string;
  projectId: string;
};

const storageKey = "paperlab.desktop.preferences";
const defaults: DesktopPreferences = { rootPath: "", projectId: "default-project" };

function load(): DesktopPreferences {
  if (typeof window === "undefined") return defaults;
  const raw = window.localStorage.getItem(storageKey);
  if (!raw) return defaults;
  try {
    const parsed = JSON.parse(raw) as Partial<DesktopPreferences>;
    return {
      rootPath: typeof parsed.rootPath === "string" ? parsed.rootPath : defaults.rootPath,
      projectId: typeof parsed.projectId === "string" && parsed.projectId ? parsed.projectId : defaults.projectId,
    };
  } catch {
    return defaults;
  }
}

export function usePreferences() {
  const [rootPath, setRootPath] = useState(() => load().rootPath);
  const [projectId, setProjectId] = useState(() => load().projectId);

  useEffect(() => {
    window.localStorage.setItem(storageKey, JSON.stringify({ rootPath, projectId }));
  }, [rootPath, projectId]);

  return { rootPath, projectId, setRootPath, setProjectId };
}

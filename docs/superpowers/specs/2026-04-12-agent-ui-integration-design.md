# StudyAgent Agent UI Integration Design

## Context

StudyAgent already has a usable document scanning and ingestion workflow, a React/Vite desktop frontend, and a LangGraph-backed streaming chat path built with `useStream` and `@assistant-ui/react`.

The current frontend proves the pipeline works, but the product shape is still weak:

- `SOLO` mode is only a large chat card, not a true primary workspace.
- `Document` mode mixes library, reading, and chat concerns too tightly.
- The current chat panel exposes only the minimum message flow and citation chips.
- The frontend is not yet structured to absorb richer Agent UI capabilities without growing more coupling in `App.tsx`.

This design defines a production-oriented frontend structure that keeps the current backend intact, upgrades usability immediately, and leaves clear extension points for later backend work.

## Goal

Integrate a LangChain-style Agent Chat UI into the existing StudyAgent frontend so that:

- `SOLO` becomes the default, user-facing, full-library AI workspace.
- `Document` becomes a two-level document workspace:
  - library management
  - single-paper reading with a document-scoped AI rail
- the frontend continues to use the existing backend stream and metadata contract
- the architecture is ready for later backend support for richer agent events without forcing another frontend rewrite

## Non-Goals

This design does not require:

- migrating the desktop frontend from Vite to Next.js
- replacing the current LangGraph streaming backend
- introducing new backend endpoints before the frontend refactor ships
- fabricating tool-call, trace, or thinking data that the current backend does not emit

## Product Decision

StudyAgent will not directly adopt the standalone `langchain-ai/agent-chat-ui` application shell.

Instead, the frontend will vendor and adapt the Agent Chat UI interaction model into the existing Vite application:

- preserve the current app shell, document workflows, and backend APIs
- reuse the current `useStream + assistant-ui` runtime path
- reshape the UI to follow Agent Chat UI patterns for thread layout, message flow, sources, and side panels

This gives the project the ergonomic benefits of Agent Chat UI without paying the cost of a framework migration.

## Workspace Model

### 1. SOLO Workspace

`SOLO` is the default landing page and primary user workspace.

It is a full-library AI research surface with three regions:

- left sidebar
  - new thread
  - recent threads
  - project scope
  - compact evidence summary
- main thread
  - user messages
  - assistant responses
  - inline source cues
  - composer
- right detail sidebar
  - sources
  - evidence summary
  - optional tools slot
  - optional trace slot

Important constraints:

- `SOLO` is user-facing, not a developer debugging screen.
- The main conversation is the visual focus.
- Deep detail stays in the right sidebar and must not dominate the primary experience.

### 2. Document Workspace

`Document` is a separate workspace with two levels.

#### Document Library

This page is focused on paper management:

- document table
- ingestion status
- task panel
- right-click actions
- document detail view

It does not include the full AI workspace.

#### Document Reader

This page is focused on a single paper:

- large PDF reading area in the center
- no persistent document list on the left
- collapsible document-scoped AI rail on the right

The AI rail binds the conversation context to the current paper and reuses the shared Agent UI core.

## Page Structure

The app should be refactored around the following page structure:

- `WorkspaceShell`
  - owns mode switch
  - owns top-level shared state
- `SoloPage`
  - full Agent workspace
- `DocumentLibraryPage`
  - document list and ingestion management
- `DocumentReaderPage`
  - PDF reader with document-scoped AI rail

## Component Decomposition

The frontend should split the current monolithic `App.tsx` into focused components.

Recommended structure:

- `components/workspace/WorkspaceShell.tsx`
- `components/solo/SoloPage.tsx`
- `components/document/DocumentLibraryPage.tsx`
- `components/document/DocumentReaderPage.tsx`
- `components/document/DocumentDetailsDialog.tsx`
- `components/document/FigureGalleryDialog.tsx`
- `components/agent/AgentWorkspace.tsx`
- `components/agent/AgentThread.tsx`
- `components/agent/AgentSidebar.tsx`
- `components/agent/AgentComposer.tsx`
- `components/agent/SourceList.tsx`
- `components/agent/EvidenceSummaryCard.tsx`
- `agent/agentUiAdapter.ts`
- `agent/agentScope.ts`

Responsibilities:

- `WorkspaceShell`
  - mode switch
  - `SOLO` vs `Document`
  - shared document and ingestion state
- `SoloPage`
  - assemble the full-library Agent UI layout
- `DocumentLibraryPage`
  - list, selection, context menu, ingestion tasks
- `DocumentReaderPage`
  - current paper header, PDF viewer, AI rail open/close state
- `AgentWorkspace`
  - runtime container shared by `SOLO` and `Document`
- `AgentThread`
  - message flow only
- `AgentSidebar`
  - sources and evidence details now, future agent detail slots later
- `agentUiAdapter`
  - all stream-to-UI mapping logic

## State Management

### Shared App State

The following state remains application-level:

- `mode`
- `documentView`
- `projectId`
- `rootPath`
- `documents`
- `selectedDocument`
- `taskByPath`
- `notesByDocumentId`
- gallery state

This state should move out of a single render file and into the workspace shell plus page props.

### Agent Session State

Agent session state should be separated by scope:

- one `SOLO` session store
- one document-scoped session store per `documentId`

Each session should preserve:

- thread identity
- messages
- loading/error status
- evidence summary
- current sidebar tab
- sidebar open/closed state

Reasoning:

- `SOLO` and `Document` conversations serve different jobs
- document-scoped threads must not overwrite the full-library thread
- returning to a paper should restore its latest local AI context

## Agent Scope Model

The frontend should define a single UI scope model:

```ts
type AgentScope =
  | {
      type: "solo";
      projectId: string;
    }
  | {
      type: "document";
      projectId: string;
      documentId: string;
      documentTitle: string;
      documentPath: string;
    };
```

Current backend usage:

- the backend still only requires `project_id`
- document scope is held by the frontend for UI behavior and future backend extension

This keeps the frontend honest about what the user is doing even when the backend has not yet consumed all scope fields.

## Agent UI Adapter

The adapter is the central technical decision in this design.

It should normalize the current LangGraph stream into a frontend-owned UI shape instead of letting view components read raw stream state directly.

Recommended normalized types:

```ts
type AgentUiSource = {
  documentId: string;
  documentTitle: string;
  chunkId: string;
  page?: number | null;
  locator?: string;
};

type AgentUiEvidenceSummary = {
  documentCount: number;
  chunkCount: number;
  assetCount: number;
};

type AgentUiMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  sources: AgentUiSource[];
};

type AgentUiSession = {
  messages: AgentUiMessage[];
  evidenceSummary: AgentUiEvidenceSummary;
  status: "idle" | "streaming" | "error";
  errorMessage?: string;
};
```

The current frontend should map:

- `stream.messages`
  - to normalized UI messages
- assistant message metadata citations
  - to `sources`
- `stream.values.evidence_counts`
  - to `evidenceSummary`
- `stream.isLoading`
  - to session status

Why this matters:

- later backend changes should primarily touch the adapter
- the presentation layer should stay stable as the backend grows richer
- `SOLO` and `Document` should both consume the same normalized UI contract

## Current Backend Contract Used By The Frontend

The frontend implementation must rely only on fields already present in the backend today.

### Required now

- stream messages
- assistant message citations from:
  - `response_metadata.citations`
  - or `additional_kwargs.citations`
- `evidence_counts`

### Optional future enhancements

These are not required for this frontend refactor but should have clear UI slots:

- `tool_calls`
- `trace_events`
- `thinking_blocks`
- `document_scope_ack`

The current frontend must never invent these values. Empty-state panels are acceptable.

## Interaction Design

### SOLO

- application opens into `SOLO`
- user can create a new chat without leaving the page
- user can switch recent chats
- main thread stays centered and dominant
- source references show inline in message cards and in a dedicated sidebar panel
- evidence summary is visible but compact
- future-facing panels such as `Tools` and `Trace` can exist as tabs with empty states

### Document Library

- single click selects a document
- double click enters reader mode
- right click opens context menu

Required context menu actions:

- open figure gallery
- toggle whether the document is treated as in-library from the UI perspective
- view details

`View Details` can initially be implemented as a frontend dialog using already available metadata.

Because the current backend does not expose a true de-index/remove endpoint, the first frontend iteration should treat this action as a UI/state affordance backed by existing `ingested` and re-ingest flows. A real removal path can be added later without changing the page structure.

### Document Reader

- the PDF viewer occupies the main reading surface
- the document list disappears in reader mode
- the right AI rail can expand or collapse
- the rail header clearly indicates that the conversation is bound to the current paper
- switching papers switches scope and restores that paper's session state if present

## Styling Direction

The UI should feel:

- professional
- dense
- calm
- optimized for research reading and productivity

This means:

- no playful chat-app aesthetics
- no oversized empty space
- restrained color use
- readable but compact typography
- strong surface hierarchy between navigation, content, and detail panels

`SOLO` should look like a serious research console, not a demo playground.

## Migration Plan

The implementation should proceed incrementally:

1. extract workspace shell and page boundaries from `App.tsx`
2. move current library behavior into `DocumentLibraryPage`
3. move current reader behavior into `DocumentReaderPage`
4. replace current `SOLO` card layout with a full Agent workspace layout
5. introduce the shared `AgentWorkspace` and adapter
6. map existing citations and evidence counts into the new sources/evidence surfaces
7. add empty-state tabs for future tools/trace support

## Risks

### Risk: over-coupling to today’s backend metadata shape

Mitigation:

- isolate metadata parsing in the adapter

### Risk: over-importing assumptions from the standalone Agent Chat UI app

Mitigation:

- copy interaction patterns, not the full app shell
- keep Vite app ownership intact

### Risk: `Document` reader becomes cramped

Mitigation:

- remove the document list from reader mode
- keep the AI rail collapsible

## Outcome

After this refactor, StudyAgent should behave like a coherent product with two clear AI surfaces:

- `SOLO`: the default full-library AI research workspace
- `Document Reader`: a focused paper-reading workspace with document-scoped AI assistance

Both surfaces share one Agent UI core, consume the current backend without protocol changes, and are ready for later backend enrichment through a single adapter layer.

# Agent UI Backend Reference

## Purpose

This document describes the frontend expectations for the Agent UI integration after the April 12, 2026 design pass.

It is written for future backend work. The frontend refactor described here does not require backend changes to ship, but this document captures the fields and behaviors that will make later integration cleaner.

## Current Frontend Dependency Surface

The frontend currently depends on the following backend outputs only:

### LangGraph stream

- `messages`
- `values.evidence_counts`

### Assistant message metadata

The frontend reads citations from either:

- `response_metadata.citations`
- `additional_kwargs.citations`

Each citation is expected to carry:

- `document_id`
- `document_title`
- `chunk_id`
- optional `page`
- optional `locator`

### Current evidence summary

The frontend expects:

```json
{
  "document_count": 0,
  "chunk_count": 0,
  "asset_count": 0
}
```

This is enough to support:

- message thread rendering
- source chips and source sidebars
- evidence summary cards

## Frontend Scope Model

The frontend now distinguishes two agent scopes.

### SOLO scope

Full-library chat:

```json
{
  "type": "solo",
  "projectId": "frontend-project"
}
```

### Document scope

Single-paper chat while reading:

```json
{
  "type": "document",
  "projectId": "frontend-project",
  "documentId": "doc-123",
  "documentTitle": "Paper Title",
  "documentPath": "C:\\\\papers\\\\paper.pdf"
}
```

The current backend only needs `project_id`.

The additional document fields are frontend-held context for now, but the backend may later choose to consume them for scope-aware retrieval or UI acknowledgements.

## Recommended Optional Future Fields

These fields are not required for the current frontend refactor, but the UI has dedicated extension points for them.

## Document Library Inclusion Toggle

The `Document Library` UI includes a right-click action for toggling whether a paper is treated as in-library.

For the current frontend release, this does not require a new backend endpoint. The UI can derive its first behavior from existing fields such as:

- `ingested`
- current task state
- re-ingest actions

If a later backend release adds a real de-index or exclude operation, that capability can be wired into the same UI affordance without changing the workspace structure.

### 1. `document_scope_ack`

Purpose:

- confirm that the backend recognized and applied the current document scope

Suggested shape:

```json
{
  "document_scope_ack": {
    "document_id": "doc-123",
    "document_title": "Paper Title"
  }
}
```

Potential UI use:

- show a stronger scope confirmation badge in the Document Reader AI rail

### 2. `tool_calls`

Purpose:

- support a proper Agent UI tools panel

Suggested shape:

```json
{
  "tool_calls": [
    {
      "id": "tool-1",
      "name": "retrieve_evidence",
      "status": "completed",
      "input_summary": "query=...",
      "output_summary": "8 chunks, 2 assets",
      "duration_ms": 132
    }
  ]
}
```

Potential UI use:

- populate `Tools` tab in both `SOLO` and `Document`

### 3. `trace_events`

Purpose:

- support timeline-style agent step inspection

Suggested shape:

```json
{
  "trace_events": [
    {
      "id": "trace-1",
      "stage": "retrieve_evidence",
      "status": "completed",
      "summary": "retrieved evidence pack",
      "timestamp": "2026-04-12T20:15:00Z"
    }
  ]
}
```

Potential UI use:

- populate `Trace` tab in the right sidebar

### 4. `thinking_blocks`

Purpose:

- enable an optional model-reasoning display area when appropriate

Suggested shape:

```json
{
  "thinking_blocks": [
    {
      "id": "think-1",
      "label": "Reasoning",
      "content": "..."
    }
  ]
}
```

Important note:

- the frontend should not require this
- if omitted, the UI should simply hide or empty-state that surface

## Recommended Stability Rule

If metadata locations change, the backend should preserve one stable frontend-facing adapter target.

Current frontend parsing logic already checks:

- `response_metadata.citations`
- `additional_kwargs.citations`

For future features, prefer consistency over perfect placement. Stable fields matter more than theoretical purity once the frontend begins relying on them.

## Source Rendering Semantics

The frontend treats a source as a paper-grounded citation, not a generic web reference.

The UI currently expects each source item to be renderable as:

- document title
- optional locator
- optional page

If future source payloads get richer, preserve these minimum rendering fields.

## Summary

The frontend is intentionally being upgraded ahead of richer backend agent events.

To support the current UI, the backend only needs to keep emitting:

- messages
- citations
- evidence counts

To support the next level of Agent UI richness later, the most valuable additions are:

1. `document_scope_ack`
2. `tool_calls`
3. `trace_events`

Those three additions would unlock most of the remaining right-sidebar surfaces without requiring another major frontend architecture change.

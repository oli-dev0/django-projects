# Projects decisions

- Keep Project data and media ownership in `apps.projects`; keep the bundled
  public-facing HTML, CSS, JavaScript, fonts, and icons in the separate
  `site_frontend` app so consumers can use or replace the presentation layer.
- Keep Projects English-only with unprefixed canonical URLs.
- Use a fixed Project category enum and category landing pages rather than a
  user-managed taxonomy; reserve category values as Project slugs so routing
  remains unambiguous. Existing rows default to `apps` in migration `0004` and
  are manually reclassified in Admin afterward.
- Use Project-owned uploads and UUID storage paths instead of remote cover URLs.
- Process images synchronously because uploads are an infrequent Admin action;
  add a queue only if measured usage requires it.
- Store technology selections as validated registry keys so editorial choices
  remain simple and public ordering stays deterministic.
- Keep the public Projects filter controls server-rendered and GET-based, with
  JavaScript submitting category and technology changes immediately. This keeps
  the URL canonical and shareable while avoiding redundant Apply/Cancel actions;
  responsive layout and theme presentation remain owned by the frontend.
- Namespace bundled static assets under `site_frontend/` and keep stylesheet
  dependencies relative so Django static-finder ordering and custom static URL
  prefixes do not change which files the reference frontend loads.
- Render enhancement-only theme and filter buttons hidden, then reveal them
  only after JavaScript initializes. Server-rendered search and filter inputs
  remain available when scripts do not run.
- Sanitize Markdown once in the presentation boundary and never trust raw
  editor input in templates.
- Enforce featured publication and uniqueness in the database, with a locked
  confirmation service for editor-visible transitions.
- Preserve native links and `<details>` before enhancing dialogs so content
  remains available without successful JavaScript initialization.
- Keep Project gallery ordering controls in `apps.projects`: use small
  keyboard-accessible up/down buttons backed by hidden positions, and normalize
  every retained row during save so the database uniqueness constraint remains
  authoritative.
- Keep one shared Project order across drafts and published records so
  publication does not move content. Replace direct numeric editing with one
  complete-order Admin page, append new Projects last, and close gaps after
  Admin deletion.
- Treat Project ordering as a single-editor workflow. Keep the lightweight
  stale-page guard for ordinary add/delete changes rather than adding a global
  ordering mutex for simultaneous Admin writes.

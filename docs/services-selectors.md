# Projects services and selectors

`apps.projects.image_services` validates image bytes, normalizes orientation,
generates all renditions, preserves a ready image during failed replacement,
and schedules old-file cleanup after commit. Failed initial records remain
visible and retryable; retries process the new upload without persisting an
unreferenced intermediate file.

`apps.projects.services` owns the shared Project order:

- `get_projects_in_order` returns published Projects and drafts in editorial
  order for the Admin page.
- `append_project` normalizes existing positions and saves a new Project last.
- `normalize_project_order` closes gaps while preserving the established order.
- `reorder_projects` validates complete, unique positive IDs, compares the
  editor snapshot with the current Project list, and returns updated, invalid,
  or stale state.

The same module owns featured-state transitions:

- `set_featured_project` locks relevant rows, rejects drafts, compares the
  expected current Project, and returns featured, stale, or unpublished state.
- `unfeature_project` removes a Project from the homepage.
- `unpublish_project` clears publication and featured state atomically.

`apps.projects.selectors` owns published list/detail reads, optional category
filtering for published lists, the valid featured read, and the Admin-gated
saved preview read. Detail and preview selectors eager-load cover and ordered
gallery relationships. Published list reads retain the shared editorial order
while filtering out drafts; category lists add an exact fixed-choice filter.

`apps.projects.rendering` owns responsive media data, unavailable-media state,
technology presentation, sanitized feature HTML, social-image metadata, and
escaped `CreativeWork`/breadcrumb JSON-LD shared by public detail and preview.

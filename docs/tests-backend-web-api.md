# Projects backend and web tests

Focused coverage is represented by the included `tests/` directory:

- `test_models.py`: category choices and validation, ownership, ordering,
  deletion, and constraints.
- `test_migrations.py`: category backfill for existing Projects and the lack of
  a runtime model default after migration.
- `test_image_services.py`: formats, limits, orientation, renditions, storage
  failures, retry cleanup, replacement, readiness, and committed deletion.
- `test_admin.py`: forms, media choices, permissions, replacement, single and
  bulk deletion, previews, featured confirmation, stale state, CSRF,
  unpublishing, gallery add-all behavior, Project reorder rendering and writes,
  direct numeric-order removal, append behavior, partial gallery reordering,
  and position normalization after deletion.
- `test_services.py`: complete Project reordering, invalid and stale snapshots,
  append and normalization behavior, database rollback, feature, replace,
  unpublish, and conflict outcomes.
- `test_selectors.py`: publication visibility, category filtering, featured
  reads, eager loading, preview reads, shared Project order, draft filtering,
  and gallery order.
- `test_rendering.py`: Markdown sanitization, technology ordering, media
  availability, real `srcset` widths, gallery teaser `sizes`, social URLs, and
  JSON-LD escaping.
- `test_views.py`: public visibility, category metadata and filtering, canonical
  search/technology query state, active-filter removal links, English category
  copy, category prompt navigation, technology icon and tooltip rendering on
  the main and category lists, filter-control markup order and status,
  immediate-filter UI contract (no Apply/Cancel actions), media states, native
  gallery fallback, rendered feature HTML, absolute list social-image metadata,
  preview headers, and permissions.
- `test_reference_frontend_assets.py`: required reference templates and scripts,
  namespaced icon availability, relative stylesheet dependencies,
  enhancement-only control fallbacks, and gallery navigation source behavior.
- `test_sitemaps.py`: canonical published entries, populated category entries,
  duplicate-category prevention, and draft exclusion.

The omitted host project should separately cover homepage placement, template
integration, root routing, and site-registry behavior.

Run the related suite with:

```bash
DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py test tests.projects
```

The focused filter/view checks can be run with:

```bash
DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py test tests.projects.test_views tests.projects.test_filters
```

The standalone reference-frontend checks do not require host Django settings:

```bash
python3 -m unittest tests.test_reference_frontend_assets
```

The suite uses Django's configured test database and temporary media roots.
Simultaneous Project ordering writes are outside the single-editor product
assumption. Browser drag behavior, filter auto-submit and dropdown restoration,
enhancement-control reveal behavior, responsive layout, light/dark filter
surfaces, and dialog behavior remain manual or environment-specific
verification boundaries.

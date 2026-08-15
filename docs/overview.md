# Projects

The `apps.projects` app owns portfolio content, project media, editorial
validation, previews, and featured-project state. A host-owned frontend app
provides the public templates, styling, and progressive enhancement.

## Current surface

- Public list: `/projects/`.
- Public category lists: `/projects/<category>/` for the fixed Project
  categories.
- Public list search and filters: normalized text search, fixed category
  selection, and registry-backed technology filters.
- Public detail: `/projects/<slug>/`.
- Admin models: Projects and Project images.
- Public content: published Projects only.
- Preview: saved Projects through a permission-protected Admin action.
- Homepage: the one valid published featured Project, or no featured section.
- Language: English-only, with unprefixed canonical URLs.

Editors can upload Project-owned images, select a cover, order a gallery,
choose technologies, write sanitized Markdown body and feature content, preview
the saved result, explicitly confirm featured-project changes, and manage the
shared public Project order from a dedicated Admin page. Each Project has one
fixed category, managed in Admin and exposed through a published-only category
list. Project images can also be bulk-deleted from the Admin list; the action
detaches their cover and gallery uses before cleanup. Image processing is
synchronous and uses the configured Django media storage.

The public list keeps search and filter controls above the results. Category
and technology changes apply immediately through a host-provided JavaScript
enhancement, and active values can be removed individually or cleared together.
The server-rendered forms and links remain the authoritative fallback.

The host frontend can also enhance multi-image detail galleries with a dialog.
Visitors can use the compact controls, Left and Right keyboard keys, or
horizontal touch swipes to move between images, while the native links remain
available without JavaScript.

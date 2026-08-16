# Projects

The `apps.projects` app owns portfolio content, project media, editorial
validation, previews, and featured-project state. The included
`site_frontend` app provides a reference implementation of the public
templates, styling, static assets, and progressive enhancement. A consuming
site can use it directly or replace it with its own frontend.

## Current surface

- Public list: `/projects/`.
- Public category lists: `/projects/<category>/` for the fixed Project
  categories.
- Public list search and filters: normalized text search, an All-first category
  navigation bar, and registry-backed technology filters.
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

The public list keeps a compact Filters and Tech stack row above a constrained
search field, followed by an All-first category navigation bar. Technology
changes apply immediately through the included JavaScript enhancement, while
category links preserve the current search and technology query state. The
server-rendered forms and links remain the authoritative fallback. Controls
that only work with JavaScript stay hidden until their scripts initialize.

The reference frontend can also enhance multi-image detail galleries with a dialog.
Visitors can use the compact controls, Left and Right keyboard keys, or
horizontal touch swipes to move between images, while the native links remain
available without JavaScript.

Frontend fonts and icons use the `site_frontend/` static namespace. References
inside the stylesheet are relative, so a host can use a non-default static URL
or asset domain. Public list pages emit absolute canonical and social-image
URLs; detail pages use their Project-specific social metadata.

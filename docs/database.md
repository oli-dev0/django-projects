# Projects database

## Models

`Project` stores English title, slug, fixed category, summary, body, SEO fields,
publication and featured state, ordering, links, gallery caption, technology
keys, Markdown feature source, and timestamps. Its optional cover is a `SET_NULL` foreign key
to `ProjectImage`. `sort_order` is a shared editorial order across published
Projects and drafts. Admin creation appends to that order; reordering and Admin
deletion normalize it to contiguous zero-based positions.

`ProjectImage` belongs to one Project and stores its editorial name,
alternative-text state, source dimensions, processing status/error, creator,
timestamps, original file, three WebP display renditions, and one social JPEG.
Deleting a Project cascades to its images. File cleanup is scheduled after the
database transaction commits.

`ProjectGalleryImage` joins a Project to one of its ready owned images with a
non-negative position. Rows are ordered by position and primary key.

## Constraints and indexes

- Project slugs are unique.
- `category` is required and must be one of `apps`, `themes`, `publishing`,
  `features`, or `operations`.
- Project slugs cannot equal a category URL segment, so category routes cannot
  shadow detail routes.
- At most one Project can have `is_featured=True`.
- A featured Project must also be published.
- A gallery cannot reuse an image or position within the same Project.
- The publication/featured/order index supports public and homepage reads.
- The publication/category/order index supports category list reads.

Project positions are not database-unique. Ordering mutations lock the current
Project rows and are intended for the single-editor Admin workflow; simultaneous
ordering writes are not supported.

Migration `0003_project_full_feature_list_project_gallery_caption_and_more.py`
adds the managed-media schema, gallery relationship, editorial fields, and
featured constraints. The schema replacement intentionally has no legacy
media backfill because the target Projects datasets were confirmed empty when
it was introduced.

Migration `0004_project_category_project_projects_pub_cat_order_idx_and_more.py`
adds the required category field, category index, and category/slug constraints.
Existing Projects receive `apps` during migration so the schema remains
non-null; editors can then reclassify them manually in Admin.

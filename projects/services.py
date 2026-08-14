from enum import StrEnum

from django.db import IntegrityError, transaction
from django.db.models import Q

from .models import Project


class FeaturedProjectOutcome(StrEnum):
    FEATURED = 'featured'
    STALE = 'stale'
    UNPUBLISHED = 'unpublished'


class ProjectOrderOutcome(StrEnum):
    UPDATED = 'updated'
    INVALID = 'invalid'
    STALE = 'stale'


def _projects_in_public_order(*, lock=False):
    queryset = Project.objects.all()
    if lock:
        queryset = queryset.select_for_update()
    return list(queryset.order_by('sort_order', '-created_at', 'pk'))


def get_projects_in_order():
    """Return every Project in the authoritative shared ordering."""
    return _projects_in_public_order()


def _parse_project_ids(values):
    if values is None or isinstance(values, (str, bytes)):
        return None
    try:
        values = iter(values)
    except TypeError:
        return None
    parsed_ids = []
    for value in values:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            project_id = value
        elif isinstance(value, str):
            try:
                project_id = int(value)
            except ValueError:
                return None
        else:
            return None
        if project_id <= 0:
            return None
        parsed_ids.append(project_id)
    if len(parsed_ids) != len(set(parsed_ids)):
        return None
    return parsed_ids


def _save_contiguous_positions(projects):
    changed_projects = []
    for position, project in enumerate(projects):
        if project.sort_order != position:
            project.sort_order = position
            changed_projects.append(project)
    if changed_projects:
        Project.objects.bulk_update(changed_projects, ('sort_order',))


@transaction.atomic
def normalize_project_order():
    """Close gaps while preserving the current public Project order."""
    projects = _projects_in_public_order(lock=True)
    _save_contiguous_positions(projects)
    return projects


@transaction.atomic
def append_project(project):
    """Save a new Project at the end of the normalized shared order."""
    if project.pk:
        raise ValueError('An unsaved Project is required.')

    projects = _projects_in_public_order(lock=True)
    _save_contiguous_positions(projects)
    project.sort_order = len(projects)
    project.save()
    return project


@transaction.atomic
def reorder_projects(ordered_ids, expected_ids):
    """Persist a complete Project order if the editor snapshot is current."""
    submitted_order = _parse_project_ids(ordered_ids)
    expected_order = _parse_project_ids(expected_ids)
    if submitted_order is None or expected_order is None:
        return ProjectOrderOutcome.INVALID

    projects = _projects_in_public_order(lock=True)
    current_ids = [project.pk for project in projects]
    if expected_order != current_ids:
        return ProjectOrderOutcome.STALE
    if len(submitted_order) != len(current_ids) or set(submitted_order) != set(current_ids):
        return ProjectOrderOutcome.INVALID

    projects_by_id = {project.pk: project for project in projects}
    _save_contiguous_positions([projects_by_id[project_id] for project_id in submitted_order])
    return ProjectOrderOutcome.UPDATED


@transaction.atomic
def set_featured_project(project, expected_current_id=None):
    """Feature a published Project if the confirmation is still current."""
    if not project.pk:
        raise ValueError('A saved Project is required.')

    locked_projects = list(
        Project.objects.select_for_update()
        .filter(Q(is_featured=True) | Q(pk=project.pk))
        .order_by('pk')
    )
    locked_by_id = {locked_project.pk: locked_project for locked_project in locked_projects}
    proposed = locked_by_id.get(project.pk)
    if proposed is None:
        raise Project.DoesNotExist

    current_projects = [locked_project for locked_project in locked_projects if locked_project.is_featured]
    current_id = current_projects[0].pk if current_projects else None
    if current_id != expected_current_id:
        return FeaturedProjectOutcome.STALE
    if not proposed.is_published:
        return FeaturedProjectOutcome.UNPUBLISHED
    if current_id == proposed.pk:
        return FeaturedProjectOutcome.FEATURED

    try:
        with transaction.atomic():
            Project.objects.filter(is_featured=True).update(is_featured=False)
            Project.objects.filter(pk=proposed.pk).update(is_featured=True)
    except IntegrityError:
        # A competing first selection may win between the snapshot and the
        # uniqueness check. Its committed row is the new confirmation state.
        return FeaturedProjectOutcome.STALE
    return FeaturedProjectOutcome.FEATURED


@transaction.atomic
def unfeature_project(project):
    """Remove a Project from the homepage without changing publication."""
    locked_project = Project.objects.select_for_update().get(pk=project.pk)
    if locked_project.is_featured:
        locked_project.is_featured = False
        locked_project.save(update_fields=['is_featured', 'updated_at'])
    return locked_project


@transaction.atomic
def unpublish_project(project):
    """Unpublish a Project and clear its featured state atomically."""
    locked_project = Project.objects.select_for_update().get(pk=project.pk)
    locked_project.is_published = False
    locked_project.is_featured = False
    locked_project.save(update_fields=['is_published', 'is_featured', 'updated_at'])
    return locked_project

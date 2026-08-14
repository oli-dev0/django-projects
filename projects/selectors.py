from django.db.models import (
    Case,
    IntegerField,
    Prefetch,
    Q,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Cast
from django.shortcuts import get_object_or_404

from .filters import ProjectFilterOption, ProjectFilterOptions
from .models import Project, ProjectGalleryImage
from .technologies import TECHNOLOGY_REGISTRY, TECHNOLOGY_KEYS


def _with_presentation_relations(queryset):
    gallery_items = ProjectGalleryImage.objects.select_related('image').order_by('position', 'pk')
    return queryset.select_related('cover_image').prefetch_related(
        Prefetch('gallery_items', queryset=gallery_items),
    )


def _compact_search_text(value):
    return ''.join(character for character in value.casefold() if character.isalnum())


def _search_terms(search_query):
    terms = []
    seen = set()
    for term in (search_query or '').split():
        normalized = term.casefold()
        if normalized not in seen:
            terms.append(term)
            seen.add(normalized)
    return tuple(terms)


def _technology_keys_for_search_term(term):
    compact_term = _compact_search_text(term)
    if not compact_term:
        return ()
    return tuple(
        technology.key
        for technology in TECHNOLOGY_REGISTRY
        if compact_term in _compact_search_text(technology.key)
        or compact_term in _compact_search_text(technology.label)
    )


def _technology_match_query(keys):
    if not keys:
        return None
    query = Q()
    for key in keys:
        query |= Q(technology_stack_text__icontains=f'"{key}"')
    return query


def _term_query(term):
    query = (
        Q(title__icontains=term)
        | Q(summary__icontains=term)
        | Q(body__icontains=term)
    )
    technology_query = _technology_match_query(
        _technology_keys_for_search_term(term),
    )
    if technology_query is not None:
        query |= technology_query
    return query


def _match_count(conditions):
    expression = Value(0, output_field=IntegerField())
    for condition in conditions:
        expression += Case(
            When(condition, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    return expression


def _technology_text_annotation(queryset):
    # Text-casting the JSON array keeps exact quoted-key matching portable
    # across SQLite and PostgreSQL.
    return queryset.annotate(
        technology_stack_text=Cast('technology_stack', TextField()),
    )


def get_published_projects(*, category=None, filters=None, filter_state=None):
    queryset = Project.objects.filter(is_published=True)
    if filters is not None and filter_state is not None:
        raise TypeError('Pass only one project filter state.')
    state = filters if filters is not None else filter_state

    selected_category = category
    selected_technologies = ()
    search_query = None
    if state is not None:
        if state.category in Project.Category.values:
            selected_category = state.category
        selected_technologies = tuple(
            key for key in TECHNOLOGY_KEYS if key in state.technology_keys
        )
        search_query = state.search_query

    if selected_category is not None:
        queryset = queryset.filter(category=selected_category)

    if selected_technologies or search_query:
        queryset = _technology_text_annotation(queryset)

    # Each quoted JSON membership predicate intentionally combines with AND semantics.
    for technology_key in selected_technologies:
        queryset = queryset.filter(
            technology_stack_text__icontains=f'"{technology_key}"',
        )

    terms = _search_terms(search_query)
    if terms:
        for term in terms:
            queryset = queryset.filter(_term_query(term))

        title_conditions = [Q(title__icontains=term) for term in terms]
        content_conditions = [
            Q(summary__icontains=term) | Q(body__icontains=term)
            for term in terms
        ]
        technology_conditions = [
            technology_query
            for technology_query in (
                _technology_match_query(_technology_keys_for_search_term(term))
                for term in terms
            )
            if technology_query is not None
        ]
        queryset = queryset.annotate(
            title_match_count=_match_count(title_conditions),
            content_match_count=_match_count(content_conditions),
            technology_match_count=_match_count(technology_conditions),
        ).order_by(
            '-title_match_count',
            '-content_match_count',
            '-technology_match_count',
            'sort_order',
            '-created_at',
            'pk',
        )
    else:
        queryset = queryset.order_by('sort_order', '-created_at')

    return queryset.select_related('cover_image')


def get_public_project_filter_options():
    used_technology_keys = set()
    for technology_stack in Project.objects.filter(
        is_published=True,
    ).values_list('technology_stack', flat=True):
        if isinstance(technology_stack, (list, tuple)):
            used_technology_keys.update(technology_stack)

    return ProjectFilterOptions(
        categories=tuple(
            ProjectFilterOption(value, label)
            for value, label in Project.Category.choices
        ),
        technologies=tuple(
            ProjectFilterOption(technology.key, technology.label)
            for technology in TECHNOLOGY_REGISTRY
            if technology.key in used_technology_keys
        ),
    )


def get_project_by_slug(slug):
    return get_object_or_404(
        _with_presentation_relations(Project.objects.filter(is_published=True)),
        slug=slug,
    )


def get_featured_project():
    return (
        _with_presentation_relations(
            Project.objects.filter(is_published=True, is_featured=True),
        )
        .order_by('pk')
        .first()
    )


def get_project_for_preview(project_id):
    return get_object_or_404(
        _with_presentation_relations(Project.objects.all()),
        pk=project_id,
    )

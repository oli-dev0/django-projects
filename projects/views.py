from dataclasses import replace

from django.urls import reverse
from django.shortcuts import redirect, render
from django.templatetags.static import static

from apps.core.sites import PRIMARY_SITE, build_site_absolute_url

from .filters import (
    CATEGORY_PARAMETER,
    SEARCH_PARAMETER,
    TECHNOLOGY_PARAMETER,
    ProjectFilterState,
    active_filters,
    parse_filter_state,
    serialize_filter_state,
)
from .models import Project
from .rendering import build_project_presentation, build_technology_data
from .selectors import (
    get_project_by_slug,
    get_public_project_filter_options,
    get_published_projects,
)


CATEGORY_DESCRIPTIONS = {
    Project.Category.APPS: 'Applications built to solve practical problems.',
    Project.Category.THEMES: 'Themes built for clear, maintainable interfaces.',
    Project.Category.PUBLISHING: 'Publishing systems and editorial tools.',
    Project.Category.FEATURES: 'Focused product features and integrations.',
    Project.Category.OPERATIONS: 'Infrastructure and operational tooling.',
}


def _project_context(request, project, *, preview=False):
    canonical_url = build_site_absolute_url(
        PRIMARY_SITE,
        reverse('personal:project-detail', kwargs={'slug': project.slug}),
    )
    presentation = build_project_presentation(
        project,
        canonical_url=canonical_url,
        fallback_social_image_url=build_site_absolute_url(
            PRIMARY_SITE,
            static('site_frontend/img/social-card.png'),
        ),
    )
    return {
        'project': project,
        'project_presentation': presentation,
        'is_preview': preview,
        'seo_canonical_url': canonical_url,
    }


def _project_list_path(category=None):
    if category:
        return reverse('personal:projects-category', kwargs={'category': category})
    return reverse('personal:projects')


def _project_list_url(state):
    path = _project_list_path(state.category)
    query_string = serialize_filter_state(state)
    return f'{path}?{query_string}' if query_string else path


def _resolved_category(request, parsed_state, route_category):
    category_values = request.GET.getlist(CATEGORY_PARAMETER)
    if parsed_state.category:
        return parsed_state.category
    if category_values and '' in category_values:
        return None
    return route_category


def _project_list_response(
    request,
    *,
    route_category,
    page_title,
    page_description,
    page_lede,
    prompt_path,
    empty_message,
):
    filter_options = get_public_project_filter_options()
    parsed_state = parse_filter_state(request.GET, filter_options)
    state = replace(
        parsed_state,
        category=_resolved_category(request, parsed_state, route_category),
    )
    canonical_path = _project_list_path(state.category)
    canonical_query = serialize_filter_state(state)
    if request.path != canonical_path or request.GET.urlencode() != canonical_query:
        target = f'{canonical_path}?{canonical_query}' if canonical_query else canonical_path
        return redirect(target)

    projects = list(get_published_projects(filters=state))
    for project in projects:
        project.public_technologies = build_technology_data(project)

    active_filter_context = []
    for active_filter in active_filters(state, filter_options):
        active_filter_context.append(
            {
                'dimension': active_filter.dimension_label,
                'value': active_filter.value_label,
                'url': _project_list_url(
                    state.without(active_filter.dimension, active_filter.value),
                ),
                'remove_label': (
                    f'Remove {active_filter.dimension_label}: '
                    f'{active_filter.value_label}'
                ),
            }
        )

    clean_path = _project_list_path(route_category)
    query_filtered = bool(state.search_query or state.technology_keys)
    selected_category_label = next(
        (
            option.label
            for option in filter_options.categories
            if option.value == state.category
        ),
        'Any category',
    )
    context = {
        'projects': projects,
        'category': route_category,
        'page_title': page_title,
        'page_description': page_description,
        'page_lede': page_lede,
        'prompt_path': prompt_path,
        'empty_message': empty_message,
        'has_projects': bool(projects),
        'filter_options': filter_options,
        'filter_state': state,
        'selected_category_label': selected_category_label,
        'filter_active': state.is_active,
        'filter_active_count': state.active_value_count,
        'active_filters': active_filter_context,
        'filter_form_action': clean_path,
        'search_form_action': clean_path,
        'current_filter_url': _project_list_url(state),
        'clear_filters_url': _project_list_url(ProjectFilterState()),
        'clear_search_url': _project_list_url(state.without(SEARCH_PARAMETER)),
        'clear_technologies_url': _project_list_url(
            state.without(TECHNOLOGY_PARAMETER),
        ),
        'query_filtered': query_filtered,
        'results_status': (
            'Filtered projects loaded.' if state.is_active else 'Projects loaded.'
        ),
        'seo_canonical_url': build_site_absolute_url(PRIMARY_SITE, clean_path),
    }
    response = render(
        request,
        'site_frontend/projects/list.html',
        context,
    )
    if query_filtered:
        response['X-Robots-Tag'] = 'noindex, follow'
    response['Content-Language'] = 'en'
    return response


def project_list(request):
    return _project_list_response(
        request,
        route_category=None,
        page_title='Projects',
        page_description='Published web, mobile, and infrastructure project examples.',
        page_lede='Products and tools built to be useful, maintainable, and durable.',
        prompt_path='projects/',
        empty_message='No published projects yet.',
    )


def project_category(request, category):
    category_label = Project.Category(category).label
    return _project_list_response(
        request,
        route_category=category,
        page_title=f'{category_label} projects',
        page_description=CATEGORY_DESCRIPTIONS[category],
        page_lede=CATEGORY_DESCRIPTIONS[category],
        prompt_path=f'projects/{category}/',
        empty_message=f'No published {category_label.lower()} projects yet.',
    )


def project_detail(request, slug):
    project = get_project_by_slug(slug)
    return render(
        request,
        'site_frontend/projects/detail.html',
        _project_context(request, project),
    )

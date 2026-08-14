from dataclasses import dataclass, replace
from urllib.parse import urlencode

CATEGORY_PARAMETER = 'category'
SEARCH_PARAMETER = 'q'
TECHNOLOGY_PARAMETER = 'tech'
TECH_PARAMETER = TECHNOLOGY_PARAMETER
SEARCH_MAX_LENGTH = 200
SEARCH_MAX_TERMS = 10


@dataclass(frozen=True, slots=True)
class ProjectFilterOption:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class ProjectFilterOptions:
    categories: tuple[ProjectFilterOption, ...]
    technologies: tuple[ProjectFilterOption, ...]

    @property
    def category_values(self):
        return frozenset(option.value for option in self.categories)

    @property
    def technology_values(self):
        return frozenset(option.value for option in self.technologies)


@dataclass(frozen=True, slots=True)
class ProjectFilterState:
    search_query: str | None = None
    category: str | None = None
    technology_keys: tuple[str, ...] = ()

    @property
    def has_filters(self):
        return bool(self.category or self.technology_keys)

    @property
    def active_value_count(self):
        return bool(self.search_query) + bool(self.category) + len(self.technology_keys)

    @property
    def active_count(self):
        return self.active_value_count

    @property
    def is_active(self):
        return bool(self.active_value_count)

    def without(self, dimension, value=None):
        if dimension == SEARCH_PARAMETER:
            return replace(self, search_query=None)
        if dimension == CATEGORY_PARAMETER:
            return replace(self, category=None)
        if dimension == TECHNOLOGY_PARAMETER:
            return replace(
                self,
                technology_keys=(
                    ()
                    if value is None
                    else tuple(key for key in self.technology_keys if key != value)
                ),
            )
        raise ValueError(f'Unknown filter dimension: {dimension}')


@dataclass(frozen=True, slots=True)
class ActiveProjectFilter:
    dimension: str
    value: str
    dimension_label: str
    value_label: str


def normalize_search_query(value):
    normalized = ' '.join(str(value or '').split()[:SEARCH_MAX_TERMS])
    return normalized[:SEARCH_MAX_LENGTH].rstrip()


def _get_values(query_data, parameter):
    if hasattr(query_data, 'getlist'):
        return query_data.getlist(parameter)
    value = query_data.get(parameter, ())
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value] if value else []


def _first_valid(values, valid_values):
    for value in values:
        if value in valid_values:
            return value
    return None


def _first_search_query(values):
    for value in values:
        normalized = normalize_search_query(value)
        if normalized:
            return normalized
    return None


def parse_filter_state(query_data, options):
    selected_technologies = set(_get_values(query_data, TECHNOLOGY_PARAMETER))
    technology_keys = tuple(
        option.value
        for option in options.technologies
        if option.value in selected_technologies
    )
    return ProjectFilterState(
        search_query=_first_search_query(_get_values(query_data, SEARCH_PARAMETER)),
        category=_first_valid(
            _get_values(query_data, CATEGORY_PARAMETER),
            options.category_values,
        ),
        technology_keys=technology_keys,
    )


def serialize_filter_state(state):
    parameters = []
    if state.search_query:
        parameters.append((SEARCH_PARAMETER, state.search_query))
    parameters.extend(
        (TECHNOLOGY_PARAMETER, key) for key in state.technology_keys
    )
    return urlencode(parameters)


def active_filters(state, options):
    category_labels = {
        option.value: option.label for option in options.categories
    }
    technology_labels = {
        option.value: option.label for option in options.technologies
    }
    result = []
    if state.search_query:
        result.append(
            ActiveProjectFilter(
                SEARCH_PARAMETER,
                state.search_query,
                'Search',
                state.search_query,
            )
        )
    if state.category in category_labels:
        result.append(
            ActiveProjectFilter(
                CATEGORY_PARAMETER,
                state.category,
                'Category',
                category_labels[state.category],
            )
        )
    result.extend(
        ActiveProjectFilter(
            TECHNOLOGY_PARAMETER,
            key,
            'Tech stack',
            technology_labels[key],
        )
        for key in state.technology_keys
        if key in technology_labels
    )
    return tuple(result)

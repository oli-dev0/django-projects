from dataclasses import dataclass

from django.core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class Technology:
    key: str
    label: str
    icon: str


TECHNOLOGY_REGISTRY = (
    Technology('python', 'Python', 'core/img/icons/stack/python.svg'),
    Technology('django', 'Django', 'core/img/icons/stack/django.svg'),
    Technology('flutter', 'Flutter', 'core/img/icons/stack/flutter.svg'),
    Technology('postgresql', 'PostgreSQL', 'core/img/icons/stack/postgresql.svg'),
    Technology('docker', 'Docker', 'core/img/icons/stack/docker.svg'),
    Technology('html5', 'HTML5', 'core/img/icons/html5.svg'),
    Technology('css3', 'CSS3', 'core/img/icons/css3.svg'),
    Technology('javascript', 'JavaScript', 'core/img/icons/javascript.svg'),
    Technology('htmx', 'HTMX', 'core/img/icons/htmx.svg'),
    Technology('bash', 'Bash', 'core/img/icons/bash.svg'),
    Technology('dart', 'Dart', 'core/img/icons/dart.svg'),
    Technology('fast_api', 'FastAPI', 'core/img/icons/fast-api.svg'),
    Technology('flask', 'Flask', 'core/img/icons/flask-dark.svg'),
    Technology('linux', 'Linux', 'core/img/icons/linux.svg'),
    Technology('ubuntu', 'Ubuntu', 'core/img/icons/ubuntu.svg'),
    Technology('cloudflare', 'Cloudflare', 'core/img/icons/cloudflare.svg'),
    Technology('pypi', 'PyPI', 'core/img/icons/pypi.svg'),
    Technology('android_studio', 'Android Studio', 'core/img/icons/android-studio.svg'),
    Technology('pycharm', 'PyCharm', 'core/img/icons/pycharm.svg'),
    Technology('sublime', 'Sublime Text', 'core/img/icons/sublime.svg'),
)
TECHNOLOGY_KEYS = tuple(technology.key for technology in TECHNOLOGY_REGISTRY)
TECHNOLOGY_CHOICES = tuple((technology.key, technology.label) for technology in TECHNOLOGY_REGISTRY)


def normalize_technology_stack(value):
    """Return unique known technology keys in registry order."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError('Technology stack must be a list of technology keys.')

    try:
        selected_keys = set(value)
    except TypeError as error:
        raise ValidationError('Technology stack must contain only technology keys.') from error

    unknown_keys = selected_keys.difference(TECHNOLOGY_KEYS)
    if unknown_keys:
        unknown = ', '.join(sorted(str(key) for key in unknown_keys))
        raise ValidationError(f'Unknown technology key(s): {unknown}.')

    return [key for key in TECHNOLOGY_KEYS if key in selected_keys]

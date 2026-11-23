"""Every span name the gateway emits has a readable label.

The span names are read from the source: the names passed to ``@task`` and
``@workflow``, and the few modules that build them at runtime. A new span
with no label in ``services/span_labels.py`` fails here.
"""

from pathlib import Path
import re

from radicalbit_ai_gateway.caching.route_cache import SPANS as CACHE_SPANS
from radicalbit_ai_gateway.limiting.limits import _ROUTE_CHECKS
from radicalbit_ai_gateway.services.span_labels import span_label

PACKAGE = Path(__file__).resolve().parents[2] / 'radicalbit_ai_gateway'

# A name given as a string literal, where a span is made.
_LITERAL_NAME = re.compile(
    r"""(?:task|workflow)\(\s*name=['"]([^'"]+)['"]"""
    r"""|checked_in_span\(\s*['"]([^'"]+)['"]"""
    r"""|@endpoint\(\s*['"]([^'"]+)['"]"""
)
# Any span made, whatever its name is.
_ANY_SPAN = re.compile(r'\b(?:task|workflow)\(')

# The modules that name a span at runtime. Their names are read below, one
# by one: a module added here needs its names added too.
_RUNTIME_NAMES = {
    'caching/route_cache.py',  # SPANS
    'endpoints/common/http.py',  # traced_endpoint: the @endpoint names
    'endpoints/common/limits.py',  # checked_in_span
    'limiting/limits.py',  # _ROUTE_CHECKS
    'preprocessing.py',  # preprocess.<plugin key>
}


def _sources():
    for path in sorted(PACKAGE.rglob('*.py')):
        yield path.relative_to(PACKAGE).as_posix(), path.read_text()


def _literal_names() -> set[str]:
    return {
        next(g for g in match.groups() if g)
        for _, text in _sources()
        for match in _LITERAL_NAME.finditer(text)
    }


def test_every_span_name_has_a_label():
    names = _literal_names() | set(CACHE_SPANS) | set(_ROUTE_CHECKS)
    # A sanity check that the source was read at all.
    assert {'chat_completions', 'auth_api_key', 'lookup_messages_cache'} <= names

    unlabelled = sorted(n for n in names if span_label(f'{n}.task') is None)

    assert unlabelled == []


def test_a_span_named_at_runtime_is_in_a_known_module():
    """A span whose name is not a string literal cannot be checked above,
    unless its module is one this test knows.
    """
    unknown = []
    for module, text in _sources():
        literal = len(_LITERAL_NAME.findall(text))
        made = len(_ANY_SPAN.findall(text))
        if made > literal and module not in _RUNTIME_NAMES:
            unknown.append(module)

    assert unknown == []


def test_a_preprocessing_plugin_span_has_a_label():
    assert span_label('preprocess.any_plugin.task') is not None

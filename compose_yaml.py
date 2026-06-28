"""Round-trip YAML handling for programmatic Compose mutations."""

from __future__ import annotations

from collections.abc import MutableMapping
from io import StringIO

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class ComposeYamlError(ValueError):
    pass


def _round_trip_yaml() -> YAML:
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    parser.width = 4096
    return parser


def load_compose_yaml(content: str) -> MutableMapping:
    """Parse one Compose document while retaining presentation metadata."""
    try:
        data = _round_trip_yaml().load(content)
    except YAMLError as exc:
        raise ComposeYamlError(str(exc)) from exc
    if not isinstance(data, MutableMapping):
        raise ComposeYamlError("Compose YAML must contain a mapping at the document root")
    return data


def dump_compose_yaml(data: MutableMapping) -> str:
    """Serialize a round-trip Compose document back to text."""
    stream = StringIO()
    try:
        _round_trip_yaml().dump(data, stream)
    except YAMLError as exc:
        raise ComposeYamlError(str(exc)) from exc
    return stream.getvalue()

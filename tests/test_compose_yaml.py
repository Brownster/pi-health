import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compose_yaml import ComposeYamlError, dump_compose_yaml, load_compose_yaml


COMPOSE_WITH_FORMATTING = """# keep this stack comment
x-shared: &shared
  image: "redis:7" # keep this image comment
services:
  existing:
    <<: *shared
    environment:
      MODE: 'prod'
"""


def test_round_trip_compose_preserves_comments_quotes_anchors_and_order():
    data = load_compose_yaml(COMPOSE_WITH_FORMATTING)
    data["services"]["added"] = {"image": "example/added:latest"}

    rendered = dump_compose_yaml(data)

    assert rendered.startswith("# keep this stack comment\n")
    assert 'image: "redis:7" # keep this image comment' in rendered
    assert "x-shared: &shared" in rendered
    assert "<<: *shared" in rendered
    assert "MODE: 'prod'" in rendered
    assert rendered.index("existing:") < rendered.index("added:")


@pytest.mark.parametrize("content", ["services: [", "- not-a-compose-object\n", "null\n"])
def test_load_compose_yaml_rejects_invalid_or_non_mapping_documents(content):
    with pytest.raises(ComposeYamlError):
        load_compose_yaml(content)

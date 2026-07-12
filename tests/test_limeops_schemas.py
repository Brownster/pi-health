import json
from pathlib import Path

from limeops.client import RESPONSE_FIELDS
from limeops.protocol import PUBLIC_ERROR_CODES


def test_request_schema_locks_version_and_top_level_fields():
    schema = json.loads(
        Path("config/schemas/limeops-request.schema.json").read_text()
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version",
        "request_id",
        "operation",
        "params",
        "actor",
    }
    assert schema["properties"]["schema_version"] == {"const": "1"}


def test_response_schema_matches_client_contract_and_error_codes():
    schema = json.loads(
        Path("config/schemas/limeops-response.schema.json").read_text()
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == RESPONSE_FIELDS
    codes = set(
        schema["properties"]["error"]["oneOf"][1]["properties"]["code"]["enum"]
    )
    assert codes == PUBLIC_ERROR_CODES

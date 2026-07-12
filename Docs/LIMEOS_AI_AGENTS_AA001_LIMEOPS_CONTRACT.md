# LimeOS AI Agents AA-001 LimeOps Contract

Date: 2026-07-12

Status: Complete

Predecessor: `Docs/LIMEOS_AI_AGENTS_AA000_BASELINE.md`

Successors: AA-002 diagnostic operations and AA-003 agent gateway

## Outcome

AA-001 implements the provider-neutral, read-only LimeOps boundary. It does not expose
any diagnostic handler yet; AA-002 registers those handlers behind the frozen broker.

The implementation includes:

- A strict version-1 request and response envelope
- Bounded, compact, length-framed JSON over a local Unix socket
- Unix peer identity and `limeops-client` group authorization
- A deny-by-default policy with per-operation timeouts and output limits
- Central resource allowlists checked before handler dispatch
- Fail-closed request auditing and durable JSONL result records
- Stable public error codes and CLI exit codes
- A client library and nested human/JSON CLI
- A secure Unix server skeleton and configuration check mode
- Published request and response JSON Schemas
- A default read-only policy template

## Source Layout

| Path | Responsibility |
| --- | --- |
| `limeops/protocol.py` | Frame encoding, bounds, UTF-8, JSON, and public errors |
| `limeops/policy.py` | Strict policy parsing, operation decisions, and resources |
| `limeops/broker.py` | Request validation, audit, dispatch, timeout, and envelopes |
| `limeops/client.py` | Socket client and response-contract validation |
| `limeops/server.py` | Peer authorization, socket permissions, and connection lifecycle |
| `limeops/cli.py` | Nested commands, JSON output, stderr errors, and exit codes |
| `config/agent-policy.default.json` | Initial read-only operation policy |
| `config/schemas/limeops-*.schema.json` | Published version-1 wire schemas |

Run the client with `python -m limeops`. Validate a server installation without opening
the socket with:

```bash
python -m limeops.server \
  --policy /etc/limeos/agent-policy.json \
  --group limeops-client \
  --check
```

AA-004 owns service identities, installation paths, systemd units, and copying the
default policy into `/etc/limeos`. The broker must not be deployed with an empty handler
registry before AA-002 lands.

## Request Contract

Every request contains exactly these fields:

```json
{
  "schema_version": "1",
  "request_id": "opaque-id",
  "operation": "container.status",
  "params": {"name": "jellyfin"},
  "actor": {
    "type": "mattermost",
    "id": "mattermost-user-id",
    "username": "holly"
  }
}
```

The asserted actor is audit context, not an authority source. The broker records the
kernel-provided peer PID, UID, and GID with every request. The read-only policy does not
vary by asserted actor.

Unknown fields, versions, actor types, operation names, and parameter shapes fail before
dispatch. The request frame limit is 64 KiB.

## Response and Error Contract

Every response contains exactly the version-1 envelope accepted in AA-000. Unsuccessful
responses contain `data: null` and one error object.

| Error code | CLI exit | Meaning |
| --- | ---: | --- |
| `invalid_input` | 2 | Request or operation arguments are invalid |
| `denied_operation` | 3 | Operation or resource is not allowlisted |
| `missing_resource` | 4 | Allowlisted target no longer exists |
| `unavailable_dependency` | 5 | Broker, handler, Docker, helper, or service unavailable |
| `timeout` | 6 | Socket or operation deadline expired |
| `output_limit` | 7 | Bounded result exceeded its policy cap |
| `upstream_failure` | 7 | Handler failed without exposing internal detail |
| `audit_failure` | 8 | Required audit record could not be persisted |
| Protocol validation errors | 9 | Invalid frame, encoding, JSON, request, or response |

The response frame limit is 1 MiB. Each operation has a smaller policy output cap where
appropriate.

## Audit Contract

The broker records request metadata before policy evaluation or dispatch. If that write
fails, no handler runs. Result records contain success, stable error code, duration, and
output size, but never parameters or returned data.

Malformed and unauthorized socket attempts are recorded by the server. Audit JSONL uses
append mode, `0640`, a process lock, and `fsync` before success is reported.

## Policy Contract

Policy parsing rejects unknown fields and unsupported schema versions. An operation must
be present and `enabled: true`. Resource-scoped handlers declare one `resource_param` in
their `OperationDefinition`; the broker then requires an exact match in the policy's
resource list before calling the handler.

An empty resource list denies every resource for that operation. It does not mean all
resources.

## AA-002 Extension Rules

AA-002 extends the broker only by providing `OperationDefinition` instances:

1. Each validator accepts a JSON object and rejects unknown fields.
2. Validators normalize bounded values before the handler runs.
3. Resource operations set `resource_param` so policy enforcement stays in the broker.
4. Handlers call framework-neutral services through injected ports.
5. Handlers never return environment values, credential paths, raw Compose secrets, or
   unbounded logs.
6. Domain exceptions map to the existing public error codes; they do not add codes.
7. Handler tests run without a Unix socket. Broker integration tests cover policy and
   envelopes separately.

AA-002 should provide one production operation registry factory to
`limeops.server.main`. It must not change the protocol, policy, audit, client, or CLI
contracts without a versioned design change.

## AA-003 Gateway Contract

The gateway should use `LimeOpsClient` directly rather than invoking the CLI as a
subprocess. It supplies a Mattermost actor object, receives the same versioned envelope,
and treats `audit_id` as the correlation identifier for provider tool events.

The CLI remains the operator and contract-smoke surface. Machine callers use `--json`.

## Verification

AA-001 focused coverage includes protocol truncation and size bounds, invalid UTF-8 and
JSON, policy parsing, disabled operations, resource denials, malformed requests, failed
audits, handler timeouts, output limits, private error handling, peer credentials,
unauthorized connections, socket modes, client response validation, CLI mappings, JSON
Schemas, and a real socket frame round trip.

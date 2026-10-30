# agentgateway webhook masking lab

Local verification of the free agentgateway **v1.7.0** image in standalone mode, using explicit routes and an external HTTP guardrail webhook. The implemented scope is **non-streaming OpenAI chat completions with text messages**.

The first verification passed **19 end-to-end cases and 5 Java serialization tests**. Both request and response masking worked. The supplied Java `List<Message> body` shape was rejected with HTTP 503; `body` must be an object containing `messages` or `choices`. See [FINDINGS.md](FINDINGS.md) for the evidence and limits of this conclusion.

## Run

Prerequisites: Docker with Compose v2 and Bash. No host Java, Maven, Python, API keys, or downloaded models are required. The first build needs internet access for images and Maven dependencies.

```bash
./verify.sh
```

This builds the Java application, runs its serialization tests, starts three services, waits for readiness, and executes the end-to-end suite. The script exits nonzero on a test failure. Services remain running for manual experiments.

| Service | Purpose | Host address |
| --- | --- | --- |
| gateway | agentgateway v1.7.0 | http://localhost:3000 |
| guardrails | Java 21 / Spring Boot 4.0.9 / Jackson 3 webhook | http://localhost:8080 |
| mock | Deterministic Python HTTP backend | Internal Compose network only |
| tests | On-demand Python test runner | None |

Ports can be changed without changing internal service addresses:

```bash
GATEWAY_PORT=13000 GUARDRAIL_PORT=18080 ./verify.sh
```

The script sets `LOCAL_UID` and `LOCAL_GID` to your host IDs so the services can write evidence. If using Compose directly on Linux, export them first:

```bash
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
docker compose up --build -d
docker compose run --rm tests
docker compose logs -f gateway guardrails
docker compose down
```

Use `./verify.sh` when you want the complete evidence bundle including Docker metadata and logs. Direct test runs generate HTTP exchange evidence and a report, but do not collect Docker logs or image metadata.

## Change webhook behavior

Both the webhook and mock read `scenarios/active.json` on every call. Change it without rebuilding or restarting. Mounting the directory allows atomic replacement of the file:

```bash
cp scenarios/mask-both.json scenarios/active.tmp
mv scenarios/active.tmp scenarios/active.json
```

Available examples are `pass.json`, `mask-both.json`, `reject-request.json`, `reject-response.json`, and `bare-array.json`. Restore `pass.json` the same way. The automated runner restores the exact active file it found before running, even when assertions fail. Run tests serially and avoid manual traffic or scenario edits during a test run; its journal assertions assume exclusive use of this lab. Concurrent test runners are rejected by a file lock.

Each scenario has independent `request` and `response` settings:

```json
{
  "request": {
    "action": "mask",
    "replacements": [{"from": "REQUEST_SECRET", "to": "[MASKED]"}],
    "reason": "Synthetic request redaction"
  },
  "response": {"action": "pass"},
  "mock": {"choices": ["Mock reply contains RESPONSE_SECRET."]}
}
```

- `pass`: returns an empty action object, or an optional `reason`.
- `mask`: applies literal, case-sensitive replacements in listed order to every message/choice. Requires a `replacements` list. An empty replacement string is supported; an empty search string is rejected. Roles, counts, and ordering are preserved.
- `reject`: requires `statusCode` (400–599) and string `body`; `reason` is optional. This scenario file uses camel case; the serialized webhook action correctly uses `status_code`.
- `rawReply`: supplies an exact JSON reply, overriding normal action construction, for deliberate malformed-payload tests. See `bare-array.json`.
- `mock.choices`: nonempty list of fixed assistant response strings; independent of the incoming prompt. This independence lets the tests isolate request and response masking.

Malformed scenario settings produce an explicit webhook HTTP 500 error, which the gateway treats as a guard failure. Valid Pass, Mask, and Reject decisions all return **HTTP 200 from the webhook**; a Reject decision embeds the eventual client status in its JSON body.

## Manual requests

After activating `mask-both.json`:

```bash
curl -sS http://localhost:3000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"local-test","stream":false,"messages":[{"role":"user","content":"My value is REQUEST_SECRET."}]}'
```

The client sees `Mock reply contains [RESPONSE_MASKED].`. The upstream request captured in `artifacts/mock.jsonl` contains `[REQUEST_MASKED]` in place of `REQUEST_SECRET`.

To inspect the webhook's JSON directly, bypassing the gateway:

```bash
curl -sS http://localhost:8080/request \
  -H 'Content-Type: application/json' \
  -d '{"body":{"messages":[{"role":"user","content":"REQUEST_SECRET"}]}}'

curl -sS http://localhost:8080/response \
  -H 'Content-Type: application/json' \
  -d '{"body":{"choices":[{"message":{"role":"assistant","content":"RESPONSE_SECRET"}}]}}'
```

Use `curl -i` with `reject-request.json`, `reject-response.json`, or `bare-array.json` to inspect the resulting client status and body.

## Protocol and gateway configuration

[gateway/config.yaml](gateway/config.yaml) uses `binds → listeners → routes` and route-level `policies.ai.promptGuard`. It does not use simplified top-level `llm` configuration or a Kubernetes controller. The AI backend uses OpenAI format and a host/path override to the mock.

`webhook.action: reject` means **enforce the webhook verdict**, including masking. It does not force every request to be rejected. Both stages use `failureMode: failClosed`. The configuration is read-only; MCP session encryption is explicitly disabled because MCP is unused in this lab.

[Protocol.java](guardrails/src/main/java/lab/Protocol.java) adapts the supplied sealed records:

| Decision | JSON sent by webhook |
| --- | --- |
| Pass | `{"action":{}}` |
| Request mask | `{"action":{"body":{"messages":[{"role":"user","content":"[MASKED]"}]}}}` |
| Response mask | `{"action":{"body":{"choices":[{"message":{"role":"assistant","content":"[MASKED]"}}]}}}` |
| Reject | `{"action":{"status_code":451,"body":"Blocked"}}` |

All actions may contain an optional string `reason`. The action is an untagged object: no `type` discriminator or `"action":"mask"` string is sent. `isReject()` is excluded from serialization. Separate mask records prevent mixing request and response wrappers. Incoming envelopes are concrete records, so polymorphic action deserialization is not needed.

Message objects have only `role` and string `content`. Do not copy arbitrary OpenAI message properties into masked webhook responses. The test suite demonstrates that an extra `name` field produces a guard failure in v1.7.0.

References: [v1.7.0 protocol source](https://github.com/agentgateway/agentgateway/blob/v1.7.0/crates/agentgateway/src/llm/policy/webhook.rs), [v1.7.0 gateway schema](https://github.com/agentgateway/agentgateway/blob/v1.7.0/schema/config.json), [standalone webhook documentation](https://agentgateway.dev/docs/standalone/latest/documentation/llm/prompt-guards/webhooks/).

## Test evidence

`artifacts/report.md` is the latest readable report; `artifacts/latest.json` contains its run ID. Each `artifacts/runs/<run-id>/` directory contains:

- One JSON file per case: scenario, client request/response, webhook request/reply, and mock request/response.
- `summary.json` and `report.md` with expected assertions reflected in pass/fail results.
- `compose.log`, `gateway-image.json` (including resolved digest), `compose-images.json`, and the tested `gateway-config.yaml`, when run through `verify.sh`.
- `java-tests/` containing Maven Surefire results for the five serialization tests.

The runner verifies full message/choice content and completion metadata, webhook ordering, and upstream call counts. Request rejection and request protocol errors must make zero upstream calls. Malformed action cases must return HTTP 503 with the appropriate request/response error body. Gateway logs are supporting diagnostics; HTTP payload assertions determine the result.

Runtime artifacts are gitignored. They contain the synthetic test text and any text you submit manually. The tracked [FINDINGS.md](FINDINGS.md) summarizes the verified result. Streaming, real providers, other APIs, tools, multimodal content, failure-mode alternatives, and performance are not covered.

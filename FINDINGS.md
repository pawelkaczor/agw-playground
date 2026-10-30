# Verification findings — agentgateway v1.7.0

Verified on **2026-10-30**, run `20261030T135644-2822515`.

**Result: webhook Mask works for both request and response text in the tested non-streaming chat-completions path.** All 19 end-to-end cases and all 5 Java protocol tests passed. No discrepancy with the documented behavior was observed within this scope.

## Tested setup

- Free image: `cr.agentgateway.dev/agentgateway:v1.7.0`.
- Resolved repository digest: `sha256:60216aafb03d37f94e952ff3d51d2f630a65b10ecaebdc0a864882f92610c45b`.
- Standalone static configuration with explicit routes and `policies.ai.promptGuard`; no top-level simplified `llm` configuration.
- Request and response webhook enforcement enabled with `action: reject` and `failureMode: failClosed`.
- Java 21 / Spring Boot 4.0.9 webhook, deterministic local OpenAI-compatible mock, no real provider.

## Expected versus observed

| Case | Expected | Observed |
| --- | --- | --- |
| Pass, with and without reasons | Original content preserved | HTTP 200; full completion and upstream message assertions passed |
| Request Mask | Replacement reaches provider | Mock received `My value is [REQUEST_MASKED].` |
| Response Mask | Replacement reaches client | Client received `Mock reply contains [RESPONSE_MASKED].` |
| Both Mask | Each stage changes only its intended text | Both exact transformations verified in one exchange |
| Request Reject | Configured error, no provider call | HTTP 451; exact rejection body; zero mock calls and no response webhook |
| Response Reject | Provider called, completion withheld | HTTP 451; exact rejection body; one mock call |
| Multiple messages/choices | Counts, order, unaffected text and metadata preserved | All assertions passed |
| Unicode and empty replacements | Exact text preserved or removed | All assertions passed, including entirely empty content |
| Bare-array mask body, either stage | Protocol error, fail closed | HTTP 503; request or response processing error body |
| Wrong wrapper, either stage | Protocol error, fail closed | HTTP 503; gateway logged `invalid webhook response` |
| Extra message field, either stage | Protocol error, fail closed | HTTP 503; action deserialization error |
| Unexpected field in Pass, either stage | Protocol error, fail closed | HTTP 503; action deserialization error |
| Invalid scenario action, either stage | Explicit service error, fail closed | Webhook HTTP 500 followed by gateway HTTP 503 |

Successful completion checks compared the full JSON response with the mock response plus the intended text replacements, including IDs, choice indexes, finish reasons, model, and usage. Upstream assertions also checked preserved model, streaming flag, temperature, and requested choice count.

## Correction to the supplied Java model

The supplied `MaskAction(List<SimpleChatCompletionMessage> body, String reason)` serializes `body` as an array. The gateway requires an object wrapper:

```json
{"action":{"body":{"messages":[{"role":"user","content":"[MASKED]"}]}}}
```

For response masking:

```json
{"action":{"body":{"choices":[{"message":{"role":"assistant","content":"[MASKED]"}}]}}}
```

The implementation uses separate `RequestMaskAction(PromptMessages body, ...)` and `ResponseMaskAction(ResponseChoices body, ...)` records. Exact serialization tests check these shapes, optional reasons, snake-case `status_code`, and absence of helper/discriminator properties.

The original bare-array shape was replayed unchanged as deliberate malformed JSON structure inside a valid webhook HTTP 200 reply. The request case produced `failed to process LLM request`, with no upstream call. The response case produced `failed to process LLM response`, withholding the mock completion. Both client statuses were 503. This demonstrates a protocol-shape problem with that class; it does not prove what any separate production application currently serializes.

## Evidence and reproduction

Run `./verify.sh` to reproduce. The complete observed run is in [artifacts/runs/20261030T135644-2822515](artifacts/runs/20261030T135644-2822515/):

- [Test report](artifacts/runs/20261030T135644-2822515/report.md)
- [Both masking directions](artifacts/runs/20261030T135644-2822515/mask-both.json)
- [Original bare-array request shape](artifacts/runs/20261030T135644-2822515/bare-array-mask-request.json)
- [Gateway image metadata](artifacts/runs/20261030T135644-2822515/gateway-image.json)
- [Java test results](artifacts/runs/20261030T135644-2822515/java-tests/lab.ProtocolTest.txt)
- [Gateway and service logs](artifacts/runs/20261030T135644-2822515/compose.log)

Generated evidence is retained locally and gitignored. A fresh checkout must run the verification to create its own evidence. `artifacts/report.md` always refers to the latest run; the links above identify this specific verification.

Behavior was checked against the [v1.7.0 protocol source](https://github.com/agentgateway/agentgateway/blob/v1.7.0/crates/agentgateway/src/llm/policy/webhook.rs) and [standalone webhook documentation](https://agentgateway.dev/docs/standalone/latest/documentation/llm/prompt-guards/webhooks/). The source reference is tag-pinned; the documentation URL can change over time.

These results do not establish behavior for streaming, other provider/API formats, real-provider integration, tools, multimodal content, `failOpen`/audit modes, or performance.

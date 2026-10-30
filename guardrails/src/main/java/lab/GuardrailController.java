package lab;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.json.JsonMapper;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import static lab.Protocol.*;

@RestController
public class GuardrailController {
    public record Replacement(String from, String to) {}
    public record Mode(String action, List<Replacement> replacements, Integer statusCode,
                       String body, String reason, Object rawReply) {}
    public record Scenario(Mode request, Mode response, Object mock) {}

    private final JsonMapper mapper;
    private final Path scenario = Path.of(System.getenv().getOrDefault("SCENARIO_FILE", "scenarios/active.json"));
    private final Path journal = Path.of(System.getenv().getOrDefault("JOURNAL_FILE", "artifacts/guardrails.jsonl"));

    public GuardrailController(JsonMapper mapper) { this.mapper = mapper; }

    @GetMapping("/health")
    public Map<String, String> health() { return Map.of("status", "ok"); }

    @PostMapping(value = "/request", consumes = "application/json", produces = "application/json")
    public ResponseEntity<String> request(@RequestBody String body) { return handle("request", body); }

    @PostMapping(value = "/response", consumes = "application/json", produces = "application/json")
    public ResponseEntity<String> response(@RequestBody String body) { return handle("response", body); }

    private ResponseEntity<String> handle(String stage, String incoming) {
        Object reply;
        int status = 200;
        try {
            Scenario settings = mapper.readValue(Files.readString(scenario), Scenario.class);
            Mode mode = stage.equals("request") ? settings.request() : settings.response();
            if (mode == null) throw new IllegalArgumentException("Missing " + stage + " scenario");
            if (mode.rawReply() != null) {
                reply = mode.rawReply(); // Deliberate protocol fault injection for negative tests.
            } else {
                if (mode.action() == null) throw new IllegalArgumentException("Missing action");
                reply = switch (mode.action()) {
                    case "pass" -> envelope(stage, new PassAction(mode.reason()));
                    case "reject" -> {
                        if (mode.statusCode() == null || mode.statusCode() < 400 || mode.statusCode() > 599 || mode.body() == null)
                            throw new IllegalArgumentException("Reject requires statusCode 400..599 and body");
                        yield envelope(stage, new RejectAction(mode.body(), mode.statusCode(), mode.reason()));
                    }
                    case "mask" -> mask(stage, incoming, mode);
                    default -> throw new IllegalArgumentException("Unknown action: " + mode.action());
                };
            }
        } catch (Exception e) {
            status = 500;
            reply = Map.of("error", e.getClass().getSimpleName() + ": " + e.getMessage());
        }
        String outgoing = mapper.writeValueAsString(reply);
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("time", Instant.now().toString());
        event.put("stage", stage);
        event.put("requestBody", mapper.readValue(incoming, Object.class));
        event.put("responseStatus", status);
        event.put("responseBody", reply);
        append(event); // Commit evidence before sending the reply.
        return ResponseEntity.status(status).body(outgoing);
    }

    private Object envelope(String stage, Object action) {
        return stage.equals("request") ? new PromptReply((RequestAction) action) : new ResponseReply((ResponseAction) action);
    }

    private Object mask(String stage, String incoming, Mode mode) {
        if (stage.equals("request")) {
            PromptRequest request = mapper.readValue(incoming, PromptRequest.class);
            List<Message> messages = request.body().messages().stream().map(m -> rewrite(m, mode)).toList();
            return new PromptReply(new RequestMaskAction(new PromptMessages(messages), mode.reason()));
        }
        ResponseRequest request = mapper.readValue(incoming, ResponseRequest.class);
        List<ResponseChoice> choices = request.body().choices().stream()
                .map(c -> new ResponseChoice(rewrite(c.message(), mode))).toList();
        return new ResponseReply(new ResponseMaskAction(new ResponseChoices(choices), mode.reason()));
    }

    private Message rewrite(Message message, Mode mode) {
        String text = Objects.requireNonNull(message.content(), "Message content must be a string");
        if (mode.replacements() == null) throw new IllegalArgumentException("Mask requires replacements");
        for (Replacement r : mode.replacements()) {
            if (r.from() == null || r.from().isEmpty() || r.to() == null)
                throw new IllegalArgumentException("Replacement requires nonempty from and nonnull to");
            text = text.replace(r.from(), r.to());
        }
        return new Message(Objects.requireNonNull(message.role()), text);
    }

    private synchronized void append(Object event) {
        try {
            Files.createDirectories(journal.getParent());
            Files.writeString(journal, mapper.writeValueAsString(event) + "\n", StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (java.io.IOException e) { throw new java.io.UncheckedIOException(e); }
    }
}

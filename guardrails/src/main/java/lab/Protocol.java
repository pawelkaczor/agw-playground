package lab;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import tools.jackson.databind.PropertyNamingStrategies.SnakeCaseStrategy;
import tools.jackson.databind.annotation.JsonNaming;
import java.util.List;

/** Wire contract matched to agentgateway v1.7.0 llm/policy/webhook.rs. */
public final class Protocol {
    private Protocol() {}
    public record Message(String role, String content) {}
    public record PromptMessages(List<Message> messages) {}
    public record ResponseChoice(Message message) {}
    public record ResponseChoices(List<ResponseChoice> choices) {}
    public record PromptRequest(PromptMessages body) {}
    public record ResponseRequest(ResponseChoices body) {}
    public record PromptReply(RequestAction action) {}
    public record ResponseReply(ResponseAction action) {}

    public sealed interface RequestAction permits PassAction, RequestMaskAction, RejectAction {
        String reason();
        @JsonIgnore
        default boolean isReject() { return this instanceof RejectAction; }
    }
    public sealed interface ResponseAction permits PassAction, ResponseMaskAction, RejectAction {
        String reason();
    }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PassAction(String reason) implements RequestAction, ResponseAction {}
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record RequestMaskAction(PromptMessages body, String reason) implements RequestAction {}
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ResponseMaskAction(ResponseChoices body, String reason) implements ResponseAction {}
    @JsonNaming(SnakeCaseStrategy.class)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record RejectAction(String body, Integer statusCode, String reason)
            implements RequestAction, ResponseAction {}
}

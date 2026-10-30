package lab;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import java.util.List;
import static lab.Protocol.*;
import static org.junit.jupiter.api.Assertions.assertEquals;

class ProtocolTest {
    private final JsonMapper mapper = JsonMapper.builder().build();
    private void matches(String expected, Object actual) {
        assertEquals(mapper.readTree(expected), mapper.readTree(mapper.writeValueAsString(actual)));
    }
    @Test void passHasNoDiscriminatorOrHelperProperty() {
        matches("{\"action\":{}}", new PromptReply(new PassAction(null)));
        matches("{\"action\":{\"reason\":\"ok\"}}", new ResponseReply(new PassAction("ok")));
    }
    @Test void requestMaskUsesMessagesWrapper() {
        matches("""
          {"action":{"body":{"messages":[{"role":"user","content":"[MASKED]"}]}}}
          """, new PromptReply(new RequestMaskAction(new PromptMessages(List.of(new Message("user", "[MASKED]"))), null)));
    }
    @Test void responseMaskUsesChoicesWrapper() {
        matches("""
          {"action":{"body":{"choices":[{"message":{"role":"assistant","content":""}}]},"reason":"masked"}}
          """, new ResponseReply(new ResponseMaskAction(new ResponseChoices(List.of(new ResponseChoice(new Message("assistant", "")))), "masked")));
    }
    @Test void rejectionUsesSnakeCaseAndNoHelperProperty() {
        matches("{\"action\":{\"body\":\"blocked\",\"status_code\":451}}", new PromptReply(new RejectAction("blocked", 451, null)));
        matches("{\"action\":{\"body\":\"blocked\",\"status_code\":403,\"reason\":\"policy\"}}", new ResponseReply(new RejectAction("blocked", 403, "policy")));
    }
    @Test void incomingEnvelopesDeserialize() {
        assertEquals("secret", mapper.readValue("{\"body\":{\"messages\":[{\"role\":\"user\",\"content\":\"secret\"}]}}", PromptRequest.class).body().messages().getFirst().content());
        assertEquals("secret", mapper.readValue("{\"body\":{\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"secret\"}}]}}", ResponseRequest.class).body().choices().getFirst().message().content());
    }
}

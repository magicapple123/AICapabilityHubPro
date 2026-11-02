package com.aicapabilityhub.gateway.filter;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;

import com.aicapabilityhub.gateway.config.JwtProperties;
import com.aicapabilityhub.gateway.security.JwtService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class AuthGlobalFilterTest {

    private static final String SECRET = "test-secret-must-be-at-least-32-bytes";
    private static final String FORGED_REQUEST_ID = "client-controlled-request-id";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private JwtService jwtService;
    private AuthGlobalFilter filter;

    @BeforeEach
    void setUp() {
        jwtService = new JwtService(new JwtProperties(SECRET, null, "ai-capability-hub", Duration.ofHours(1)));
        filter = new AuthGlobalFilter(jwtService, objectMapper);
    }

    @Test
    void rejectsUnauthenticatedRequestWithUnifiedResult() throws Exception {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/user/ping")
                        .header(AuthGlobalFilter.HEADER_REQUEST_ID, FORGED_REQUEST_ID)
                        .build());

        StepVerifier.create(filter.filter(exchange, completedChain())).verifyComplete();

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        JsonNode body = objectMapper.readTree(exchange.getResponse().getBodyAsString().block());
        assertThat(body.get("code").asInt()).isEqualTo(1001);
        assertThat(body.get("message").asText()).isEqualTo("未认证或登录已过期");
        assertThat(body.get("data").isNull()).isTrue();
        assertThat(body.get("requestId").asText()).isNotBlank();
        assertThat(body.get("requestId").asText()).isNotEqualTo(FORGED_REQUEST_ID);
        assertThat(exchange.getResponse().getHeaders().getFirst(AuthGlobalFilter.HEADER_REQUEST_ID))
                .isEqualTo(body.get("requestId").asText());
    }

    @Test
    void rejectsInternalPathBeforeAuthentication() throws Exception {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/user-service/internal/user/check").build());

        StepVerifier.create(filter.filter(exchange, completedChain())).verifyComplete();

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
        JsonNode body = objectMapper.readTree(exchange.getResponse().getBodyAsString().block());
        assertThat(body.get("message").asText()).isEqualTo("禁止访问内部接口");
    }

    @Test
    void rejectsRootInternalPathEvenWithoutGatewayRoute() throws Exception {
        InternalAccessWebFilter internalFilter = new InternalAccessWebFilter(objectMapper);
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/internal/hidden")
                        .header(AuthGlobalFilter.HEADER_REQUEST_ID, FORGED_REQUEST_ID)
                        .build());

        StepVerifier.create(internalFilter.filter(exchange, ignored -> Mono.empty())).verifyComplete();

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
        JsonNode body = objectMapper.readTree(exchange.getResponse().getBodyAsString().block());
        assertThat(body.get("code").asInt()).isEqualTo(1001);
        assertThat(body.get("requestId").asText()).isNotBlank();
        assertThat(body.get("requestId").asText()).isNotEqualTo(FORGED_REQUEST_ID);
    }

    @Test
    void passesWhitePathAndRemovesSpoofedIdentity() {
        MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest
                .get("/api/capability/market/demo")
                .header(AuthGlobalFilter.HEADER_USER_ID, "forged")
                .header(AuthGlobalFilter.HEADER_USER_NAME, "forged")
                .header(AuthGlobalFilter.HEADER_REQUEST_ID, FORGED_REQUEST_ID)
                .build());
        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();

        StepVerifier.create(filter.filter(exchange, capturingChain(forwarded))).verifyComplete();

        HttpHeaders headers = forwarded.get().getRequest().getHeaders();
        assertThat(headers.getFirst(AuthGlobalFilter.HEADER_USER_ID)).isNull();
        assertThat(headers.getFirst(AuthGlobalFilter.HEADER_USER_NAME)).isNull();
        assertThat(headers.getFirst(AuthGlobalFilter.HEADER_REQUEST_ID)).isNotBlank();
        assertThat(headers.getFirst(AuthGlobalFilter.HEADER_REQUEST_ID)).isNotEqualTo(FORGED_REQUEST_ID);
        assertThat((String) exchange.getAttribute(AuthGlobalFilter.ATTRIBUTE_REQUEST_ID))
                .isEqualTo(headers.getFirst(AuthGlobalFilter.HEADER_REQUEST_ID));
    }

    @Test
    void injectsIdentityFromValidToken() {
        String token = jwtService.createDevToken("42", "test-user");
        MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest
                .get("/api/chat/ping")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .header(AuthGlobalFilter.HEADER_USER_ID, "forged")
                .build());
        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();

        StepVerifier.create(filter.filter(exchange, capturingChain(forwarded))).verifyComplete();

        HttpHeaders headers = forwarded.get().getRequest().getHeaders();
        assertThat(headers.getFirst(AuthGlobalFilter.HEADER_USER_ID)).isEqualTo("42");
        assertThat(headers.getFirst(AuthGlobalFilter.HEADER_USER_NAME)).isEqualTo("test-user");
        assertThat(headers.getFirst(AuthGlobalFilter.HEADER_REQUEST_ID)).isNotBlank();
    }

    private GatewayFilterChain completedChain() {
        return exchange -> Mono.empty();
    }

    private GatewayFilterChain capturingChain(AtomicReference<ServerWebExchange> forwarded) {
        return exchange -> {
            forwarded.set(exchange);
            exchange.getResponse().setStatusCode(HttpStatus.OK);
            return Mono.empty();
        };
    }
}

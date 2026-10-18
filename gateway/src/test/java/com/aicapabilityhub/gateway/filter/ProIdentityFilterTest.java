package com.aicapabilityhub.gateway.filter;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.concurrent.atomic.AtomicReference;

import com.aicapabilityhub.gateway.config.JwtProperties;
import com.aicapabilityhub.gateway.security.JwtService;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Jwts;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

class ProIdentityFilterTest {
    private static final String SECRET = "leader-filter-secret-at-least-32-bytes";
    private final ObjectMapper mapper = new ObjectMapper();
    private final JwtService jwt = new JwtService(
            new JwtProperties(SECRET, "ai-capability-hub", Duration.ofHours(1)));
    private final AuthGlobalFilter filter = new AuthGlobalFilter(jwt, mapper);

    @Test
    void replacesAllRoleAndIdentityAliasesFromSignedClaims() {
        String token = Jwts.builder().issuer("ai-capability-hub").subject("42")
                .claim("username", "signed-user").claim("role", "user")
                .expiration(Date.from(Instant.now().plusSeconds(60)))
                .signWith(JwtService.createKey(SECRET)).compact();
        var request = MockServerHttpRequest.get("/api/chat/completions")
                .header("Authorization", "Bearer " + token)
                .header("x-user-id", "1").header("X-User-Role", "admin", "user")
                .header("X-User-Roles", "admin").header("role", "admin")
                .header("X-Role", "admin").header("X-Forwarded-User", "admin")
                .header("X-Request-Id", "spoofed").build();
        var exchange = MockServerWebExchange.from(request);
        var forwarded = new AtomicReference<ServerWebExchange>();
        filter.filter(exchange, value -> { forwarded.set(value); return Mono.empty(); }).block();
        var headers = forwarded.get().getRequest().getHeaders();
        assertThat(headers.getFirst("X-User-Id")).isEqualTo("42");
        assertThat(headers.get("X-User-Role")).containsExactly("user");
        for (String name : new String[]{"role", "X-Role", "X-User-Roles", "X-Forwarded-User"}) {
            assertThat(headers.containsKey(name)).isFalse();
        }
        assertThat(headers.getFirst("X-Request-Id")).isNotEqualTo("spoofed");
    }

    @Test
    void exactExchangePostIsAnonymousAndStripsSpoofedAdmin() {
        var exchange = MockServerWebExchange.from(MockServerHttpRequest
                .post("/api/user/apikeys/exchange").header("X-User-Role", "admin"));
        var forwarded = new AtomicReference<ServerWebExchange>();
        filter.filter(exchange, value -> { forwarded.set(value); return Mono.empty(); }).block();
        assertThat(forwarded.get()).isNotNull();
        assertThat(forwarded.get().getRequest().getHeaders().getFirst("X-User-Role")).isNull();
    }

    @ParameterizedTest
    @ValueSource(strings = {"/api/user/apikeys/exchange/", "/api/user/apikeys/exchange/extra",
            "/user-service/api/user/apikeys/exchange", "/api/user/apikeys/exchange-fake"})
    void doesNotWhitelistExchangeLookalikes(String path) {
        var exchange = MockServerWebExchange.from(MockServerHttpRequest.post(path));
        filter.filter(exchange, value -> Mono.error(new AssertionError("unexpected forwarding"))).block();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void exchangeGetRequiresAuthentication() {
        var exchange = MockServerWebExchange.from(MockServerHttpRequest.get("/api/user/apikeys/exchange"));
        filter.filter(exchange, value -> Mono.empty()).block();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @ParameterizedTest
    @ValueSource(strings = {"/internal/hidden", "/user-service/internal/user/check",
            "/api/INTERNAL/check", "/user-service/%69nternal/user/check"})
    void rejectsInternalSegmentsBeforeRouteMatching(String path) {
        var exchange = MockServerWebExchange.from(MockServerHttpRequest.get(path));
        new InternalAccessWebFilter(mapper).filter(exchange,
                value -> Mono.error(new AssertionError("internal forwarded"))).block();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
    }
}

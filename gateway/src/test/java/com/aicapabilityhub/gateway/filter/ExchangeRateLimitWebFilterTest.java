package com.aicapabilityhub.gateway.filter;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.InetSocketAddress;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.core.publisher.Mono;

class ExchangeRateLimitWebFilterTest {
    @Test
    void limitsExchangeAndNeverCachesSuccessfulOrRejectedResponses() {
        var filter = new ExchangeRateLimitWebFilter(Clock.fixed(Instant.now(), ZoneOffset.UTC));
        var forwarded = new AtomicInteger();
        for (int attempt = 0; attempt < 11; attempt++) {
            var exchange = MockServerWebExchange.from(MockServerHttpRequest
                    .post("/api/user/apikeys/exchange")
                    .remoteAddress(new InetSocketAddress("127.0.0.1", 12345))
                    .header("X-Forwarded-For", "forged-" + attempt));
            filter.filter(exchange, value -> { forwarded.incrementAndGet(); return Mono.empty(); }).block();
            assertThat(exchange.getResponse().getHeaders().getCacheControl()).isEqualTo("no-store");
            if (attempt == 10) {
                assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
                assertThat(exchange.getResponse().getBodyAsString().block()).contains("\"code\":4001");
                assertThat(exchange.getResponse().getHeaders().getFirst("X-Request-Id")).isNotBlank();
            }
        }
        assertThat(forwarded.get()).isEqualTo(10);
    }

    @Test
    void unrelatedEndpointsAreNotLimited() {
        var filter = new ExchangeRateLimitWebFilter();
        var count = new AtomicInteger();
        for (int attempt = 0; attempt < 20; attempt++) {
            var exchange = MockServerWebExchange.from(MockServerHttpRequest.get("/api/capability/market"));
            filter.filter(exchange, value -> { count.incrementAndGet(); return Mono.empty(); }).block();
        }
        assertThat(count.get()).isEqualTo(20);
    }
}

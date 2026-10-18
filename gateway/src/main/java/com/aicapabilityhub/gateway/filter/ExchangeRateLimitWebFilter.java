package com.aicapabilityhub.gateway.filter;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

import org.springframework.core.Ordered;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

/** 单网关本地限流；不相信客户端可伪造的 X-Forwarded-For。 */
@Component
public final class ExchangeRateLimitWebFilter implements WebFilter, Ordered {
    private static final String PATH = "/api/user/apikeys/exchange";
    private static final long WINDOW_MS = 60_000;
    private static final int LIMIT = 10;
    private static final int MAX_CLIENTS = 2048;
    private final Map<String, Window> windows = new HashMap<>();
    private final Clock clock;

    public ExchangeRateLimitWebFilter() {
        this(Clock.systemUTC());
    }

    ExchangeRateLimitWebFilter(Clock clock) {
        this.clock = clock;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        String path = exchange.getRequest().getURI().getPath();
        if (!path.equals(PATH) && !path.endsWith(PATH)) {
            return chain.filter(exchange);
        }
        exchange.getResponse().getHeaders().setCacheControl("no-store");
        exchange.getResponse().getHeaders().set("Pragma", "no-cache");
        if (exchange.getRequest().getMethod() != HttpMethod.POST) {
            return chain.filter(exchange);
        }
        var address = exchange.getRequest().getRemoteAddress();
        String client = address == null ? "unknown" : address.getAddress().getHostAddress();
        if (acquire(client)) {
            return chain.filter(exchange);
        }
        String requestId = UUID.randomUUID().toString();
        exchange.getResponse().setStatusCode(HttpStatus.TOO_MANY_REQUESTS);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        exchange.getResponse().getHeaders().set("X-Request-Id", requestId);
        exchange.getResponse().getHeaders().set("Retry-After", "60");
        String body = "{\"code\":4001,\"message\":\"兑换请求过于频繁\",\"data\":null,\"requestId\":\""
                + requestId + "\"}";
        return exchange.getResponse().writeWith(Mono.just(exchange.getResponse().bufferFactory()
                .wrap(body.getBytes(StandardCharsets.UTF_8))));
    }

    private synchronized boolean acquire(String client) {
        long now = clock.millis();
        Window window = windows.get(client);
        if (window == null || now - window.start >= WINDOW_MS) {
            if (windows.size() >= MAX_CLIENTS) {
                windows.entrySet().removeIf(entry -> now - entry.getValue().start >= WINDOW_MS);
            }
            if (window == null && windows.size() >= MAX_CLIENTS) {
                return false;
            }
            window = new Window(now);
            windows.put(client, window);
        }
        return ++window.count <= LIMIT;
    }

    @Override
    public int getOrder() {
        return -150;
    }

    private static final class Window {
        private final long start;
        private int count;

        private Window(long start) {
            this.start = start;
        }
    }
}

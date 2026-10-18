package com.aicapabilityhub.gateway.filter;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.aicapabilityhub.gateway.security.InternalPaths;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

/**
 * 在路由匹配之前拒绝外部内部接口，避免无匹配路由时 GlobalFilter 不被组装。
 */
@Component
public final class InternalAccessWebFilter implements WebFilter, Ordered {

    private static final Logger LOGGER = LoggerFactory.getLogger(InternalAccessWebFilter.class);
    private static final String REQUEST_ID_HEADER = AuthGlobalFilter.HEADER_REQUEST_ID;
    private final ObjectMapper objectMapper;

    public InternalAccessWebFilter(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        String path = exchange.getRequest().getURI().getPath();
        if (!isInternalPath(path)) {
            return chain.filter(exchange);
        }

        // 即使请求在路由前被拒绝，也必须覆盖客户端伪造的链路标识。
        String requestId = UUID.randomUUID().toString();
        LOGGER.info(
                "requestId={} userId=anonymous serviceName=api-gateway method={} path={} status=403",
                requestId,
                exchange.getRequest().getMethod(),
                path);
        return writeForbidden(exchange, requestId);
    }

    private boolean isInternalPath(String path) {
        return InternalPaths.containsInternalSegment(path);
    }

    private Mono<Void> writeForbidden(ServerWebExchange exchange, String requestId) {
        if (exchange.getResponse().isCommitted()) {
            return exchange.getResponse().setComplete();
        }
        byte[] body;
        try {
            body = objectMapper.writeValueAsBytes(
                    new ErrorResult(1001, "禁止访问内部接口", null, requestId));
        } catch (JsonProcessingException exception) {
            body = ("""
                    {"code":1001,"message":"禁止访问内部接口","data":null,"requestId":"%s"}
                    """.formatted(requestId)).getBytes(StandardCharsets.UTF_8);
        }
        exchange.getResponse().setStatusCode(HttpStatus.FORBIDDEN);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        exchange.getResponse().getHeaders().set(REQUEST_ID_HEADER, requestId);
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(body);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }

    @Override
    public int getOrder() {
        return -200;
    }

    private record ErrorResult(int code, String message, Object data, String requestId) {
    }
}

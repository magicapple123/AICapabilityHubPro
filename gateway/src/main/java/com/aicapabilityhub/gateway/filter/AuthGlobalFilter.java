package com.aicapabilityhub.gateway.filter;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.aicapabilityhub.gateway.security.JwtIdentity;
import com.aicapabilityhub.gateway.security.JwtService;
import com.aicapabilityhub.gateway.security.TrustedIdentityHeaders;
import com.aicapabilityhub.gateway.security.InternalPaths;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class AuthGlobalFilter implements GlobalFilter, Ordered {

    private static final Logger LOGGER = LoggerFactory.getLogger(AuthGlobalFilter.class);
    private static final String SERVICE_NAME = "api-gateway";
    public static final String HEADER_USER_ID = "X-User-Id";
    public static final String HEADER_USER_NAME = "X-User-Name";
    public static final String HEADER_REQUEST_ID = "X-Request-Id";
    public static final String ATTRIBUTE_REQUEST_ID =
            AuthGlobalFilter.class.getName() + ".requestId";

    private static final String BEARER_PREFIX = "Bearer ";
    private final JwtService jwtService;
    private final ObjectMapper objectMapper;

    public AuthGlobalFilter(JwtService jwtService, ObjectMapper objectMapper) {
        this.jwtService = jwtService;
        this.objectMapper = objectMapper;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String path = exchange.getRequest().getURI().getPath();
        // 外部请求标识只能由网关生成，不能信任客户端传入值；后续可安全用于链路追踪与幂等键。
        String requestId = UUID.randomUUID().toString();
        exchange.getAttributes().put(ATTRIBUTE_REQUEST_ID, requestId);
        exchange.getResponse().getHeaders().set(HEADER_REQUEST_ID, requestId);

        // 服务发现定位器同样能暴露路径，因此任意层级的 internal 段都必须拦截。
        if (isInternalPath(path)) {
            return withAccessLog(
                    writeError(exchange, HttpStatus.FORBIDDEN, 1001, "禁止访问内部接口", requestId),
                    exchange, requestId, "anonymous");
        }

        boolean exchangePath = "/api/user/apikeys/exchange".equals(path)
                && exchange.getRequest().getMethod() == org.springframework.http.HttpMethod.POST;
        if (exchangePath || isWhitePath(path) || exchange.getRequest().getMethod() == org.springframework.http.HttpMethod.OPTIONS) {
            return withAccessLog(
                    chain.filter(withIdentityHeaders(exchange, null, requestId)),
                    exchange, requestId, "anonymous");
        }

        String token = extractBearerToken(exchange.getRequest().getHeaders().getFirst(HttpHeaders.AUTHORIZATION));
        if (token == null) {
            return withAccessLog(unauthorized(exchange, requestId), exchange, requestId, "anonymous");
        }

        try {
            JwtIdentity identity = jwtService.parse(token);
            return withAccessLog(
                    chain.filter(withIdentityHeaders(exchange, identity, requestId)),
                    exchange, requestId, identity.userId());
        } catch (RuntimeException exception) {
            return withAccessLog(unauthorized(exchange, requestId), exchange, requestId, "anonymous");
        }
    }

    private Mono<Void> withAccessLog(
            Mono<Void> result, ServerWebExchange exchange, String requestId, String userId) {
        return result.doFinally(signal -> LOGGER.info(
                "requestId={} userId={} serviceName={} method={} path={} status={}",
                requestId,
                userId,
                SERVICE_NAME,
                exchange.getRequest().getMethod(),
                exchange.getRequest().getURI().getPath(),
                exchange.getResponse().getStatusCode()));
    }

    private Mono<Void> unauthorized(ServerWebExchange exchange, String requestId) {
        return writeError(exchange, HttpStatus.UNAUTHORIZED, 1001, "未认证或登录已过期", requestId);
    }

    private ServerWebExchange withIdentityHeaders(
            ServerWebExchange exchange, JwtIdentity identity, String requestId) {
        ServerHttpRequest request = exchange.getRequest().mutate()
                .headers(headers -> {
                    TrustedIdentityHeaders.replace(headers, identity, requestId);
                })
                .build();
        return exchange.mutate().request(request).build();
    }

    private boolean isWhitePath(String path) {
        return isExactPath(path, "/api/user/register")
                || isExactPath(path, "/api/user/login")
                || isPathOrChild(path, "/api/capability/market")
                // OpenAI 兼容层自带 API Key 校验，不依赖平台 JWT。
                || isPathOrChild(path, "/v1")
                || isHealthPath(path);
    }

    private boolean isInternalPath(String path) {
        return InternalPaths.containsInternalSegment(path);
    }

    private boolean isHealthPath(String path) {
        String normalized = normalizePath(path);
        return normalized.equals("/health") || normalized.endsWith("/health");
    }

    private boolean isExactPath(String path, String expected) {
        return normalizePath(path).equals(expected);
    }

    private boolean isPathOrChild(String path, String prefix) {
        String normalized = normalizePath(path);
        return normalized.equals(prefix) || normalized.startsWith(prefix + "/");
    }

    private String normalizePath(String path) {
        if (path == null || path.isBlank()) {
            return "/";
        }
        if (path.length() > 1 && path.endsWith("/")) {
            return path.substring(0, path.length() - 1);
        }
        return path;
    }

    private String extractBearerToken(String authorization) {
        if (!StringUtils.hasText(authorization)
                || authorization.length() <= BEARER_PREFIX.length()
                || !authorization.regionMatches(true, 0, BEARER_PREFIX, 0, BEARER_PREFIX.length())) {
            return null;
        }
        String token = authorization.substring(BEARER_PREFIX.length()).trim();
        return StringUtils.hasText(token) ? token : null;
    }

    private Mono<Void> writeError(
            ServerWebExchange exchange, HttpStatus status, int code, String message, String requestId) {
        if (exchange.getResponse().isCommitted()) {
            return exchange.getResponse().setComplete();
        }

        byte[] body;
        try {
            body = objectMapper.writeValueAsBytes(new ErrorResult(code, message, null, requestId));
        } catch (JsonProcessingException exception) {
            body = ("{\"code\":" + code + ",\"message\":\"" + message
                    + "\",\"data\":null,\"requestId\":\"" + requestId + "\"}")
                    .getBytes(StandardCharsets.UTF_8);
        }

        exchange.getResponse().setStatusCode(status);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        exchange.getResponse().getHeaders().set(HEADER_REQUEST_ID, requestId);
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(body);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }

    @Override
    public int getOrder() {
        return -100;
    }

    private record ErrorResult(int code, String message, Object data, String requestId) {
    }
}

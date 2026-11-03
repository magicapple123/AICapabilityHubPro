package com.aicapabilityhub.gateway.security;

import java.util.ArrayList;
import java.util.Locale;

import org.springframework.http.HttpHeaders;

/** 可信头只有一个写入点；JWT role 不代替业务服务的实时管理员授权。 */
public final class TrustedIdentityHeaders {
    public static final String ROLE = "X-User-Role";

    private TrustedIdentityHeaders() {
    }

    public static void replace(HttpHeaders headers, JwtIdentity identity, String requestId) {
        for (String name : new ArrayList<>(headers.keySet())) {
            String lower = name.toLowerCase(Locale.ROOT);
            if (lower.startsWith("x-user-") || lower.equals("role")
                    || lower.equals("x-role") || lower.equals("x-roles")
                    || lower.equals("x-forwarded-user") || lower.equals("x-request-id")) {
                headers.remove(name);
            }
        }
        headers.set("X-Request-Id", requestId);
        if (identity != null) {
            headers.set("X-User-Id", identity.userId());
            headers.set("X-User-Name", identity.userName());
            headers.set(ROLE, identity.role());
            // P6：Key 身份与其它 x-user-* 一样，只有网关能写入；外部伪造的同名头
            // 已在上面被统一剥离，因此下游可以无条件信任这个值。
            if (identity.apiKeyId() != null && !identity.apiKeyId().isBlank()) {
                headers.set("X-User-Key-Id", identity.apiKeyId());
            }
        }
    }
}

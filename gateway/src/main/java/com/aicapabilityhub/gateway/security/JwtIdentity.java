package com.aicapabilityhub.gateway.security;

/**
 * 网关解析出的调用者身份。
 *
 * <p>{@code apiKeyId} 只在「用 API Key 换来的短 JWT」上才有值：它来自令牌的
 * {@code key_id} claim，网关把它写成 {@code X-User-Key-Id} 供下游记账归因（P6）。
 * 普通登录令牌该字段为 {@code null}，语义是「这次调用没有 Key 身份」。
 */
public record JwtIdentity(String userId, String userName, String role, String apiKeyId) {
    public JwtIdentity(String userId, String userName) {
        this(userId, userName, "user", null);
    }

    public JwtIdentity(String userId, String userName, String role) {
        this(userId, userName, role, null);
    }
}

package com.aicapabilityhub.gateway.security;

public record JwtIdentity(String userId, String userName, String role) {
    public JwtIdentity(String userId, String userName) {
        this(userId, userName, "user");
    }
}

package com.aicapabilityhub.gateway.config;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "security.jwt")
public record JwtProperties(
        String secret,
        /* F2：轮换期并行接受的上一把密钥；为空表示未在轮换。 */
        String previousSecret,
        String issuer,
        Duration ttl
) {
}

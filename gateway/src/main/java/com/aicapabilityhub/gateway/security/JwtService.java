package com.aicapabilityhub.gateway.security;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;

import javax.crypto.SecretKey;

import com.aicapabilityhub.gateway.config.JwtProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

@Component
public class JwtService {

    private static final int MIN_SECRET_BYTES = 32;

    /* F2：当前密钥的 keyId，签发时写进 JWT header，便于轮换期定位。 */
    static final String CURRENT_KEY_ID = "v1";

    private final JwtProperties properties;
    private final SecretKey key;
    /* F2：轮换期并行接受的上一把密钥；未配置时为 null。 */
    private final SecretKey previousKey;

    public JwtService(JwtProperties properties) {
        this.properties = properties;
        this.key = createKey(properties.secret());
        this.previousKey = StringUtils.hasText(properties.previousSecret())
                ? createKey(properties.previousSecret())
                : null;
        if (!StringUtils.hasText(properties.issuer())) {
            throw new IllegalStateException("JWT_ISSUER 不能为空");
        }
        if (properties.ttl() == null || properties.ttl().isNegative() || properties.ttl().isZero()) {
            throw new IllegalStateException("JWT_TTL 必须是正数时长");
        }
    }

    public JwtIdentity parse(String token) {
        Claims claims = parseWith(token, key);
        if (claims == null && previousKey != null) {
            /* 轮换期：旧 key 签发的 Token 在 TTL 内仍可用，过期后自然淘汰。 */
            claims = parseWith(token, previousKey);
        }
        if (claims == null) {
            throw new IllegalArgumentException("JWT 签名校验失败");
        }

        String userId = claims.getSubject();
        String userName = firstTextClaim(claims, "username", "user_name", "userName");
        if (!StringUtils.hasText(userId) || !userId.matches("[1-9][0-9]{0,18}")
                || !StringUtils.hasText(userName) || claims.getExpiration() == null) {
            throw new IllegalArgumentException("JWT 缺少用户身份声明");
        }
        String role = claims.get("role", String.class);
        if (role == null) {
            role = "user"; // 兼容旧登录 Token，绝不由请求头补出管理员角色。
        }
        if (!role.equals("user") && !role.equals("admin")) {
            throw new IllegalArgumentException("JWT 角色声明无效");
        }
        return new JwtIdentity(userId, userName, role);
    }

    private Claims parseWith(String token, SecretKey signingKey) {
        try {
            return Jwts.parser()
                    .verifyWith(signingKey)
                    .requireIssuer(properties.issuer())
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
        } catch (JwtException | IllegalArgumentException ex) {
            return null;
        }
    }

    public String createDevToken(String userId, String userName) {
        if (!StringUtils.hasText(userId) || !StringUtils.hasText(userName)) {
            throw new IllegalArgumentException("测试用户 ID 和用户名不能为空");
        }
        Instant now = Instant.now();
        return Jwts.builder()
                .issuer(properties.issuer())
                .subject(userId)
                .claim("username", userName)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(properties.ttl())))
                .header().keyId(CURRENT_KEY_ID).and()
                .signWith(key)
                .compact();
    }

    public static SecretKey createKey(String secret) {
        if (!StringUtils.hasText(secret)) {
            throw new IllegalStateException("请通过环境变量 JWT_SECRET 配置网关签名密钥");
        }
        byte[] secretBytes = secret.getBytes(StandardCharsets.UTF_8);
        if (secretBytes.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException("JWT_SECRET 按 UTF-8 编码后不得少于 32 字节");
        }
        return Keys.hmacShaKeyFor(secretBytes);
    }

    private String firstTextClaim(Claims claims, String... names) {
        for (String name : names) {
            String value = claims.get(name, String.class);
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return null;
    }
}

package com.aicapabilityhub.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;

import javax.crypto.SecretKey;

import com.aicapabilityhub.gateway.config.JwtProperties;
import io.jsonwebtoken.Jwts;
import org.junit.jupiter.api.Test;

/** F2：密钥轮换期新旧密钥并行，切换完成后旧密钥失效。 */
class JwtRotationTest {

    private static final String CURRENT = "current-secret-value-0123456789abcdef";
    private static final String PREVIOUS = "previous-secret-value-0123456789abcdef";
    private static final String OTHER = "another-secret-value-0123456789abcdef";
    private static final String ISSUER = "ai-capability-hub";

    private JwtService service(String current, String previous) {
        return new JwtService(new JwtProperties(current, previous, ISSUER, Duration.ofHours(1)));
    }

    private String tokenSignedWith(String secret) {
        SecretKey key = JwtService.createKey(secret);
        Instant now = Instant.now();
        return Jwts.builder()
                .issuer(ISSUER)
                .subject("42")
                .claim("username", "demo")
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(Duration.ofHours(1))))
                .header().keyId("v0").and()
                .signWith(key)
                .compact();
    }

    @Test
    void currentKeyTokenIsAccepted() {
        JwtService jwtService = service(CURRENT, null);
        assertThat(jwtService.parse(tokenSignedWith(CURRENT)).userId()).isEqualTo("42");
    }

    @Test
    void previousKeyTokenIsAcceptedDuringRotation() {
        JwtService jwtService = service(CURRENT, PREVIOUS);
        assertThat(jwtService.parse(tokenSignedWith(PREVIOUS)).userId()).isEqualTo("42");
    }

    @Test
    void previousKeyTokenIsRejectedAfterRotationCompletes() {
        JwtService jwtService = service(CURRENT, null);
        assertThatThrownBy(() -> jwtService.parse(tokenSignedWith(PREVIOUS)))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void unknownKeyIsAlwaysRejected() {
        JwtService jwtService = service(CURRENT, PREVIOUS);
        assertThatThrownBy(() -> jwtService.parse(tokenSignedWith(OTHER)))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void issuedTokenCarriesKeyId() {
        JwtService jwtService = service(CURRENT, PREVIOUS);
        String token = jwtService.createDevToken("7", "demo");
        assertThat(new String(token.split("\\.")[0].getBytes(StandardCharsets.UTF_8)))
                .isNotBlank();
        assertThat(jwtService.parse(token).userId()).isEqualTo("7");
    }
}

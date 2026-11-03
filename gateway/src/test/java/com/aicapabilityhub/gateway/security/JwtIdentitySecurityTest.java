package com.aicapabilityhub.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Duration;
import java.time.Instant;
import java.util.Date;

import com.aicapabilityhub.gateway.config.JwtProperties;
import io.jsonwebtoken.Jwts;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class JwtIdentitySecurityTest {
    private static final String SECRET = "leader-test-secret-with-at-least-32-bytes";
    private final JwtService service = new JwtService(
            new JwtProperties(SECRET, null, "ai-capability-hub", Duration.ofHours(1)));

    private String token(String userId, String role, boolean expires) {
        var builder = Jwts.builder().issuer("ai-capability-hub")
                .subject(userId).claim("username", "tester");
        if (role != null) {
            builder.claim("role", role);
        }
        if (expires) {
            builder.expiration(Date.from(Instant.now().plusSeconds(300)));
        }
        return builder.signWith(JwtService.createKey(SECRET)).compact();
    }

    @Test
    void legacyTokenDefaultsToUserAndSignedAdminClaimIsRetained() {
        assertThat(service.parse(token("42", null, true)).role()).isEqualTo("user");
        assertThat(service.parse(token("42", "admin", true)).role()).isEqualTo("admin");
    }

    @ParameterizedTest
    @ValueSource(strings = {"0", "-1", "anonymous", "01", "1\r\nX-Role:admin"})
    void rejectsInvalidSubjects(String subject) {
        assertThatThrownBy(() -> service.parse(token(subject, "user", true)))
                .isInstanceOf(RuntimeException.class);
    }

    @Test
    void rejectsUnknownRoleAndMissingExpiry() {
        assertThatThrownBy(() -> service.parse(token("1", "super-admin", true)))
                .isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> service.parse(token("1", "user", false)))
                .isInstanceOf(RuntimeException.class);
    }

    private String keyToken(Object keyId) {
        return Jwts.builder().issuer("ai-capability-hub")
                .subject("42").claim("username", "tester")
                .claim("key_id", keyId)
                .expiration(Date.from(Instant.now().plusSeconds(300)))
                .signWith(JwtService.createKey(SECRET)).compact();
    }

    @Test
    void apiKeyIdClaimIsCarriedButNeverTrustedForRole() {
        assertThat(service.parse(keyToken(7)).apiKeyId()).isEqualTo("7");
        // 非法 key_id 只影响归因，不影响请求本身：当成「没有 Key 身份」。
        assertThat(service.parse(keyToken("abc")).apiKeyId()).isNull();
        assertThat(service.parse(keyToken(0)).apiKeyId()).isNull();
        assertThat(service.parse(token("42", "user", true)).apiKeyId()).isNull();
    }

    @Test
    void forgedKeyHeaderIsStrippedAndOnlyGatewayWritesIt() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-User-Key-Id", "999");
        headers.set("X-User-Id", "888");
        TrustedIdentityHeaders.replace(
                headers, new JwtIdentity("42", "tester", "user", "7"), "req-1");
        assertThat(headers.getFirst("X-User-Key-Id")).isEqualTo("7");
        assertThat(headers.getFirst("X-User-Id")).isEqualTo("42");

        HttpHeaders withoutKey = new HttpHeaders();
        withoutKey.set("X-User-Key-Id", "999");
        TrustedIdentityHeaders.replace(
                withoutKey, new JwtIdentity("42", "tester", "user", null), "req-2");
        assertThat(withoutKey.containsKey("X-User-Key-Id")).isFalse();
    }
}

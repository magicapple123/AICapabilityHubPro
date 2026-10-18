package com.aicapabilityhub.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Duration;
import java.time.Instant;
import java.util.Date;

import com.aicapabilityhub.gateway.config.JwtProperties;
import io.jsonwebtoken.Jwts;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class JwtIdentitySecurityTest {
    private static final String SECRET = "leader-test-secret-with-at-least-32-bytes";
    private final JwtService service = new JwtService(
            new JwtProperties(SECRET, "ai-capability-hub", Duration.ofHours(1)));

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
}

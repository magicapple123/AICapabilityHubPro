package com.aicapabilityhub.gateway.tool;

import java.time.Duration;

import com.aicapabilityhub.gateway.config.JwtProperties;
import com.aicapabilityhub.gateway.security.JwtIdentity;
import com.aicapabilityhub.gateway.security.JwtService;

/**
 * 仅供本地联调生成测试 JWT。生产环境必须由用户服务签发令牌。
 */
public final class DevTokenTool {

    private static final String DEFAULT_ISSUER = "ai-capability-hub";
    private static final String DEFAULT_TTL = "PT24H";

    private DevTokenTool() {
    }

    public static void main(String[] args) {
        String userId = args.length > 0 ? args[0] : "1";
        String userName = args.length > 1 ? args[1] : "dev-user";
        String secret = System.getenv("JWT_SECRET");
        String issuer = environmentOrDefault("JWT_ISSUER", DEFAULT_ISSUER);
        Duration ttl = Duration.parse(environmentOrDefault("JWT_TTL", DEFAULT_TTL));

        JwtService jwtService = new JwtService(new JwtProperties(secret, null, issuer, ttl));
        String token = jwtService.createDevToken(userId, userName);
        JwtIdentity verified = jwtService.parse(token);

        System.out.println("测试 JWT：");
        System.out.println(token);
        System.out.printf("校验通过：user_id=%s, username=%s%n", verified.userId(), verified.userName());
    }

    private static String environmentOrDefault(String name, String defaultValue) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? defaultValue : value;
    }
}

package com.aicapabilityhub.gateway.config;

import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 网关限流规则配置（`gateway.rate-limit.*`）。
 *
 * <p>规则在启动时由 {@link GatewayRateLimitInitializer} 载入 Sentinel，
 * 阈值全部走配置或环境变量，禁止在代码里写死；`enabled=false` 时不加载任何规则，
 * 便于本地排障时临时关闭限流。</p>
 *
 * @param enabled 是否启用启动时加载限流规则
 * @param rules 按路由 ID 维度的 QPS 规则
 */
@ConfigurationProperties(prefix = "gateway.rate-limit")
public record GatewayRateLimitProperties(boolean enabled, List<Rule> rules) {

    public GatewayRateLimitProperties {
        rules = rules == null ? List.of() : List.copyOf(rules);
    }

    /**
     * 单条限流规则。
     *
     * @param resource 路由 ID（与 `spring.cloud.gateway.routes[].id` 一致）
     * @param count 统计窗口内允许的请求数（QPS）
     * @param intervalSec 统计窗口秒数，1 表示 QPS
     */
    public record Rule(String resource, double count, int intervalSec) {
    }
}

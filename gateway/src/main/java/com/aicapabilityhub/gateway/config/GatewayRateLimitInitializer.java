package com.aicapabilityhub.gateway.config;

import java.util.HashSet;
import java.util.Set;

import com.alibaba.csp.sentinel.adapter.gateway.common.SentinelGatewayConstants;
import com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayFlowRule;
import com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayRuleManager;
import com.alibaba.csp.sentinel.slots.block.RuleConstant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.stereotype.Component;

/**
 * 启动时把 `gateway.rate-limit` 配置转换为 Sentinel 网关限流规则。
 *
 * <p>资源维度使用 {@link SentinelGatewayConstants#RESOURCE_MODE_ROUTE_ID}，
 * 即按路由 ID（= 服务名）限流，例如 `ai-chat-service` 对应 `/api/chat/**`。
 * 触发限流时由 {@link SentinelGatewayConfiguration} 返回统一的 429 + `code=4001`。</p>
 */
@Component
public class GatewayRateLimitInitializer implements InitializingBean {

    private static final Logger log = LoggerFactory.getLogger(GatewayRateLimitInitializer.class);

    private final GatewayRateLimitProperties properties;

    public GatewayRateLimitInitializer(GatewayRateLimitProperties properties) {
        this.properties = properties;
    }

    @Override
    public void afterPropertiesSet() {
        if (!properties.enabled()) {
            log.warn("网关限流规则已通过配置关闭（gateway.rate-limit.enabled=false）");
            return;
        }

        Set<GatewayFlowRule> rules = new HashSet<>();
        for (GatewayRateLimitProperties.Rule rule : properties.rules()) {
            if (rule.resource() == null || rule.resource().isBlank() || rule.count() <= 0) {
                log.warn("忽略非法的限流规则配置 resource={} count={}", rule.resource(), rule.count());
                continue;
            }
            rules.add(new GatewayFlowRule(rule.resource())
                    .setResourceMode(SentinelGatewayConstants.RESOURCE_MODE_ROUTE_ID)
                    .setGrade(RuleConstant.FLOW_GRADE_QPS)
                    .setCount(rule.count())
                    .setIntervalSec(rule.intervalSec()));
        }

        GatewayRuleManager.loadRules(rules);
        log.info("已加载 {} 条网关限流规则", rules.size());
    }
}

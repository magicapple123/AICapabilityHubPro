package com.aicapabilityhub.gateway.config;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Set;

import com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayFlowRule;
import com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayRuleManager;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

class GatewayRateLimitInitializerTest {

    @AfterEach
    void clearRules() {
        GatewayRuleManager.loadRules(Set.of());
    }

    @Test
    void loadsConfiguredRouteRules() {
        GatewayRateLimitProperties properties = new GatewayRateLimitProperties(
                true,
                List.of(
                        new GatewayRateLimitProperties.Rule("ai-chat-service", 20, 1),
                        new GatewayRateLimitProperties.Rule("user-service", 50, 1)));

        new GatewayRateLimitInitializer(properties).afterPropertiesSet();

        Set<GatewayFlowRule> rules = GatewayRuleManager.getRules();
        assertThat(rules).hasSize(2);
        assertThat(rules)
                .anySatisfy(rule -> {
                    assertThat(rule.getResource()).isEqualTo("ai-chat-service");
                    assertThat(rule.getCount()).isEqualTo(20);
                    assertThat(rule.getIntervalSec()).isEqualTo(1);
                });
    }

    @Test
    void skipsRulesWhenDisabled() {
        GatewayRateLimitProperties properties = new GatewayRateLimitProperties(
                false, List.of(new GatewayRateLimitProperties.Rule("ai-chat-service", 20, 1)));

        new GatewayRateLimitInitializer(properties).afterPropertiesSet();

        assertThat(GatewayRuleManager.getRules()).isEmpty();
    }

    @Test
    void ignoresInvalidRules() {
        GatewayRateLimitProperties properties = new GatewayRateLimitProperties(
                true,
                List.of(
                        new GatewayRateLimitProperties.Rule(" ", 20, 1),
                        new GatewayRateLimitProperties.Rule("user-service", 0, 1)));

        new GatewayRateLimitInitializer(properties).afterPropertiesSet();

        assertThat(GatewayRuleManager.getRules()).isEmpty();
    }
}

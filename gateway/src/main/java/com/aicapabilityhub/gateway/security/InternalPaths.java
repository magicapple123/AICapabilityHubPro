package com.aicapabilityhub.gateway.security;

import java.nio.charset.StandardCharsets;
import org.springframework.web.util.UriUtils;

/** 对路由前后、服务发现别名和编码路径采用同一隔离规则。 */
public final class InternalPaths {
    private InternalPaths() {
    }

    public static boolean containsInternalSegment(String path) {
        if (path == null) {
            return false;
        }
        String decoded = path;
        for (int i = 0; i < 4 && decoded.contains("%"); i++) {
            try {
                String next = UriUtils.decode(decoded, StandardCharsets.UTF_8);
                if (next.equals(decoded)) {
                    break;
                }
                decoded = next;
            } catch (IllegalArgumentException invalidEncoding) {
                return true;
            }
        }
        for (String segment : decoded.replace('\\', '/').split("/")) {
            if (segment.equalsIgnoreCase("internal")) {
                return true;
            }
        }
        return false;
    }
}

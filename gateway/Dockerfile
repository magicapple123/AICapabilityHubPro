# AICapabilityHub Pro · Spring Cloud Gateway 镜像
#
# 构建上下文：**gateway/ 目录**（deploy/docker-compose.yml 里写的是 `build: ../gateway`）。
# 之所以不用仓库根：网关是独立 Maven 工程，上下文越小构建越快；
# 若换成仓库根，需要把下面所有 COPY 路径加上 `gateway/` 前缀：
#   COPY gateway/pom.xml . / COPY gateway/src ./src
#
# 本机手搓镜像：
#   docker build -t aihub-pro-gateway:local gateway
# 走 compose：
#   docker compose -f deploy/docker-compose.yml --profile app build gateway

# ---------------------------------------------------------------- 1. 构建阶段
FROM maven:3.9-eclipse-temurin-21 AS build

ARG MAVEN_MIRROR_URL=
RUN if [ -n "${MAVEN_MIRROR_URL}" ]; then \
      mkdir -p /root/.m2 && \
      printf '<settings><mirrors><mirror><id>configured-mirror</id><mirrorOf>*</mirrorOf><url>%s</url></mirror></mirrors></settings>' \
        "${MAVEN_MIRROR_URL}" > /root/.m2/settings.xml; \
    fi

WORKDIR /build

# 先只拷 pom，依赖层可复用缓存；改源码时不会重新拉一遍整个依赖树。
COPY pom.xml ./
RUN mvn -B -q -ntp dependency:go-offline

COPY src ./src
# 测试在 CI / 本地 `mvn test` 里跑，镜像构建只产出可运行 jar。
RUN mvn -B -q -ntp -DskipTests package

# ---------------------------------------------------------------- 2. 运行阶段
FROM eclipse-temurin:21-jre

# 网关自身没有 actuator，健康检查走 curl 打业务探针，因此装 curl（约 1MB）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 非 root 运行：容器被攻破时不能直接改镜像内文件。
RUN groupadd --system --gid 10001 aihub \
    && useradd --system --uid 10001 --gid aihub --home-dir /app aihub

WORKDIR /app

# target 下同时存在 *.jar 与 *.jar.original，glob 只会命中前者。
COPY --from=build /build/target/*.jar /app/app.jar

RUN chown -R aihub:aihub /app
USER aihub

# JVM 参数走 JAVA_TOOL_OPTIONS（JVM 自动读取），这样 ENTRYPOINT 保持 exec 形式，
# java 是 PID 1，docker stop 的 SIGTERM 能直接到达 JVM，能优雅停机。
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75.0 -Dfile.encoding=UTF-8"
ENV TZ=Asia/Shanghai

EXPOSE 8080

ENTRYPOINT ["java","-jar","/app/app.jar"]

import importlib
import logging
import os
import random
import socket
import threading
from typing import Any, Protocol

import httpx
from loguru import logger

from app.core.config import model_runtime_config, settings


HEARTBEAT_INTERVAL_SECONDS = 5

# SDK 的 INFO 调试日志可能包含配置原文，统一提升级别以避免模型密钥进入日志。
logging.getLogger("nacos").setLevel(logging.WARNING)


class ServiceRegistry(Protocol):
    """注册发现协议，替换注册中心时只需实现该接口。"""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def discover_one(self, service_name: str) -> str: ...


class NacosRegister:
    """Nacos 注册、心跳和发现适配器。构造及模块导入阶段不访问网络。"""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._client_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._config_worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._registered = False
        self._last_model_config_content: str | None = None
        self._random = random.SystemRandom()

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    nacos = importlib.import_module("nacos")
                    # Python SDK 的公共命名空间 ID 为空字符串；配置文件仍可使用 public。
                    namespace_id = (
                        "" if settings.nacos_namespace.lower() == "public" else settings.nacos_namespace
                    )
                    self._client = nacos.NacosClient(
                        settings.nacos_addr,
                        namespace=namespace_id,
                    )
        return self._client

    def _advertise_host(self) -> str:
        """返回其它容器真的能连上的地址。

        容器里 `service_host` 默认是 127.0.0.1，注册上去等于告诉别人"连你自己"，
        网关/兄弟服务按这个地址调用必然 4002（G2 整栈联调实测）。优先级：
        显式配置 > SERVICE_REGISTER_IP > 容器自身 IP > 回退 127.0.0.1（本地开发）。
        """

        host = settings.service_host
        if host not in ("127.0.0.1", "localhost", "0.0.0.0"):
            return host
        override = os.getenv("SERVICE_REGISTER_IP", "").strip()
        if override:
            return override
        # 本地多进程开发：127.0.0.1 就是对的，别改成局域网 IP（换网卡/断网会连带注册失效）。
        if not os.path.exists("/.dockerenv"):
            return host
        try:
            resolved = socket.gethostbyname(socket.gethostname())
        except OSError:
            return host
        return resolved if resolved and not resolved.startswith("127.") else host

    def _register(self) -> None:
        self._get_client().add_naming_instance(
            settings.service_name,
            self._advertise_host(),
            settings.service_port,
            cluster_name=settings.nacos_cluster,
            group_name=settings.nacos_group,
            healthy=True,
            ephemeral=True,
        )
        self._registered = True
        logger.info(
            "已注册到 Nacos service={} address={}:{}",
            settings.service_name,
            self._advertise_host(),
            settings.service_port,
        )

    def _heartbeat(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._registered:
                    self._register()
                else:
                    self._get_client().send_heartbeat(
                        settings.service_name,
                        self._advertise_host(),
                        settings.service_port,
                        cluster_name=settings.nacos_cluster,
                        group_name=settings.nacos_group,
                        ephemeral=True,
                    )
            except Exception as exc:
                self._registered = False
                logger.warning("Nacos 注册或心跳失败，将自动重试: {}", exc)
            self._stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)

    def _watch_model_config(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._refresh_model_config()
            except Exception as exc:
                # 不输出异常详情，避免 SDK 错误中意外带出配置内容。
                logger.warning("Nacos 模型配置读取失败，将自动重试: {}", type(exc).__name__)
            self._stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)

    def _model_config_data_id(self) -> str:
        return settings.nacos_model_config_data_id or f"{settings.service_name}-model.json"

    def _nacos_config_urls(self) -> list[str]:
        urls: list[str] = []
        for address in settings.nacos_addr.split(","):
            base_url = address.strip().rstrip("/")
            if not base_url:
                continue
            if not base_url.startswith(("http://", "https://")):
                base_url = f"http://{base_url}"
            suffix = "/v1/cs/configs" if base_url.endswith("/nacos") else "/nacos/v1/cs/configs"
            urls.append(f"{base_url}{suffix}")
        if not urls:
            raise ValueError("NACOS_ADDR 未配置有效地址")
        return urls

    def _fetch_model_config(self) -> str | None:
        params = {
            "dataId": self._model_config_data_id(),
            "group": settings.nacos_group,
        }
        if settings.nacos_namespace and settings.nacos_namespace.lower() != "public":
            params["tenant"] = settings.nacos_namespace

        last_error: Exception | None = None
        for url in self._nacos_config_urls():
            try:
                response = httpx.get(url, params=params, timeout=settings.nacos_config_timeout)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return None

    def _apply_model_config(self, raw_content: str) -> None:
        if not raw_content.strip():
            logger.warning("Nacos 模型配置为空，继续使用最近一次有效配置")
            return
        try:
            fields = model_runtime_config.update_from_json(raw_content)
        except (TypeError, ValueError):
            logger.warning("Nacos 模型配置格式无效，继续使用最近一次有效配置")
            return
        logger.info(
            "Nacos 模型配置已更新 dataId={} fields={}",
            self._model_config_data_id(),
            ",".join(sorted(fields)),
        )

    def _refresh_model_config(self) -> None:
        if not settings.nacos_model_config_enabled:
            return
        # 配置接口独立于注册发现 SDK，避免 SDK 默认快照将模型 Key 写入工作区。
        content = self._fetch_model_config()
        if not content or content == self._last_model_config_content:
            return
        self._last_model_config_content = content
        self._apply_model_config(content)

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._heartbeat,
            name=f"{settings.service_name}-nacos-heartbeat",
            daemon=True,
        )
        self._worker.start()
        if settings.nacos_model_config_enabled:
            self._config_worker = threading.Thread(
                target=self._watch_model_config,
                name=f"{settings.service_name}-nacos-config",
                daemon=True,
            )
            self._config_worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=HEARTBEAT_INTERVAL_SECONDS + 1)
        if self._config_worker is not None:
            self._config_worker.join(timeout=HEARTBEAT_INTERVAL_SECONDS + 1)
        if self._registered:
            try:
                self._get_client().remove_naming_instance(
                    settings.service_name,
                    settings.service_host,
                    settings.service_port,
                    cluster_name=settings.nacos_cluster,
                    group_name=settings.nacos_group,
                    ephemeral=True,
                )
            except Exception as exc:
                logger.warning("Nacos 注销失败: {}", exc)
        self._registered = False

    def discover_one(self, service_name: str) -> str:
        data = self._get_client().list_naming_instance(
            service_name,
            group_name=settings.nacos_group,
            clusters=settings.nacos_cluster,
            healthy_only=True,
        )
        hosts = [
            host
            for host in data.get("hosts", [])
            if host.get("healthy") and host.get("enabled", True)
        ]
        if not hosts:
            raise RuntimeError(f"未发现健康服务实例: {service_name}")
        host = self._random.choice(hosts)
        return f"http://{host['ip']}:{host['port']}"


nacos_register: ServiceRegistry = NacosRegister()

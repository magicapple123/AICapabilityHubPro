import json
import threading
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服务运行配置，环境变量名称与字段名一一对应。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "capability-service"
    service_host: str = "127.0.0.1"
    service_port: int = 8082

    nacos_addr: str = "127.0.0.1:8848"
    nacos_namespace: str = "public"
    nacos_group: str = "DEFAULT_GROUP"
    nacos_cluster: str = "DEFAULT"
    nacos_model_config_enabled: bool = False
    nacos_model_config_data_id: str = ""
    nacos_config_timeout: float = Field(default=5.0, gt=0)

    db_url: str = "mysql+pymysql://root:root@127.0.0.1:3306/capability_db?charset=utf8mb4"
    # A2 连接池参数化：容量公式 4 服务 × UVICORN_WORKERS × (pool+overflow)，
    # 生产 4 worker 时为 4×4×15=240，故 MySQL max_connections 必须 ≥300。
    # D2：保存阶段向 ai-chat 校验 provider 绑定
    ai_chat_service_name: str = "ai-chat-service"
    # A3：目录缓存失效通知开关；本地/单测关闭后不发起跨服务调用
    enable_internal_chain: bool = True
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout: int = Field(default=30, ge=1, le=300)
    db_pool_recycle: int = Field(default=1800, ge=-1)
    uvicorn_workers: int = Field(default=1, ge=1, le=16)
    internal_call_timeout: float = Field(default=10.0, gt=0)

    # 运营权限由 user-service 实时判定；本服务不跨库读取角色。
    user_service_name: str = "user-service"

    use_mock: bool = True
    model_base_url: str = "https://api.example.com/v1"
    model_api_key: str = "replace-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


class ModelRuntimeSettings(BaseModel):
    """可由 Nacos 热更新的模型配置快照。"""

    model_config = ConfigDict(extra="ignore", frozen=True)

    use_mock: bool
    model_base_url: str
    model_api_key: str


class ModelRuntimeConfig:
    """以不可变快照方式更新配置，避免请求线程读到一半更新的数据。"""

    def __init__(self, initial: ModelRuntimeSettings) -> None:
        self._value = initial
        self._lock = threading.RLock()

    def snapshot(self) -> ModelRuntimeSettings:
        with self._lock:
            return self._value

    def update_from_json(self, raw_content: str) -> set[str]:
        payload: Any = json.loads(raw_content)
        if not isinstance(payload, dict):
            raise ValueError("Nacos 模型配置必须是 JSON 对象")
        current = self.snapshot().model_dump()
        updated = ModelRuntimeSettings.model_validate({**current, **payload})
        with self._lock:
            self._value = updated
        return set(payload).intersection(current)


model_runtime_config = ModelRuntimeConfig(
    ModelRuntimeSettings(
        use_mock=settings.use_mock,
        model_base_url=settings.model_base_url,
        model_api_key=settings.model_api_key,
    )
)

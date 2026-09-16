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

    service_name: str = "billing-service"
    service_host: str = "127.0.0.1"
    service_port: int = 8083

    nacos_addr: str = "127.0.0.1:8848"
    nacos_namespace: str = "public"
    nacos_group: str = "DEFAULT_GROUP"
    nacos_cluster: str = "DEFAULT"
    nacos_model_config_enabled: bool = False
    nacos_model_config_data_id: str = ""
    nacos_config_timeout: float = Field(default=5.0, gt=0)

    db_url: str = "mysql+pymysql://root:root@127.0.0.1:3306/billing_db?charset=utf8mb4"
    internal_call_timeout: float = Field(default=10.0, gt=0)

    # 扣分只能调用 user-service 的内部契约，不允许直接读写 user_db。
    user_service_name: str = "user-service"
    # 用量统计默认回看天数（未显式传 start_date / end_date 时生效）。
    stat_default_range_days: int = Field(default=30, ge=1)

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

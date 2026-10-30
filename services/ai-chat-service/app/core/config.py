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

    service_name: str = "ai-chat-service"
    service_host: str = "127.0.0.1"
    service_port: int = 8090

    nacos_addr: str = "127.0.0.1:8848"
    nacos_namespace: str = "public"
    nacos_group: str = "DEFAULT_GROUP"
    nacos_cluster: str = "DEFAULT"
    nacos_model_config_enabled: bool = True
    nacos_model_config_data_id: str = "ai-chat-service-model.json"
    nacos_config_timeout: float = Field(default=5.0, gt=0)

    db_url: str = "mysql+pymysql://root:root@127.0.0.1:3306/ai_chat_db?charset=utf8mb4"
    internal_call_timeout: float = Field(default=10.0, gt=0)
    # 内部链路开关：开启后按指南 11.2 调用 user 校验积分、调用 billing 上报计费。
    enable_internal_chain: bool = True
    user_service_name: str = "user-service"
    billing_service_name: str = "billing-service"
    points_cost: int = Field(default=1, ge=0)

    # 模型地址 / Key / USE_MOCK 由 Nacos 热更新（三个字段，见 README）；
    # 下面的对话参数走环境变量，属于部署期配置，不参与热更新。
    model_timeout: float = Field(default=30.0, gt=0)
    model_max_tokens: int = Field(default=1024, ge=1, le=32768)
    default_system_prompt: str = "你是一个严谨的中文 AI 助手，回答尽量简洁。"
    default_temperature: float = Field(default=0.7, ge=0, le=2)

    use_mock: bool = True
    model_base_url: str = "https://api.example.com/v1"
    model_api_key: str = "replace-me"
    # 服务端默认模型名。请求未显式指定 model 时使用；真实供应商要求模型名与其目录一致
    # （例如 deepseek-flash），留默认值只在 Mock/测试替身下有效。
    model_name: str = "mock-model"


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

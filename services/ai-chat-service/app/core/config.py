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
    # A2 连接池参数化：容量公式 4 服务 × UVICORN_WORKERS × (pool+overflow)，
    # 生产 4 worker 时为 4×4×15=240，故 MySQL max_connections 必须 ≥300。
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout: int = Field(default=30, ge=1, le=300)
    db_pool_recycle: int = Field(default=1800, ge=-1)
    uvicorn_workers: int = Field(default=1, ge=1, le=16)
    internal_call_timeout: float = Field(default=10.0, gt=0)
    # 内部链路开关：开启后按指南 11.2 调用 user 校验积分、调用 billing 上报计费。
    enable_internal_chain: bool = True
    user_service_name: str = "user-service"
    billing_service_name: str = "billing-service"
    points_cost: int = Field(default=1, ge=0)

    # 模型地址 / Key / USE_MOCK 由 Nacos 热更新（三个字段，见 README）；
    # 下面的对话参数走环境变量，属于部署期配置，不参与热更新。
    # A4：按用户限流；每 worker 一份桶，真实速率 ≈ qps × worker 数
    # D1：供应商地址白名单；之前只从 os.environ 读，.env 里的值不生效（已修）
    provider_allowed_hosts: str = ""
    # D1：供应商密钥的主密钥（base64 的 32 字节）；与白名单同样支持 .env
    provider_master_key_v1: str = ""
    rate_limit_enabled: bool = True
    rate_limit_qps: float = 5.0
    rate_limit_burst: int = 10
    # P16：一次调用的整体超时预算（入口算 deadline，向下只传"还剩多少"）。
    # 4 跳串联（目录 → 校验 → 模型 → 账单）最坏情况不得超过它。
    request_budget_seconds: float = Field(default=60.0, gt=0)
    # P16：按供应商 alias 的进程内熔断；状态不跨 worker（见 provider_breaker 文档）。
    provider_breaker_enabled: bool = True
    provider_breaker_failure_threshold: int = Field(default=5, ge=1, le=100)
    provider_cooldown_seconds: float = Field(default=30.0, ge=1)
    model_timeout: float = Field(default=30.0, gt=0)
    model_max_tokens: int = Field(default=1024, ge=1, le=32768)
    default_system_prompt: str = "你是一个严谨的中文 AI 助手，回答尽量简洁。"
    default_temperature: float = Field(default=0.7, ge=0, le=2)

    use_mock: bool = True
    model_base_url: str = "https://api.example.com/v1"
    model_api_key: str = "replace-me"

    # OpenAI 兼容层：外部客户端用 `Bearer sk_...`（平台 API Key 的 Secret）接入。
    # 校验走 user-service 内部接口，服务间令牌由共享 JWT_SECRET 派生，缺失时失败关闭。
    jwt_secret: str = ""
    openai_compat_enabled: bool = True
    # 形如 deepseek-flash=1，逗号分隔；等号右侧是 capability_id。
    openai_compat_model_map: str = "deepseek-flash=1,deepseek-chat=1,chat-completions=1"
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

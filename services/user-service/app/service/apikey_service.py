"""API Key 业务逻辑。

安全约束：
- `secret_key` 使用 `secrets.token_hex` 生成，只在创建响应中返回一次；
  库内只保存 SHA-256 摘要与展示掩码，任何列表/详情接口都不回传完整密钥；
- access_key 由随机数生成，理论上可能碰撞，这里做有限次重试并最终由
  `uk_api_key_access_key` 唯一索引兜底。
"""

import hashlib
import secrets

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import ACCESS_KEY_PREFIX, SECRET_KEY_PREFIX, ApiKeyStatus
from app.core.exceptions import BizException
from app.models import ApiKey, User
from app.repository import ApiKeyRepository, UserRepository
from app.repository import api_key_repository, user_repository
from app.schemas import ApiKeyCreateRequest
from app.service.user_service import require_available_user

# 生成随机凭据时的重试上限；正常情况一次成功。
_MAX_GENERATE_ATTEMPTS = 3

# access_key / secret_key 的随机部分字节数。
_ACCESS_KEY_BYTES = 12
_SECRET_KEY_BYTES = 24


def _mask_secret(secret_key: str) -> str:
    """展示掩码：保留前缀与末 4 位，中间不可还原。"""

    return f"{SECRET_KEY_PREFIX}****{secret_key[-4:]}"


def _hash_secret(secret_key: str) -> str:
    return hashlib.sha256(secret_key.encode("utf-8")).hexdigest()


class ApiKeyService:
    """API Key 的创建、查询与禁用。"""

    def __init__(
        self,
        api_keys: ApiKeyRepository | None = None,
        users: UserRepository | None = None,
    ) -> None:
        self.api_keys = api_keys or api_key_repository
        self.users = users or user_repository

    def create(
        self, db: Session, user_id: int, payload: ApiKeyCreateRequest
    ) -> tuple[ApiKey, str]:
        """创建 Key；返回 (实体, 完整 secret_key)。完整密钥不落库。

        被禁用账号不允许再签发新凭据：网关只认 Token，禁用后旧 Token 在有效期内
        仍可通过网关，因此这里必须自行校验账号状态（返回 1005）。
        """

        self._require_available_user(db, user_id)
        access_key = self._generate_access_key(db)
        secret_key = f"{SECRET_KEY_PREFIX}{secrets.token_hex(_SECRET_KEY_BYTES)}"

        api_key = ApiKey(
            user_id=user_id,
            name=payload.name,
            access_key=access_key,
            secret_hash=_hash_secret(secret_key),
            secret_mask=_mask_secret(secret_key),
            status=ApiKeyStatus.ENABLED.value,
            expire_time=payload.expire_time,
        )
        try:
            self.api_keys.add(db, api_key)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.warning("API Key 生成冲突 user_id={}", user_id)
            raise BizException(4003, "系统内部错误") from exc

        db.refresh(api_key)
        logger.info("API Key 已创建 key_id={} user_id={}", api_key.id, user_id)
        return api_key, secret_key

    def list_keys(self, db: Session, user_id: int) -> list[ApiKey]:
        self._require_available_user(db, user_id)
        return self.api_keys.list_by_user(db, user_id)

    def disable(self, db: Session, user_id: int, api_key_id: int) -> ApiKey:
        """禁用 Key；重复禁用幂等返回当前状态。

        他人 Key 与不存在的 Key 都返回 1006，不暴露资源是否存在。
        被禁用账号一律 1005：禁用 Key 属账号内操作，与其它接口保持同一放行规则，
        不做特例（吊销动作由运营在账号层面处理）。
        """

        self._require_available_user(db, user_id)
        api_key = self.api_keys.find_owned(db, api_key_id, user_id)
        if api_key is None:
            raise BizException(1006, "API Key 不存在")
        if api_key.status == ApiKeyStatus.DISABLED.value:
            return api_key

        self.api_keys.update_fields(db, api_key, {"status": ApiKeyStatus.DISABLED.value})
        db.commit()
        db.refresh(api_key)
        logger.info("API Key 已禁用 key_id={} user_id={}", api_key.id, user_id)
        return api_key

    def _require_available_user(self, db: Session, user_id: int) -> User:
        return require_available_user(db, user_id, self.users)

    def _generate_access_key(self, db: Session) -> str:
        for _ in range(_MAX_GENERATE_ATTEMPTS):
            candidate = f"{ACCESS_KEY_PREFIX}{secrets.token_hex(_ACCESS_KEY_BYTES)}"
            if not self.api_keys.exists_access_key(db, candidate):
                return candidate
        raise BizException(4003, "系统内部错误")


api_key_service = ApiKeyService()

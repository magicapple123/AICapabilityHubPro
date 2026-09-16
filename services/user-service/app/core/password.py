"""密码哈希与校验。

为什么不引入 bcrypt：开发指南 2.2 / 附录 A.2 锁定的依赖清单中没有 bcrypt，
按“禁止擅自增加或替换依赖”的约束，这里使用标准库 `hashlib.pbkdf2_hmac`
实现加盐慢哈希（PBKDF2-HMAC-SHA256），满足指南 5.5 “密码必须使用安全哈希、
不得明文存储”的要求。

存储格式（自描述，便于后续无痛提升迭代次数）：

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

校验使用 `hmac.compare_digest` 做常量时间比较，避免通过响应时间侧信道推断密码。
"""

import hashlib
import hmac
import secrets

# 迭代次数：本地演示环境取 24 万次，兼顾安全性与登录耗时。
PBKDF2_ITERATIONS = 240_000
SALT_BYTES = 16
ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """生成加盐哈希串；盐每次随机，相同密码得到不同哈希。"""

    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """校验明文密码；哈希串格式非法时直接判定失败，不抛异常。"""

    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$")
        if algorithm != ALGORITHM:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)

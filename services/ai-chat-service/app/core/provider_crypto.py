"""上游密钥的对称加密（D1）。

- 算法：AES-256-GCM，随机 12 字节 nonce，输出 `v1:<nonce_b64>:<ciphertext_b64>`；
- 主密钥来自环境变量 `PROVIDER_MASTER_KEY_V1`（base64 的 32 字节），**只在 ai-chat 内存中**；
- 带版本前缀是为了轮换：未来 `v2:` 用新 key 解，旧密文仍可读（F2 同源思路）；
- 解密结果绝不写日志、不进响应；对外只暴露 `api_key_mask`。

缺失或非法主密钥时**失败关闭**：加密/解密直接抛异常，不允许明文兜底。
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = "v1"
PREFIX = f"{VERSION}:"
NONCE_BYTES = 12


class ProviderKeyError(RuntimeError):
    """主密钥缺失/非法，或密文损坏。绝不回退到明文。"""


def _master_key() -> bytes:
    raw = os.environ.get("PROVIDER_MASTER_KEY_V1", "").strip()
    if not raw:
        raise ProviderKeyError("PROVIDER_MASTER_KEY_V1 is not configured")
    try:
        key = base64.b64decode(raw)
    except (ValueError, TypeError) as exc:
        raise ProviderKeyError("PROVIDER_MASTER_KEY_V1 must be base64") from exc
    if len(key) != 32:
        raise ProviderKeyError("PROVIDER_MASTER_KEY_V1 must decode to 32 bytes")
    return key


def encrypt(plaintext: str) -> str:
    """加密为 `v1:nonce:cipher`；空串直接拒绝，避免"空 Key"被当成已配置。"""

    if not plaintext:
        raise ProviderKeyError("api key must not be empty")
    nonce = os.urandom(NONCE_BYTES)
    cipher = AESGCM(_master_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"{PREFIX}{base64.b64encode(nonce).decode()}:{base64.b64encode(cipher).decode()}"


def decrypt(ciphertext: str) -> str:
    if not ciphertext.startswith(PREFIX):
        raise ProviderKeyError("unsupported cipher version")
    parts = ciphertext.split(":")
    if len(parts) != 3:
        raise ProviderKeyError("malformed ciphertext")
    try:
        nonce = base64.b64decode(parts[1])
        data = base64.b64decode(parts[2])
        return AESGCM(_master_key()).decrypt(nonce, data, None).decode("utf-8")
    except ProviderKeyError:
        raise
    except Exception as exc:  # noqa: BLE001 - 解密失败一律视为密文损坏
        raise ProviderKeyError("ciphertext cannot be decrypted") from exc


def mask(plaintext: str) -> str:
    """展示用掩码：只留后 4 位；过短的 Key 全部打码。"""

    if not plaintext:
        return ""
    if len(plaintext) <= 8:
        return "*" * len(plaintext)
    return f"{'*' * 8}{plaintext[-4:]}"


def fingerprint(plaintext: str) -> str:
    """SHA-256 前 12 位，用于判断"Key 是否换过"而不暴露内容。"""

    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:12]

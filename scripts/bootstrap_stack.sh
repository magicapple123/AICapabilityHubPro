#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/deploy/.env}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-aicapabilityhubpro}"
COMPOSE_FILE="$ROOT/deploy/docker-compose.yml"
ADMIN_USERNAME_OVERRIDE="${BOOTSTRAP_ADMIN_USERNAME:-}"
ADMIN_PASSWORD_OVERRIDE="${BOOTSTRAP_ADMIN_PASSWORD:-}"
ADMIN_POINTS_OVERRIDE="${BOOTSTRAP_ADMIN_POINTS:-}"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit "${2:-1}"
}

[[ -f "$ENV_FILE" ]] || fail "缺少环境文件：$ENV_FILE；先复制 deploy/.env.template 并填写必填项" 10
set -a
# Generated secrets in deploy/.env use shell-safe hex/base64 values.
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
if [[ -n "$ADMIN_PASSWORD_OVERRIDE" ]]; then
  BOOTSTRAP_ADMIN_PASSWORD="$ADMIN_PASSWORD_OVERRIDE"
fi
if [[ -n "$ADMIN_USERNAME_OVERRIDE" ]]; then
  BOOTSTRAP_ADMIN_USERNAME="$ADMIN_USERNAME_OVERRIDE"
fi
if [[ -n "$ADMIN_POINTS_OVERRIDE" ]]; then
  BOOTSTRAP_ADMIN_POINTS="$ADMIN_POINTS_OVERRIDE"
fi
unset ADMIN_USERNAME_OVERRIDE ADMIN_POINTS_OVERRIDE
unset ADMIN_PASSWORD_OVERRIDE

: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}"
ADMIN_USERNAME="${BOOTSTRAP_ADMIN_USERNAME:-admin}"
ADMIN_POINTS="${BOOTSTRAP_ADMIN_POINTS:-1000}"
[[ "$ADMIN_USERNAME" =~ ^[a-zA-Z0-9._-]{1,64}$ ]] || fail "BOOTSTRAP_ADMIN_USERNAME 只允许字母、数字、点、下划线、连字符" 10
[[ "$ADMIN_POINTS" =~ ^[0-9]{1,7}$ ]] || fail "BOOTSTRAP_ADMIN_POINTS 必须是 0–9999999 的整数" 10

compose=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
if [[ -n "${COMPOSE_OVERRIDE_FILE:-}" ]]; then
  override_file="$COMPOSE_OVERRIDE_FILE"
  [[ "$override_file" = /* ]] || override_file="$ROOT/$override_file"
  compose+=(-f "$override_file")
fi
compose+=(--profile app)
MYSQL_CONTAINER_ID="$("${compose[@]}" ps -q mysql)"
[[ -n "$MYSQL_CONTAINER_ID" ]] || fail "MySQL 容器未运行；先执行 docker compose --profile app up -d" 10

mysql_exec() {
  docker exec -i -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_CONTAINER_ID" \
    mysql -uroot --default-character-set=utf8mb4 "$@"
}

mysql_exec -N -B -e 'SELECT 1' >/dev/null 2>&1 || fail "MySQL 未就绪或口令不匹配" 20

declare -A DATABASES=(
  [user-service]=user_db
  [billing-service]=billing_db
  [capability-service]=capability_db
  [ai-chat-service]=ai_chat_db
)

applied=0
skipped=0
for service in user-service billing-service capability-service ai-chat-service; do
  database="${DATABASES[$service]}"
  sql_dir="$ROOT/services/$service/sql"
  [[ -d "$sql_dir" ]] || fail "缺少迁移目录：services/$service/sql" 30
  mysql_exec -e "CREATE DATABASE IF NOT EXISTS $database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
  mysql_exec "$database" <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migration (
  version VARCHAR(160) NOT NULL,
  checksum CHAR(64) NOT NULL DEFAULT '',
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='bootstrap_stack.sh/ps1 migration registry';
SQL

  for file in "$sql_dir"/*.sql; do
    [[ -f "$file" ]] || continue
    filename="$(basename "$file")"
    if [[ "$filename" == "02_seed.sql" ]]; then
      printf 'SKIP  %s/%s (first-boot seed; never replay as a migration)\n' "$service" "$filename"
      continue
    fi
    version="$service/$filename"
    checksum="$(sha256sum "$file" | awk '{print $1}')"
    recorded="$(mysql_exec -N -B -e \
      "SELECT checksum FROM schema_migration WHERE version='$version'" "$database" 2>/dev/null || true)"
    if [[ -n "$recorded" ]]; then
      if [[ "$recorded" != "$checksum" ]]; then
        printf 'WARN  %s checksum changed after application; left untouched\n' "$version" >&2
      else
        printf 'SKIP  %s\n' "$version"
      fi
      ((skipped += 1))
      continue
    fi
    printf 'APPLY %s\n' "$version"
    mysql_exec "$database" < "$file"
    mysql_exec -e \
      "INSERT INTO schema_migration(version, checksum) VALUES ('$version', '$checksum') ON DUPLICATE KEY UPDATE checksum=VALUES(checksum)" "$database"
    ((applied += 1))
  done
done

online_capabilities="$(mysql_exec -N -B -e \
  "SELECT COUNT(*) FROM t_capability WHERE is_deleted=0 AND status='online'" capability_db)"
if [[ "$online_capabilities" == "0" && "${BOOTSTRAP_SKIP_SEED:-0}" != "1" ]]; then
  total_capabilities="$(mysql_exec -N -B -e \
    'SELECT COUNT(*) FROM t_capability WHERE is_deleted=0' capability_db)"
  if [[ "$total_capabilities" == "0" ]]; then
    printf 'SEED  capability-service/02_seed.sql (empty capability directory)\n'
    mysql_exec capability_db < "$ROOT/services/capability-service/sql/02_seed.sql"
  else
    printf 'SKIP  capability seed (directory has records but none are online)\n'
  fi
fi

admin_id="$(mysql_exec -N -B -e \
  "SELECT id FROM t_user WHERE username='$ADMIN_USERNAME' AND is_deleted=0 LIMIT 1" user_db)"
if [[ -z "$admin_id" ]]; then
  admin_password="${BOOTSTRAP_ADMIN_PASSWORD:-}"
  if [[ -z "$admin_password" ]]; then
    [[ -t 0 ]] || fail "首次创建管理员时需交互输入口令，或设置 BOOTSTRAP_ADMIN_PASSWORD" 10
    read -r -s -p '管理员初始口令（至少 12 位，不回显）: ' admin_password
    printf '\n' >&2
  fi
  [[ ${#admin_password} -ge 12 ]] || fail "管理员口令至少 12 位" 10
  user_container_id="$("${compose[@]}" ps -q user-service)"
  [[ -n "$user_container_id" ]] || fail "user-service 容器未运行，无法生成兼容的 PBKDF2 哈希" 10
  password_hash="$(printf '%s' "$admin_password" | docker exec -i "$user_container_id" python -c \
    'import hashlib,secrets,sys; salt=secrets.token_bytes(16); digest=hashlib.pbkdf2_hmac("sha256",sys.stdin.buffer.read(),salt,240000,32); print("pbkdf2_sha256$240000$%s$%s"%(salt.hex(),digest.hex()))')"
  unset admin_password
  mysql_exec -e \
    "INSERT INTO t_user(username,password_hash,role,nickname,status) SELECT '$ADMIN_USERNAME','$password_hash','admin','系统管理员','normal' FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM t_user WHERE username='$ADMIN_USERNAME' AND is_deleted=0)" user_db
  admin_id="$(mysql_exec -N -B -e \
    "SELECT id FROM t_user WHERE username='$ADMIN_USERNAME' AND is_deleted=0 LIMIT 1" user_db)"
  printf 'CREATED admin id=%s role=admin (password was not echoed)\n' "$admin_id"
else
  role="$(mysql_exec -N -B -e "SELECT role FROM t_user WHERE id=$admin_id" user_db)"
  [[ "$role" == "admin" ]] || fail "已存在同名账号但不是 admin；请改 BOOTSTRAP_ADMIN_USERNAME" 40
  printf 'SKIP  admin already exists id=%s role=admin (password unchanged)\n' "$admin_id"
fi

mysql_exec -e \
  "INSERT INTO t_points_account(user_id,balance,frozen,version) SELECT $admin_id,$ADMIN_POINTS,0,0 FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM t_points_account WHERE user_id=$admin_id)" user_db
printf 'DONE  migrations applied=%s skipped=%s; opsdemo billing data was not accessed\n' "$applied" "$skipped"

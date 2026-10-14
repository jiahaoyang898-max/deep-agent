#!/usr/bin/env bash
# ==================================================
#  Deep Agent Search  -  一键启动 (Linux / macOS / Git Bash)
#  用法:  bash start.sh
# ==================================================
set -euo pipefail

cd "$(dirname "$0")"

echo "=================================================="
echo "  Deep Agent Search  -  一键启动 (Docker)"
echo "=================================================="

# ---------- 环境文件自举（.env 与 docker/.env.docker）----------
# 新机器 clone 后这两个文件并不存在（已从 git 移除、仅保留 .example 模板）。
# 这里负责从模板生成，并保证两处 MYSQL_PASSWORD 一致。
ENV_FILE=".env"
ENV_EXAMPLE=".env.example"
DOCKER_ENV_FILE="docker/.env.docker"
DOCKER_ENV_EXAMPLE="docker/.env.docker.example"

# docker/.env.docker 会被挂载为容器内 /app/.env；若该路径上存在目录而非文件，
# Docker 会以同名目录挂载，导致容器行为异常。此处提前拦截。
if [ -e "$DOCKER_ENV_FILE" ] && [ ! -f "$DOCKER_ENV_FILE" ]; then
  echo "[错误] $DOCKER_ENV_FILE 已存在但不是普通文件（很可能是 Docker 误建的目录）。" >&2
  echo "       请删除后重试：rm -rf \"$DOCKER_ENV_FILE\"" >&2
  exit 1
fi

GEN_ENV=0
if [ ! -f "$ENV_FILE" ]; then
  if [ -f "$ENV_EXAMPLE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    GEN_ENV=1
    echo "[自举] 已从 $ENV_EXAMPLE 生成 $ENV_FILE"
  else
    echo "[警告] 未找到 $ENV_EXAMPLE，无法自动生成 $ENV_FILE，请手动创建。" >&2
  fi
fi

GEN_DOCKER_ENV=0
if [ ! -f "$DOCKER_ENV_FILE" ]; then
  if [ -f "$DOCKER_ENV_EXAMPLE" ]; then
    cp "$DOCKER_ENV_EXAMPLE" "$DOCKER_ENV_FILE"
    GEN_DOCKER_ENV=1
    echo "[自举] 已从 $DOCKER_ENV_EXAMPLE 生成 $DOCKER_ENV_FILE"
  else
    echo "[警告] 未找到 $DOCKER_ENV_EXAMPLE，无法自动生成 $DOCKER_ENV_FILE，请手动创建。" >&2
  fi
fi

# 替换（缺失时追加）指定文件中的 MYSQL_PASSWORD 行
set_env_password() {
  local file="$1" pwd_value="$2"
  # 转义 sed 替换串里的特殊字符（\ & 以及分隔符 |），兼容用户自带密码
  local esc
  esc="$(printf '%s' "$pwd_value" | sed 's/[\\&|]/\\&/g')"
  if grep -q '^MYSQL_PASSWORD=' "$file"; then
    sed -i "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=${esc}|" "$file"
  else
    printf 'MYSQL_PASSWORD=%s\n' "$pwd_value" >> "$file"
  fi
}

if [ "$GEN_ENV" = "1" ]; then
  # 20 位随机密码（大小写字母 + 数字）。head 提前关闭管道会使 tr 收到 SIGPIPE，
  # 在 set -o pipefail 下会误判为失败，故补 || true。
  RAND_PWD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20 || true)"
  set_env_password "$ENV_FILE" "$RAND_PWD"
  echo "[自举] 已生成 20 位随机 MySQL 密码并写入 $ENV_FILE"
fi

if [ "$GEN_DOCKER_ENV" = "1" ] && [ -f "$DOCKER_ENV_FILE" ]; then
  if [ "$GEN_ENV" = "1" ]; then
    set_env_password "$DOCKER_ENV_FILE" "$RAND_PWD"
  else
    # .env 已存在（用户真实密钥），沿用其中密码，保证两处一致
    EXISTING_PWD="$(grep -m1 '^MYSQL_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)"
    if [ -n "$EXISTING_PWD" ]; then
      set_env_password "$DOCKER_ENV_FILE" "$EXISTING_PWD"
    fi
  fi
  echo "[自举] 已将同一 MySQL 密码同步写入 $DOCKER_ENV_FILE"
fi

if [ "$GEN_ENV" = "1" ] || [ "$GEN_DOCKER_ENV" = "1" ]; then
  echo ""
  echo "--------------------------------------------------"
  echo "  环境文件自举完成，涉及的配置文件："
  echo "    - $ENV_FILE"
  echo "    - $DOCKER_ENV_FILE"
  echo "  MySQL 密码已在以上两个文件中保持一致。"
  echo "  [注意] LLM / 搜索 / 知识库 的 API Key 仍是占位符，服务可正常启动，"
  echo "         但联网检索与大模型功能需在以上两个文件中填入真实值。"
  echo "--------------------------------------------------"
  echo ""
fi

# ---------- 0. 检查 Docker 是否安装 ----------
if ! command -v docker >/dev/null 2>&1; then
  echo "[错误] 未检测到 Docker 命令，请先安装 Docker / Docker Desktop。" >&2
  exit 1
fi

# ---------- 1. 检查 Docker 守护进程 ----------
if ! docker info >/dev/null 2>&1; then
  echo "[错误] Docker 守护进程未运行。"
  echo "       - Windows / macOS: 请先打开 Docker Desktop，待其显示 Running 后重试。"
  echo "       - Linux: sudo systemctl start docker"
  exit 1
fi
echo "[OK] Docker 已就绪。"

# ---------- 2. 构建并启动 ----------
echo "[1/3] 构建并启动容器（首次构建需 3-8 分钟）..."
docker compose up -d --build

# ---------- 3. 等待 MySQL 健康 ----------
echo "[2/3] 等待 MySQL 初始化 ..."
hs=""
for _ in $(seq 1 60); do
  hs="$(docker inspect -f '{{.State.Health.Status}}' das-mysql 2>/dev/null || true)"
  [ "$hs" = "healthy" ] && break
  sleep 3
done
if [ "$hs" = "healthy" ]; then
  echo "[OK] MySQL 状态: healthy"
else
  echo "[警告] MySQL 健康检查等待超时（当前: ${hs:-unknown}），继续检查其它服务 ..."
fi

# ---------- 4. 输出 ----------
echo "[3/3] 当前服务状态:"
docker compose ps

cat <<'EOF'

==================================================
  启动成功！请在浏览器中访问:

    前端界面   http://localhost:8080
    后端 API   http://localhost:8000/docs
    认证服务   http://localhost:8001/docs
    MySQL      127.0.0.1:3307  (root / 见 .env 中的 MYSQL_PASSWORD)

  停止服务:  docker compose down
  查看日志:  docker compose logs -f
==================================================
EOF

#!/usr/bin/env bash
# ==================================================
#  Deep Agent Search  -  一键启动 (Linux / macOS / Git Bash)
#  用法:  bash start.sh
#         bash start.sh --frontend      # 只重建并重启前端（改前端代码后最快的迭代路径）
# ==================================================
set -euo pipefail

cd "$(dirname "$0")"

# ---------- 参数解析 ----------
FRONTEND_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --frontend|--frontend-only|-f) FRONTEND_ONLY=1 ;;
    -h|--help)
      echo "用法: bash start.sh [--frontend]"
      echo "  (无参数)        构建并启动全部服务"
      echo "  --frontend      只构建并重启前端容器"
      exit 0
      ;;
    *)
      echo "[错误] 未知参数: $arg（可用: --frontend / --help）" >&2
      exit 1
      ;;
  esac
done

echo "=================================================="
echo "  Deep Agent Search  -  一键启动 (Docker)"
if [ "$FRONTEND_ONLY" = "1" ]; then
  echo "  模式：只重建前端 (--frontend)"
fi
echo "=================================================="

# ---------- 预检：端口占用 / 磁盘空间 ----------
check_port() {
  local port="$1" owner=""
  if command -v lsof >/dev/null 2>&1; then
    # lsof 无匹配时退出码为 1，配合 set -e 必须 || true
    owner="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print $1" ("$2")"}' | sort -u | tr '\n' ' ' || true)"
  elif command -v ss >/dev/null 2>&1; then
    owner="$(ss -lptn "sport = :$port" 2>/dev/null | tail -n +2 | head -3 | tr '\n' ' ' || true)"
  fi
  if [ -n "$owner" ]; then
    echo "[提示] 端口 $port 已被占用：$owner"
  fi
}

check_ports() {
  for p in "$@"; do check_port "$p"; done
  echo "       自行定位（以 8080 为例）：lsof -nP -iTCP:8080 -sTCP:LISTEN"
}

check_disk() {
  local avail
  avail="$(df -Pk . 2>/dev/null | awk 'NR==2{printf "%d", $4/1024/1024}' || true)"
  if [ -n "$avail" ] && [ "$avail" -lt 5 ]; then
    echo "[警告] 当前磁盘可用空间仅约 ${avail} GB（建议 ≥ 5 GB），构建可能因空间不足中断。"
    echo "       查看占用: docker system df"
    echo "       清理构建缓存: docker builder prune"
  fi
}

# ---------- HTTP 探活：轮询直到返回 2xx/3xx ----------
probe() {
  local name="$1" url="$2" timeout="${3:-60}" interval=3 elapsed=0 code
  while [ "$elapsed" -lt "$timeout" ]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 5 "$url" 2>/dev/null || true)"
    case "$code" in
      2??|3??)
        echo "       [OK] ${name} 已就绪（HTTP ${code}，耗时 ${elapsed}s）"
        return 0
        ;;
    esac
    sleep "$interval"
    elapsed=$((elapsed + interval))
  done
  echo "       [失败] ${name} 在 ${timeout}s 内未就绪" >&2
  return 1
}

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

# ---------- 2. 预检 ----------
if [ "$FRONTEND_ONLY" = "1" ]; then
  check_ports 8080
else
  check_ports 8080 8000 8001 3307
fi
check_disk

# ---------- 3. 只重建前端（快速通道）----------
if [ "$FRONTEND_ONLY" = "1" ]; then
  echo "[1/2] 构建前端镜像（只构建 frontend）..."
  if ! docker compose build frontend; then
    echo "[错误] 前端镜像构建失败。查看完整输出：" >&2
    echo "       docker compose build --progress=plain --no-cache frontend" >&2
    echo "       若提示 no space left on device：docker builder prune" >&2
    exit 1
  fi

  echo "[2/2] 重启前端容器 ..."
  if ! docker compose up -d frontend; then
    echo "[错误] 启动前端容器失败。下面是 docker compose logs 末尾 20 行：" >&2
    docker compose logs --tail 20 || true
    exit 1
  fi

  if probe "前端" "http://localhost:8080/" 60; then
    docker compose ps frontend
    echo ""
    echo "=================================================="
    echo "  前端已重建完成！访问: http://localhost:8080"
    echo ""
    echo "  查看前端日志:  docker compose logs -f frontend"
    echo "  需要全量重建:  bash start.sh"
    echo "=================================================="
    exit 0
  fi

  docker compose ps frontend
  echo ""
  echo "  前端已重启，但探活未通过：" >&2
  echo "       docker compose logs -f frontend" >&2
  exit 1
fi

# ---------- 4. 构建并启动 ----------
echo "[1/3] 构建并启动容器（首次构建需 3-8 分钟）..."
if ! docker compose up -d --build; then
  echo "[错误] 构建并启动容器失败。下面是 docker compose logs 末尾 20 行：" >&2
  docker compose logs --tail 20 || true
  echo ""
  echo "       下一步: docker compose ps / docker compose logs -f / docker builder prune" >&2
  exit 1
fi

# ---------- 5. 等待 MySQL 健康 ----------
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

# ---------- 6. 服务探活 ----------
echo "[3/3] 服务探活（每个服务最长 60 秒）..."
FAILED=""
if ! probe "前端" "http://localhost:8080/" 60;    then FAILED="$FAILED frontend"; fi
if ! probe "后端" "http://localhost:8000/docs" 60; then FAILED="$FAILED backend";  fi
if ! probe "认证" "http://localhost:8001/docs" 60; then FAILED="$FAILED auth";     fi
if [ -n "$FAILED" ]; then
  echo "[提示] 以下服务暂未就绪:${FAILED}"
  echo "       查看日志：docker compose logs -f <服务名>"
else
  echo "[OK] 三个服务全部探活通过。"
fi

# ---------- 7. 输出 ----------
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
  只重建前端:  bash start.sh --frontend
==================================================
EOF

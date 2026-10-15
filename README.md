# Deep Agent Search · 深度调研智能体

基于 DeepAgents 的深度调研智能体系统，包含前端对话界面、后端智能体服务、独立认证微服务与 MySQL 业务数据库（药品库存/销售结构化数据）。

整个系统通过 **Docker Compose** 编排，**一条命令即可启动全部服务**。

---

## 一、快速开始（5 分钟跑起来）

### 0. 前置要求

| 项目 | 要求 |
|---|---|
| Docker | Docker Desktop（Windows / macOS）或 Docker Engine + Compose v2（Linux） |
| 磁盘 | 建议预留 **8 GB** 以上（4 个镜像约 5.7 GB） |
| 内存 | 建议 ≥ 6 GB 可用（Docker 内存上限可在 Docker Desktop → Settings → Resources 调整） |
| 网络 | 首次构建需访问 `registry.npmmirror.com` / `pypi.tuna.tsinghua.edu.cn`，无需科学上网 |

> **Windows 用户请务必确认 Docker Desktop 已启动并显示 Running。**

### 1. 启动

任选一种方式，**在项目根目录执行**：

```powershell
# 方式 A：PowerShell（推荐）
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

```bat
:: 方式 B：CMD —— 直接双击 start.bat
start.bat
```

```bash
# 方式 C：Linux / macOS / Git Bash
bash start.sh
```

> 不想用脚本？等价命令就一行：
> ```bash
> docker compose up -d --build
> ```

首次执行会自动完成：拉取基础镜像 → 构建 3 个业务镜像 → 启动 4 个容器 → 等待 MySQL 建库建表 → **逐个探活三个 HTTP 服务**。
**首次约 3~8 分钟**（取决于网络），之后再次启动只需十几秒。

#### 只重建前端（改前端代码后的最快路径）

改完 `ui/src/**` 后不必重建全部镜像，用 `-FrontendOnly` 只构建并重启前端容器：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -FrontendOnly
```

```bat
start.bat -FrontendOnly
```

```bash
bash start.sh --frontend
```

等价命令：`docker compose build frontend && docker compose up -d frontend`。

#### 启动脚本会做的事（失败时会给出下一步）

| 阶段 | 行为 |
|---|---|
| 环境自举 | 缺失的 `.env` / `docker/.env.docker` 从模板生成，并保证两处 MySQL 密码一致 |
| 预检 | 检测 8080 / 8000 / 8001 / 3307 是否被占用并**报出占用进程**；检测系统盘剩余空间（< 5 GB 时提醒 Docker Desktop 镜像默认占 C 盘） |
| 构建启动 | `docker compose up -d --build`；失败时打印 `docker compose logs` 末尾 20 行 |
| 服务探活 | 依次请求 `http://localhost:8080/`、`http://localhost:8000/docs`、`http://localhost:8001/docs`，每个最长 60 秒（每 3 秒重试一次） |
| 结果 | 全部通过才打印「启动成功」；未通过的服务会直接给出 `docker compose logs -f <服务名>` |

探活失败时的标准排查顺序：

```bash
docker compose ps                 # 看哪个容器退出了
docker compose logs -f backend    # 换成未通过的服务名
docker compose up -d --force-recreate backend
```

> **关于密钥配置（重要）**
> `.env` 与 `docker/.env.docker` 含真实 API Key 与数据库密码，**不随仓库分发**（已在 `.gitignore` 中忽略）。
> 首次运行脚本会自动从 `*.example` 模板生成这两个文件，并**随机生成一个 MySQL 密码同时写入两处**（两处必须一致，否则后端连不上库）。
> 此时 `LLM / 搜索 / 知识库` 的 API Key 仍是占位符 —— 服务能正常启动、界面能打开、可注册登录，
> 但**联网检索与大模型能力**需要在这两个文件里填入真实值后重启后端：
> ```bash
> docker compose restart backend
> ```

### 2. 访问

| 服务 | 地址 | 说明 |
|---|---|---|
| **前端界面** | http://localhost:8080 | 浏览器打开这个即可；可直接用演示账号 `demo` / `demo123456` 登录，或自行注册 |
| 后端 API 文档 | http://localhost:8000/docs | FastAPI Swagger（仅调试用，前端通过 8080 网关访问） |
| 认证服务文档 | http://localhost:8001/docs | 登录 / 注册微服务（仅调试用） |
| MySQL | 127.0.0.1:3307 | 用户 `root`，密码见 `.env` 中的 `MYSQL_PASSWORD`，库 `pharma_db` |

### 3. 停止 / 查看日志

```bash
docker compose down          # 停止并删除容器（数据保留）
docker compose logs -f       # 实时查看全部日志
docker compose logs -f backend
```

---

## 二、系统架构

```
                    ┌──────────────────────────────┐
   浏览器 :8080 ───▶│  das-frontend (Nginx 网关)    │
                    │  · 托管前端静态资源            │
                    │  · /api/     → backend:8000   │
                    │  · /api/auth/→ auth:8001      │
                    │  · /ws/      → backend:8000 (WebSocket) │
                    └───────┬──────────────┬───────┘
                            │              │
              ┌─────────────▼───┐   ┌──────▼──────────┐
              │ das-backend     │   │ das-auth        │
              │ FastAPI + Agent │   │ FastAPI + SQLite│
              │ :8000           │   │ :8001           │
              └────────┬────────┘   └─────────────────┘
                       │
              ┌────────▼────────┐
              │ das-mysql 8.0   │  utf8mb4，首次启动自动执行 sql/db.sql
              │ :3306 (宿主 3307)│
              └─────────────────┘
```

宿主机目录映射：

| 宿主机 | 容器 | 用途 |
|---|---|---|
| `./docker-data/mysql` | `/var/lib/mysql` | MySQL 数据持久化（**首次启动自动初始化**） |
| `./docker-data/auth` | `/data` | 认证服务 SQLite 数据 |
| `./output` | `/app/output` | 智能体生成的文件（前端「文件面板」读取） |
| `./upload` | `/app/upload` | 用户上传的文件 |
| `./sql/db.sql` | `/docker-entrypoint-initdb.d/01-init.sql` | 首次启动建库建表 + 示例数据（只读） |

---

## 三、配置

### 后端环境变量

后端容器的环境变量来自 `docker/.env.docker`（由 `docker-compose.yml` 挂载为容器内 `/app/.env`）。

**更换 LLM / 搜索 / 知识库密钥，只需编辑该文件**，例如替换 `DASHSCOPE_API_KEY`、`TAVILY_API_KEY`、`RAGFLOW_API_KEY`，然后重启 backend：

```bash
docker compose up -d --force-recreate backend
```

> 该文件中 `MYSQL_HOST=mysql` **是固定的**（容器网络中的服务名），不要改成 `localhost`。

模板见 [`docker/.env.docker.example`](docker/.env.docker.example)。
本地（非 Docker）开发用的模板见 [`.env.example`](.env.example)。

### 修改对外端口

编辑 `docker-compose.yml` 中 `frontend` 服务的端口映射，例如改成 `9090:80`：

```yaml
ports:
  - "9090:80"
```

---

## 四、常见问题（Troubleshooting）

**1. `curl` 访问本机地址报 502 / connection refused，但浏览器正常**
本机若开启了系统代理（Clash / v2ray 等），`curl` 会走代理导致误判。请加 `--noproxy '*'`：

```bash
curl --noproxy '*' http://127.0.0.1:8080/
```

**2. 端口被占用（8080 / 8000 / 8001 / 3307）**
改 `docker-compose.yml` 中对应服务的左侧端口号即可（左侧是宿主机端口）。

**3. 想彻底重置数据库**
MySQL 数据在 `docker-data/mysql`。删除该目录后再启动会重新执行 `sql/db.sql` 初始化：

```bash
docker compose down
rm -rf docker-data/mysql        # Windows: rmdir /s /q docker-data\mysql
docker compose up -d
```
⚠️ 会丢失已有数据，请先确认。

**4. 改了代码但容器没变化**
镜像已构建过，需要重新构建：

```bash
docker compose up -d --build
```

**5. Windows 下路径含空格导致脚本报错**
本项目目录名以空格开头，任何命令行引用路径都必须加英文引号，例如 `cd "D:\ deep_agent search"`。

**6. 不想让 Docker 占用 C 盘空间**
Docker Desktop 的镜像 / 容器 / 构建缓存存放在 *Settings → Resources → Advanced → Disk image location* 指定的位置。请将其指向非系统盘（例如 `D:\DockerData`），否则默认会落在 `%LOCALAPPDATA%\Docker`（C 盘）。

---

## 五、技术说明

- **后端业务代码零改动**：`utils/converter_utils.py` 原本依赖 Windows 专属的 `pywin32`（Word COM 转 PDF），容器内通过 `docker/shim/sitecustomize.py` 注入假模块并改用 **WeasyPrint** 渲染 PDF，中文表格由 `fonts-noto-cjk` 提供字体。镜像已内置，无需额外配置。
- **MySQL 字符集**：`utf8mb4` / `utf8mb4_unicode_ci`，中文药品数据可正常存取。
- **数据库初始化**：`sql/db.sql` 内含 `CREATE DATABASE` / `CREATE TABLE` / 示例数据，MySQL 容器**仅在数据目录为空时**执行一次。

---

## 六、目录结构

```
.
├── docker-compose.yml          # 编排入口（4 个服务）
├── start.ps1 / start.bat / start.sh   # 一键启动脚本
├── .env / .env.example         # 本地开发环境变量
├── docker/
│   ├── backend.Dockerfile      # 后端镜像
│   ├── auth.Dockerfile         # 认证服务镜像
│   ├── frontend.Dockerfile     # 前端构建 + Nginx 镜像
│   ├── nginx.conf              # 网关路由（API / WS / SPA）
│   ├── requirements-docker.txt # 后端 Linux 依赖锁版本
│   ├── .env.docker             # 容器内环境变量（实际生效）
│   ├── .env.docker.example     # 上者模板
│   └── shim/sitecustomize.py   # win32com → WeasyPrint 兼容垫片
├── agent/ api/ tools/ utils/ prompt/   # 后端智能体业务代码
├── auth_service/main.py        # 认证微服务（SQLite + PBKDF2）
├── ui/                         # Vue 3 + Vite 前端
├── sql/db.sql                  # 建库建表 + 示例数据
├── docker-data/                # 运行期数据（自动创建，勿手动改）
├── output/  upload/            # 智能体产出 / 用户上传
└── .dockerignore               # 构建上下文排除规则
```

# 测试服务器 Docker 部署

生产式 Compose 会启动四个容器：

- `web`：构建 Vue 前端并通过 Nginx 提供页面，同时反向代理 `/api`。
- `api`：FastAPI + LangGraph 后端。
- `postgres`：对话日志数据库。
- `redis`：短期缓存服务，预留给项目的 Redis memory。

对外只开放一个 Web 端口，PostgreSQL、Redis 和 API 不直接暴露到公网。SQLite checkpoint 与 embedding 缓存、PostgreSQL 数据、Redis 数据都保存在 Docker volume 中。

## 1. 服务器准备

建议测试服务器至少 2 核 CPU、4 GB 内存、20 GB 可用磁盘，并已安装 Docker Engine 与 Docker Compose v2：

```bash
docker --version
docker compose version
```

将仓库克隆或上传到服务器，然后进入项目根目录。

## 2. 配置环境变量

```bash
cp .env.production.example .env
```

编辑 `.env`，至少替换：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` 与 `OPENAI_MODEL`
- `QWEN_EMBEDDING_API_KEY`
- `POSTGRES_PASSWORD`
- `USER_APP_BASE_URL`、`ADMIN_API_BASE_URL` 与 `LOGIN_PROFILE_URL`

首次联调建议保持 `USER_APP_SUBMIT_ENABLED=false`，避免误下真实订单；确认完整流程后再改为 `true`。

不要提交 `.env`，也不要把它复制到前端目录。`VITE_*` 环境变量会被打包进浏览器 JS，不适合存放长期密钥。

## 3. 构建并启动

```bash
docker compose up -d --build
```

首次构建需要下载 Python、Node、Nginx、PostgreSQL 和 Redis 镜像，并安装前后端依赖，耗时取决于服务器网络。

如果服务器访问 Docker Hub 超时，请先按服务器所在网络配置可信的 Docker Registry mirror，再重启 Docker daemon 后重试；不要从来历不明的镜像站下载包含业务代码的镜像。

查看状态和日志：

```bash
docker compose ps
docker compose logs -f --tail=200 api web
```

默认使用 `8080` 端口：

```bash
curl http://127.0.0.1:8080/health
```

正常返回示例：

```json
{"status":"ok","service":"Hotel AI Order Agent"}
```

浏览器访问 `http://测试服务器IP:8080/`，接口文档访问 `http://测试服务器IP:8080/docs`。如果需改端口，修改 `.env` 中的 `WEB_PORT`，并在服务器安全组或防火墙中只开放该端口。

## 4. 更新版本

拉取新代码后重新构建，数据库和会话数据不会因容器重建而丢失：

```bash
git pull
docker compose up -d --build
```

## 5. 停止与清理

停止服务但保留数据：

```bash
docker compose down
```

只有明确要删除全部测试数据时才使用下面的命令：

```bash
docker compose down -v
```

## 常见问题

### API 容器反复重启

先查看日志：

```bash
docker compose logs --tail=300 api postgres
```

常见原因是模型 Key 无效、PostgreSQL 密码与旧 volume 中初始化密码不一致，或测试服务器无法访问模型/业务接口。

### 修改了 PostgreSQL 密码却仍然认证失败

PostgreSQL 只在数据目录首次初始化时读取密码。已有测试数据要保留时，请在数据库内改密码；不需要保留时可执行 `down -v` 后重新初始化。

### 容器无法访问业务内网地址

确认测试服务器本身能够访问 `USER_APP_BASE_URL`，并检查服务器路由、防火墙和业务系统白名单。Linux 容器通常可直接访问局域网 IP，但无法把容器里的 `127.0.0.1` 当作宿主机。

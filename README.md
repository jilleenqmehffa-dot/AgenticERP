# AgenticERP

## 运行后端

需要 Python 3.12、uv 和 Docker。首次运行时：

```bash
cd backend
cp .env.example .env
docker compose up -d postgres
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

根据本地 PostgreSQL 配置调整 `.env` 中的 `DATABASE_URL`。应用默认监听
`http://127.0.0.1:8000`；`GET /health` 检查应用，`GET /ready` 检查数据库连接。

运行单元测试：

```bash
cd backend
uv run python -m unittest discover -s tests -q
```

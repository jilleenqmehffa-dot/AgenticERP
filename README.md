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

## 预留建议审核

预留建议使用 `recommendation_type=RESERVATION`、`source_type=OUTBOUND_ORDER_ITEM`
和出库行 `source_id`。`proposed_data` 包含 `quantity`、`location_code`，可选
`lot_no` 和 `expires_at`。建议由 Agent 创建后，仓库经理使用账号的 HTTP Basic
凭据调用：

```text
POST /reservation-recommendations/{id}/approve
POST /reservation-recommendations/{id}/reject
Content-Type: application/json

{"reason":"审核理由"}
```

批准操作会在一个数据库事务中创建库存预留、关联建议并写入审计；重复批准返回原预留。
驳回只记录决定和审计，不占用库存。接口返回建议状态及批准后生成的
`approved_reservation_id`。

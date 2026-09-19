# AgenticERP V1 基础 ERP 后端 Spec

## 1. 文档目标

本 Spec 定义 AgenticERP V1 的基础 ERP 后端开发范围。

V1 **不接入 Agent、不开发前端、不开发审批系统、不开发员工 Task
系统**。目标是先建立可靠、确定性的 ERP 业务底座，为后续 Agent
Capability、Task、审批与前端提供基础。

### 技术栈

-   Python
-   FastAPI
-   Pydantic
-   SQLAlchemy 2.x
-   Alembic
-   PostgreSQL

### 基础分层

``` text
API / Router
     ↓
Service
     ↓
Repository
     ↓
SQLAlchemy Model
     ↓
PostgreSQL
```

职责约束：

-   **Router**：接收请求、参数校验、返回响应。
-   **Service**：业务规则、状态判断、业务操作编排、事务边界。
-   **Repository**：数据库查询和持久化，不承载核心业务判断。
-   **Model**：数据库实体映射。
-   **Schema**：API 输入输出数据结构。

------------------------------------------------------------------------

# 2. V1 开发范围

V1 严格按照以下 6 个模块开发：

1.  订单数据结构
2.  商品与库存数据结构
3.  商品与库存状态数据结构
4.  库存阈值判断与状态自动更新
5.  出库 / 入库 Service 与 Repository
6.  应收 / 应付数据结构

审批涉及前端交互，V1 暂不实现。

------------------------------------------------------------------------

# Module 1：订单数据结构

## 目标

建立最基础的销售订单数据模型，使系统能够表示：

> 一个客户订单包含多个商品，每个商品具有数量、单价和金额。

## SalesOrder

建议字段：

``` text
SalesOrder
├── id
├── order_no
├── customer_name
├── status
├── total_amount
├── created_at
└── updated_at
```

## SalesOrderItem

建议字段：

``` text
SalesOrderItem
├── id
├── sales_order_id
├── product_id
├── quantity
├── unit_price
└── amount
```

## SalesOrderStatus

``` text
DRAFT
CONFIRMED
PARTIALLY_FULFILLED
FULFILLED
CANCELLED
```

## 关系

``` text
SalesOrder
    │
    ├── SalesOrderItem
    ├── SalesOrderItem
    └── SalesOrderItem
             │
             └── Product
```

## 业务约束

-   一个 `SalesOrder` 可以包含多个 `SalesOrderItem`。
-   每个 `SalesOrderItem` 必须关联一个有效 `Product`。
-   `quantity` 必须大于 0。
-   `unit_price` 不允许为负数。
-   `amount` 应由数量与单价计算或由 Service 统一维护。
-   `total_amount` 应由订单项汇总产生，不应由客户端任意指定最终值。

## 完成标准

能够在 PostgreSQL 中：

-   创建销售订单。
-   一个订单包含多个商品。
-   查询订单及其订单项。
-   正确保存订单状态和金额。

------------------------------------------------------------------------

# Module 2：商品与库存数据结构

## 目标

建立商品主数据与库存数据。

商品信息和库存信息必须分离，禁止直接在 `Product` 上使用一个简单的
`stock` 字段表示库存。

## Product

``` text
Product
├── id
├── sku
├── name
├── category
├── unit
├── status
├── created_at
└── updated_at
```

## Inventory

``` text
Inventory
├── id
├── product_id
├── warehouse_code
├── on_hand_quantity
├── reserved_quantity
├── status
├── low_stock_threshold
└── updated_at
```

## 库存数量定义

``` text
available_quantity
=
on_hand_quantity
-
reserved_quantity
```

其中：

-   `on_hand_quantity`：当前实际账面库存。
-   `reserved_quantity`：已经被业务占用但尚未实际出库的库存。
-   `available_quantity`：当前仍然可以被新业务使用的库存。

## 示例

``` text
Product:
显示器
SKU = MONITOR-001

Inventory:
warehouse_code = A
on_hand_quantity = 100
reserved_quantity = 30

available_quantity = 70
```

## 业务约束

-   `sku` 必须唯一。
-   `on_hand_quantity` 不允许为负数。
-   `reserved_quantity` 不允许为负数。
-   `reserved_quantity` 原则上不得大于 `on_hand_quantity`。
-   V1 即使只有一个仓库，也保留 `warehouse_code` 字段。
-   后续库存变化不得通过普通 CRUD API 直接修改 `on_hand_quantity`。

## 完成标准

系统能够表示：

-   多种商品。
-   每种商品对应的库存。
-   实际库存、预留库存、可用库存。
-   不同仓库下的商品库存。

------------------------------------------------------------------------

# Module 3：商品与库存状态数据结构

## 目标

区分：

1.  商品自身生命周期状态。
2.  商品当前库存业务状态。

禁止将两种状态混为一个 `Product.status`。

## ProductStatus

``` text
ACTIVE
INACTIVE
DISCONTINUED
```

含义：

-   `ACTIVE`：正常使用/销售。
-   `INACTIVE`：暂时停用。
-   `DISCONTINUED`：已停止经营该商品。

## InventoryStatus

``` text
NORMAL
LOW_STOCK
OUT_OF_STOCK
```

含义：

-   `NORMAL`：库存正常。
-   `LOW_STOCK`：低于预设库存阈值。
-   `OUT_OF_STOCK`：当前无可用库存。

## 示例

``` text
Product.status = ACTIVE

Inventory:
on_hand_quantity = 40
reserved_quantity = 20
available_quantity = 20
low_stock_threshold = 30
status = LOW_STOCK
```

## 完成标准

系统能够独立表达：

``` text
商品是否仍然有效
≠
商品现在是否缺货
```

------------------------------------------------------------------------

# Module 4：库存计算与状态判断规则

## 目标

建立 V1 第一组确定性的 ERP 库存领域规则。

本 Module **不负责修改库存，也不实现正式的出库 / 入库 Service**。

本阶段只负责定义：

1. 可用库存如何计算。
2. 库存状态如何根据可用库存与库存阈值确定。

真正的库存变化以及库存变化后自动触发状态重新计算，将在 **Module 5 的 `InventoryService`** 中实现。

---

## 1. 可用库存计算

统一定义：

```python
available_quantity = on_hand_quantity - reserved_quantity
```

建议实现独立规则函数：

```python
def calculate_available(
    on_hand_quantity: int,
    reserved_quantity: int,
) -> int:
    return on_hand_quantity - reserved_quantity
```

其中：

* `on_hand_quantity`：当前实际账面库存。
* `reserved_quantity`：已经被其他业务预留的库存。
* `available_quantity`：当前仍然可以被新业务使用的库存。

---

## 2. 库存状态判断

基础规则：

```python
if available_quantity <= 0:
    status = OUT_OF_STOCK

elif available_quantity < low_stock_threshold:
    status = LOW_STOCK

else:
    status = NORMAL
```

建议实现统一的状态判断函数：

```python
def evaluate_inventory_status(
    available_quantity: int,
    low_stock_threshold: int,
) -> InventoryStatus:

    if available_quantity <= 0:
        return InventoryStatus.OUT_OF_STOCK

    if available_quantity < low_stock_threshold:
        return InventoryStatus.LOW_STOCK

    return InventoryStatus.NORMAL
```

---

## 3. 职责边界

Module 4 只负责：

```text
库存数据
   ↓
calculate_available()
   ↓
可用库存
   ↓
evaluate_inventory_status()
   ↓
InventoryStatus
```

本 Module 不负责：

```text
stock_in()
stock_out()
数据库库存修改
StockMovement
库存事务
```

以上内容统一在 Module 5 实现。

---

## 4. 业务


------------------------------------------------------------------------

# Module 5：出库 / 入库 Service 与 Repository

## 目标

建立 V1 最基础的受控库存 Business Capability。

库存不得通过 Agent、Router 或普通 CRUD 接口直接修改。

统一通过业务 Service：

``` text
stock_in()
stock_out()
```

执行。

------------------------------------------------------------------------

## InventoryRepository

Repository 只负责数据访问。

建议能力：

``` text
get_by_product()
get_by_product_and_warehouse()
get_for_update()
save()
```

Repository 不负责：

-   判断能不能出库。
-   判断库存状态。
-   判断业务动作是否合法。
-   决定库存应该增加还是减少。

这些属于 Service。

------------------------------------------------------------------------

## InventoryService.stock_in()

接口概念：

``` python
stock_in(
    product_id,
    warehouse_code,
    quantity
)
```

执行流程：

``` text
检查 quantity > 0
        ↓
查询并锁定 Inventory
        ↓
on_hand_quantity += quantity
        ↓
重新计算 available_quantity
        ↓
重新计算 InventoryStatus
        ↓
创建 StockMovement
        ↓
保存
```

------------------------------------------------------------------------

## InventoryService.stock_out()

接口概念：

``` python
stock_out(
    product_id,
    warehouse_code,
    quantity
)
```

执行流程：

``` text
检查 quantity > 0
        ↓
查询并锁定 Inventory
        ↓
计算 available_quantity
        ↓
检查 available_quantity >= quantity
        ↓
on_hand_quantity -= quantity
        ↓
重新计算库存状态
        ↓
创建 StockMovement
        ↓
保存
```

如果库存不足：

``` text
available_quantity < quantity
```

必须拒绝出库，不允许产生负库存。

------------------------------------------------------------------------

## StockMovement

所有实际库存变化都必须产生库存流水。

``` text
StockMovement
├── id
├── product_id
├── warehouse_code
├── movement_type
├── quantity
├── reference_type
├── reference_id
├── created_at
└── created_by
```

### MovementType

V1：

``` text
IN
OUT
```

后续可扩展：

``` text
TRANSFER_IN
TRANSFER_OUT
ADJUSTMENT
RETURN
```

## reference

`reference_type` 与 `reference_id` 用于记录库存变化来源。

例如：

``` text
movement_type = OUT
quantity = 40
reference_type = SALES_ORDER
reference_id = 1001
```

表示：

> 这 40 件库存是因为销售订单 1001 而出库。

------------------------------------------------------------------------

## 事务要求

库存数量修改和 `StockMovement` 创建必须处于可靠的数据库事务中。

目标：

``` text
库存修改成功 + 流水创建成功
```

或者：

``` text
全部失败并回滚
```

不能出现：

``` text
库存 -40
但 StockMovement 创建失败
```

这种不一致状态。

## 并发要求

出库操作应考虑并发修改问题。

推荐在读取待修改库存记录时使用数据库行锁或其他可靠并发控制方式，避免两个请求同时读取相同库存并造成超卖。

## 完成标准

能够完成：

``` text
库存 100
↓
stock_out(40)
↓
库存 60
↓
生成 OUT 40 StockMovement
```

以及：

``` text
库存 60
↓
stock_in(20)
↓
库存 80
↓
生成 IN 20 StockMovement
```

并且每次库存变化后自动重新计算 `InventoryStatus`。

------------------------------------------------------------------------

# Module 6：应收 / 应付数据结构

## 目标

建立 V1 最基础的应收账款（AR）与应付账款（AP）数据结构。

V1 不实现完整会计系统。

------------------------------------------------------------------------

## AccountReceivable

``` text
AccountReceivable
├── id
├── sales_order_id
├── customer_name
├── amount
├── paid_amount
├── due_date
├── status
├── created_at
└── updated_at
```

## ReceivableStatus

``` text
UNPAID
PARTIALLY_PAID
PAID
OVERDUE
```

目标是能够表达：

``` text
某销售订单应收多少钱
已经收到多少钱
还剩多少钱
什么时候到期
当前付款状态
```

------------------------------------------------------------------------

## AccountPayable

``` text
AccountPayable
├── id
├── reference_no
├── supplier_name
├── amount
├── paid_amount
├── due_date
├── status
├── created_at
└── updated_at
```

## PayableStatus

``` text
UNPAID
PARTIALLY_PAID
PAID
OVERDUE
```

目标是能够表达：

``` text
某笔采购应付多少钱
已经支付多少钱
还剩多少钱
什么时候到期
当前付款状态
```

## V1 不实现

以下内容明确排除：

-   总账（General Ledger）
-   会计科目
-   借贷记账
-   资产负债表
-   利润表
-   税务
-   完整发票系统
-   自动付款
-   银行对账

## 完成标准

系统能够查询：

``` text
这个销售订单
→ 客户还欠公司多少钱

这笔采购相关业务
→ 公司还欠供应商多少钱
```

------------------------------------------------------------------------

# 3. V1 核心业务关系

完成 6 个模块后，基础结构应形成：

``` text
SalesOrder
    │
    ├── SalesOrderItem
    │       │
    │       ↓
    │    Product
    │       │
    │       ↓
    │   Inventory
    │       │
    │       ├── stock_in()
    │       ├── stock_out()
    │       └── StockMovement
    │
    └── AccountReceivable


采购相关 Reference
    │
    └── AccountPayable
```

库存状态：

``` text
Inventory
    ↓
available_quantity
    ↓
InventoryStatus

NORMAL
LOW_STOCK
OUT_OF_STOCK
```

------------------------------------------------------------------------

# 4. V1 核心架构原则

## 4.1 Agent 不参与 V1

V1 所有业务必须在没有 LLM 和 Agent 的情况下正确运行。

后续 Agent 只能调用已经验证过的 Business Capability。

------------------------------------------------------------------------

## 4.2 禁止直接修改核心业务状态

例如库存变化禁止：

``` text
Router
↓
直接 UPDATE Inventory
```

必须：

``` text
Router
↓
InventoryService.stock_in / stock_out
↓
InventoryRepository
↓
Database
```

未来 Agent 同样遵守：

``` text
Agent
↓
Business Capability
↓
Service
↓
Repository
↓
Database
```

------------------------------------------------------------------------

## 4.3 Service 负责业务规则

Service 负责：

-   库存是否足够。
-   库存状态如何变化。
-   一个业务动作需要修改哪些实体。
-   事务。
-   业务异常。

Repository 只负责数据持久化。

------------------------------------------------------------------------

## 4.4 所有库存变化必须可追溯

禁止只有：

``` text
Inventory = 60
```

却不知道为什么变成 60。

必须可以通过 `StockMovement` 追踪：

``` text
100
↓
OUT 40
↓
60
```

------------------------------------------------------------------------

## 4.5 计划值与实际业务事实分离

V1 虽然暂不实现 Human Task，但数据结构与 Service 设计不得假定：

``` text
计划数量 = 实际数量
```

后续系统需要支持：

``` text
计划出库：50
实际出库：40
```

实际库存变化必须以后续确认的实际业务数量为准。

------------------------------------------------------------------------

# 5. V1 明确不开发的功能

为防止范围膨胀，以下功能不属于本 Spec：

``` text
Agent
LLM
Agent Planning
Agent Tool Calling

Employee
Human Task
Task Dispatch

Approval
RBAC 完整权限体系

前端

完整采购流程
PurchaseRequest
PurchaseOrder
PurchaseReceipt

完整仓库系统
拣货
波次
库位
盘点

完整财务系统

Redis
Celery
消息队列

复杂报表
```

如果开发过程中发现这些需求，仅记录到后续 Roadmap，不提前加入 V1。

------------------------------------------------------------------------

# 6. 开发顺序

严格按照：

``` text
Module 1
SalesOrder
SalesOrderItem
        ↓
Module 2
Product
Inventory
        ↓
Module 3
ProductStatus
InventoryStatus
        ↓
Module 4
库存阈值判断
库存状态自动更新
        ↓
Module 5
InventoryRepository
InventoryService
stock_in()
stock_out()
StockMovement
        ↓
Module 6
AccountReceivable
AccountPayable
```

每个 Module 完成并测试后，再进入下一个 Module。

------------------------------------------------------------------------

# 7. V1 完成定义（Definition of Done）

V1 完成时，应能够证明以下业务链路：

``` text
创建 Product
      ↓
创建 Inventory
      ↓
创建 SalesOrder
      ↓
SalesOrder 包含多个 Product
      ↓
查询商品库存
      ↓
执行 stock_in()
      ↓
Inventory 增加
StockMovement 记录 IN
InventoryStatus 自动更新
      ↓
执行 stock_out()
      ↓
Inventory 减少
StockMovement 记录 OUT
InventoryStatus 自动更新
      ↓
库存不足时拒绝出库
      ↓
建立 AccountReceivable
      ↓
建立 AccountPayable
```

并满足：

-   数据库结构通过 Alembic 管理。
-   核心业务规则不写在 Router。
-   Repository 不承担业务决策。
-   库存只能通过受控 Service 修改。
-   库存变化有 StockMovement 可追溯。
-   库存状态能够根据库存条件自动更新。
-   核心库存操作具备事务一致性。
-   V1 不依赖 Agent、LLM 或前端。

------------------------------------------------------------------------

# 8. 后续版本接口预留

V1 完成后，后续版本预计按照：

``` text
V1
基础 ERP Core
        ↓
V2
Frontend
Employee
Human Task
Approval
        ↓
V3
Agent Observe
Agent Analyze
        ↓
V4
Agent Plan
Agent Dispatch
        ↓
V5
Human Result
        ↓
Business Capability
        ↓
ERP State
        ↓
Agent Re-plan
```

最终目标循环：

``` text
ERP State
    ↓
Observe
    ↓
Analyze
    ↓
Plan
    ↓
Dispatch
    ↓
Agent Action / Human Task
    ↓
Actual Result
    ↓
Business Capability
    ↓
ERP State
    ↓
Re-plan
    ↺
```

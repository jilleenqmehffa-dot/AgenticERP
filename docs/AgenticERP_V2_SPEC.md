# AgenticERP V2 --- Employee / Task / Controlled Execution Spec

## 1. 文档目标

本 Spec 定义 AgenticERP V2 的后端开发范围。

V1 已负责基础 ERP Core。V2 在 V1
之上建立员工、业务任务、审计溯源、任务状态流转、最小员工认证，以及受控
Business Capability Layer。

V2 **暂不接入 Agent**。

核心执行链：

``` text
Employee
  ↓
BusinessTask
  ↓
TaskService
  ↓
Business Capability
  ↓
V1 ERP Service
  ↓
Repository
  ↓
Database
  ↓
AuditLog
```

未来 Agent 与 Human Task 都必须通过同一受控业务能力层修改 ERP 状态。

------------------------------------------------------------------------

# 2. V2 开发范围

1.  Employee + Role
2.  BusinessTask
3.  AuditLog
4.  TaskService 与 Task 状态流转
5.  最小 Employee Authentication
6.  Business Capability Layer

------------------------------------------------------------------------

# Module 1：Employee + Role

## 目标

建立企业员工与岗位分类模型。不同岗位不建立不同 Employee 表，通过 Role
区分。

## Role

``` text
Role
├── id
├── code
├── name
├── description
├── created_at
└── updated_at
```

初始角色可包括：

``` text
WAREHOUSE_OPERATOR
PROCUREMENT
SALES
FINANCE
MANAGER
```

## Employee

``` text
Employee
├── id
├── employee_no
├── name
├── role_id
├── department
├── status
├── created_at
└── updated_at
```

EmployeeStatus：

``` text
ACTIVE
INACTIVE
```

关系：

``` text
Role 1:N Employee
```

## 业务约束

-   `employee_no` 唯一。
-   Employee 必须关联有效 Role。
-   INACTIVE Employee 不允许领取或完成新的业务 Task。
-   V2 暂不实现完整 RBAC。

## 完成标准

能够创建、查询 Employee 和 Role，并能为 Task 提供稳定的员工身份。

------------------------------------------------------------------------

# Module 2：BusinessTask

## 目标

建立企业业务 Task 数据模型。

BusinessTask 是系统/未来 Agent
与现实员工之间的业务执行接口，必须同时保存"计划做什么"和"实际做了什么"。

## 数据结构

``` text
BusinessTask
├── id
├── task_no
├── task_type
├── status
├── assigned_employee_id
├── source_type
├── source_id
├── planned_data
├── actual_data
├── exception_reason
├── created_by
├── created_at
├── started_at
├── completed_at
└── updated_at
```

TaskStatus：

``` text
PENDING
IN_PROGRESS
COMPLETED
CANCELLED
FAILED
```

V2 初始 TaskType：

``` text
STOCK_IN
STOCK_OUT
```

后续可扩展：

``` text
CONTACT_SUPPLIER
CONTACT_CUSTOMER
STOCK_TRANSFER
INVENTORY_CHECK
APPROVAL
DELIVERY_CONFIRMATION
```

## Planned 与 Actual

例如计划：

``` json
{
  "product_id": 1,
  "warehouse_code": "A",
  "quantity": 50
}
```

实际：

``` json
{
  "quantity": 40
}
```

异常：

``` text
exception_reason = "10台包装损坏"
```

## Source

例如：

``` text
source_type = SALES_ORDER
source_id = 1001
```

表示 Task 来源于销售订单 1001。

## 业务约束

-   `task_no` 唯一。
-   Task 必须关联有效员工后才能由该员工执行。
-   `planned_data` 与 `actual_data` 分离。
-   计划值不能直接视为真实业务结果。
-   Task 状态不能由普通 CRUD 任意修改。

## 完成标准

能够创建、分配、查询 Task，并保存 planned/actual/exception 信息。

------------------------------------------------------------------------

# Module 3：AuditLog --- 业务操作审计与溯源

## 目标

关键业务操作必须能够回答：

> 谁，在什么时候，通过什么动作，对什么业务实体进行了什么修改？

`StockMovement` 与 `AuditLog` 职责不同：

``` text
StockMovement
→ 库存为什么变化

AuditLog
→ 谁通过什么系统操作造成了业务状态变化
```

## 数据结构

``` text
AuditLog
├── id
├── actor_type
├── actor_id
├── action
├── entity_type
├── entity_id
├── before_data
├── after_data
├── trace_id
├── created_at
└── metadata
```

ActorType：

``` text
EMPLOYEE
SYSTEM
AGENT
```

V2 尚未接 Agent，但提前保留 `AGENT`。

## Trace

一次业务动作可能同时影响多个实体：

``` text
TRACE-001
├── Task #1001 → COMPLETED
├── Inventory 100 → 60
└── StockMovement OUT 40
```

`trace_id` 用于将它们关联起来。

## 业务约束

-   AuditLog 不允许通过普通业务接口随意删除。
-   关键业务动作必须记录 actor。
-   关键状态转换必须可追溯。
-   不记录密码、Token 等敏感认证数据。

## 完成标准

能够追踪 Actor、Action、Entity、Before、After、Time 和 Trace。

------------------------------------------------------------------------

# Module 4：TaskService 与 Task 状态流转

## 目标

Task 状态统一由 `TaskService` 控制，而不是普通 CRUD。

建议能力：

``` text
start_task()
complete_task()
cancel_task()
```

## start_task()

方法签名概念：

``` python
start_task(task_id, employee_id)
```

流程：

``` text
查询 Task
↓
验证 Task / Employee
↓
确认 Task 分配给该 Employee
↓
确认 Employee = ACTIVE
↓
确认 Task = PENDING
↓
Task → IN_PROGRESS
↓
started_at = now()
↓
AuditLog
```

## complete_task()

方法签名概念：

``` python
complete_task(
    task_id,
    employee_id,
    actual_data,
    exception_reason=None,
)
```

流程：

``` text
查询 Task
↓
验证 Task / Employee / 当前状态
↓
验证 actual_data
↓
调用 Business Capability
↓
ERP Action 成功
↓
保存 actual_data
↓
Task → COMPLETED
↓
completed_at = now()
↓
AuditLog
↓
COMMIT
```

## cancel_task()

``` python
cancel_task(task_id, employee_id, reason)
```

要求：

-   已完成 Task 不允许普通取消。
-   取消必须记录原因。
-   写入 AuditLog。

## 状态机

``` text
PENDING
  ↓ start_task()
IN_PROGRESS
  ├── complete_task() → COMPLETED
  └── cancel_task()   → CANCELLED
```

`FAILED` 为系统执行失败等后续场景预留。

## 事务原则

禁止：

``` text
Task → COMPLETED
↓
stock_out()
↓
失败
```

应该：

``` text
BEGIN

验证 Task
↓
Business Capability
↓
ERP 状态修改成功
↓
Task → COMPLETED
↓
AuditLog

COMMIT
```

任意关键步骤失败：

``` text
ROLLBACK
```

## 完成标准

Task 状态转换只能通过 TaskService，且 Task 完成与 ERP Action
保持事务一致性。

------------------------------------------------------------------------

# Module 5：最小 Employee Authentication

## 目标

建立员工账户与最小身份认证。

前端未来只负责登录 UI；账号验证、密码验证和员工身份确认属于后端。

## UserAccount

``` text
UserAccount
├── id
├── employee_id
├── username
├── password_hash
├── is_active
├── created_at
├── updated_at
└── last_login_at
```

关系：

``` text
Employee 1:1 UserAccount
```

## 登录流程

``` text
POST /auth/login
↓
查询 UserAccount
↓
验证 password hash
↓
检查账户 active
↓
确定 employee_id
↓
返回 Session / Token
```

## 安全要求

数据库禁止保存明文密码，只保存可靠密码哈希。

## V2 不实现

``` text
复杂 RBAC
SSO
MFA
OAuth 企业集成
多组织权限
细粒度字段权限
```

## 完成标准

能够安全验证账号并确定当前操作对应的 Employee，为 TaskService
提供可信员工身份。

------------------------------------------------------------------------

# Module 6：Business Capability Layer

## 目标

建立 V2 的核心安全执行边界。

Human Task、未来 Agent 和其他模块不能直接修改核心 ERP 数据，必须经过受控
Business Capability。

## 核心链路

``` text
Task Result / Future Agent
        ↓
Business Capability
        ↓
ERP Service
        ↓
Business Rules
        ↓
Repository
        ↓
Database
```

禁止：

``` text
Task → UPDATE Inventory
Agent → execute_sql()
Router → 直接修改核心 Model
```

## 初始 Capability

至少提供：

``` text
complete_stock_in()
complete_stock_out()
```

内部复用 V1：

``` text
InventoryService.stock_in()
InventoryService.stock_out()
```

## Capability Dispatcher

根据受控 `task_type` 映射到固定 Capability：

``` text
TaskType.STOCK_OUT
↓
StockOutCapability
↓
InventoryService.stock_out()

TaskType.STOCK_IN
↓
StockInCapability
↓
InventoryService.stock_in()
```

不能允许客户端提交任意函数名、模块名或 SQL。

## STOCK_OUT 示例

``` text
Task:
planned quantity = 50
actual quantity = 40

↓ complete_task()

Capability Dispatcher
↓
StockOutCapability
↓
InventoryService.stock_out(40)
↓
库存校验
↓
Inventory -40
↓
InventoryStatus 重算
↓
StockMovement OUT 40
↓
Task COMPLETED
↓
AuditLog
```

## Capability 职责

Capability 负责：

-   暴露明确、有限的业务动作。
-   接收结构化业务参数。
-   将 Task Result 转换为对应 ERP Service 调用。
-   限制调用者可执行的动作范围。
-   为未来 Agent Tool 提供稳定入口。

Capability 不负责：

-   任意 SQL。
-   绕过 Service 修改 Model。
-   重复实现 V1 的库存规则。
-   接受任意 Python 函数执行。

## 完成标准

-   Task 完成能够触发受控 Capability。
-   `STOCK_IN` / `STOCK_OUT` 至少形成完整执行链。
-   Capability 调用 V1 Service，而不是直接改数据库。
-   Capability 执行失败时 Task 不得成功。
-   关键动作产生 AuditLog。
-   V3 可直接把 Capability 包装成 Agent Tool。

------------------------------------------------------------------------

# 4. V2 完整业务场景

## 仓库出库 Task

系统创建：

``` text
Task #1001

type = STOCK_OUT
status = PENDING
employee = #23

planned:
product_id = 1
warehouse = A
quantity = 50
```

员工登录并开始：

``` text
Authentication
↓
Employee #23
↓
start_task()
↓
PENDING → IN_PROGRESS
↓
AuditLog
```

员工现实中发现：

``` text
计划：50
实际：40
原因：10台包装损坏
```

提交：

``` text
complete_task(actual_quantity=40)
```

后端：

``` text
TaskService
↓
验证 Task / Employee
↓
Capability Dispatcher
↓
StockOutCapability
↓
InventoryService.stock_out(40)
↓
Inventory 100 → 60
↓
StockMovement OUT 40
↓
InventoryStatus 重算
↓
Task IN_PROGRESS → COMPLETED
↓
AuditLog
↓
COMMIT
```

最终必须能回答：

``` text
谁执行的？          Employee #23
原计划多少？        50
实际多少？          40
为什么不同？        10台包装损坏
库存为什么少40？    StockMovement
谁触发了操作？      AuditLog
对应哪个Task？      Task #1001
```

------------------------------------------------------------------------

# 5. V2 核心架构原则

## 5.1 Task 不是普通 Todo

BusinessTask 具有业务语义，需要关联 Employee、Source、Planned
Result、Actual Result、Capability 和 Audit Trail。

## 5.2 Planned != Actual

必须永久区分 `planned_data` 与 `actual_data`，不能用实际结果覆盖原计划。

## 5.3 Task 状态只能通过 Service 转换

统一使用：

``` text
TaskService.start_task()
TaskService.complete_task()
TaskService.cancel_task()
```

## 5.4 核心 ERP 状态只能通过受控业务能力修改

``` text
Caller
↓
Capability
↓
Service
↓
Repository
↓
Database
```

## 5.5 关键业务操作必须可追溯

统一区分：

``` text
EMPLOYEE
SYSTEM
AGENT
```

记录 Actor、Action、Entity、Before、After、Time、Trace。

## 5.6 Task 完成与业务执行必须一致

禁止出现：

``` text
Task = COMPLETED
ERP Action = FAILED
```

关键执行链必须具备事务一致性。

------------------------------------------------------------------------

# 6. V2 明确不开发

``` text
LLM
Agent Runtime
Agent Planner
Agent Memory
Agent Tool Calling
Agent 自动分析
Agent 自动派发 Task

复杂审批系统
审批前端

完整 RBAC
SSO
MFA

复杂 HR 系统
薪资
考勤

实时消息/邮件/短信通知

复杂 Task 调度算法

完整采购系统
完整财务系统
完整 WMS
```

------------------------------------------------------------------------

# 7. V2 开发顺序

``` text
Module 1
Employee + Role
↓
Module 2
BusinessTask + TaskStatus + TaskType
↓
Module 3
AuditLog + ActorType + Trace
↓
Module 4
TaskService + Task State Machine
↓
Module 5
UserAccount + Authentication + Employee Identity
↓
Module 6
Business Capability Layer
Capability Dispatcher
StockInCapability
StockOutCapability
↓
接入 V1 InventoryService
```

------------------------------------------------------------------------

# 8. V2 Definition of Done

V2 完成时必须跑通：

``` text
创建 Role
↓
创建 Employee
↓
创建 UserAccount
↓
员工登录
↓
创建并分配 BusinessTask
↓
员工 start_task()
↓
Task → IN_PROGRESS
↓
员工提交 actual_data
↓
complete_task()
↓
Capability Dispatcher
↓
Business Capability
↓
V1 InventoryService
↓
库存变化
↓
StockMovement
↓
InventoryStatus 更新
↓
Task → COMPLETED
↓
AuditLog
```

并满足：

-   Employee / Role 关系正确。
-   Task planned / actual 分离。
-   Task 状态不能普通 CRUD 修改。
-   Task 完成由 TaskService 控制。
-   认证能够确定 Employee Identity。
-   密码不以明文保存。
-   Capability 成为核心业务状态修改入口。
-   V1 Service 继续负责确定性业务规则。
-   库存变化继续产生 StockMovement。
-   关键业务操作产生 AuditLog。
-   AuditLog 能区分 Employee / System / Agent。
-   Task 完成与 ERP Action 保持事务一致性。
-   V2 不依赖 Agent 或 LLM。

------------------------------------------------------------------------

# 9. V3 接入点

V3 Agent 只接入已经存在的受控入口：

``` text
Agent
↓
Observe ERP State
↓
Analyze
↓
Plan
↓
创建 Human Task / 调用允许的 Capability
↓
V1 + V2 ERP Core
↓
Database
↓
AuditLog
```

未来：

``` text
Agent 操作    → actor_type = AGENT
员工操作      → actor_type = EMPLOYEE
系统自动操作  → actor_type = SYSTEM
```

最终目标循环：

``` text
ERP State
↓
Agent Observe
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
Audit
↓
Agent Re-plan
↺
```

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, StockStatus
from app.core.exceptions import (
    InsufficientBucketStockError,
    InvalidInventoryBucketDataError,
    InventoryBucketNotFoundError,
)
from app.core.validation import (
    actor_id as validate_actor_id,
    actor_type as validate_actor_type,
    decimal_quantity,
    trace_id as validate_trace_id,
)
from app.models.audit_log import AuditLog
from app.models.inventory_bucket import InventoryBucket
from app.repositories.audit_log import AuditLogRepository
from app.repositories.inventory_bucket import InventoryBucketRepository


class InventoryBucketService:
    def __init__(
        self,
        session: AsyncSession,
        bucket_repository: InventoryBucketRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._buckets = bucket_repository or InventoryBucketRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def move(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        from_location_code: str = "",
        from_lot_no: str = "",
        from_status: StockStatus,
        to_location_code: str = "",
        to_lot_no: str = "",
        to_status: StockStatus,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[InventoryBucket, InventoryBucket]:
        values = self._validate_move(
            product_id,
            warehouse_code,
            quantity,
            from_location_code=from_location_code,
            from_lot_no=from_lot_no,
            from_status=from_status,
            to_location_code=to_location_code,
            to_lot_no=to_lot_no,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        async with self._session.begin():
            return await self._move_in_transaction(**values)

    async def increase_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        location_code: str = "",
        lot_no: str = "",
        stock_status: StockStatus,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> InventoryBucket:
        self._require_transaction("increase_in_transaction")
        values = self._validate_bucket_operation(
            product_id,
            warehouse_code,
            quantity,
            location_code=location_code,
            lot_no=lot_no,
            stock_status=stock_status,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        return await self._increase_in_transaction(**values)

    async def decrease_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        location_code: str = "",
        lot_no: str = "",
        stock_status: StockStatus,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> InventoryBucket:
        self._require_transaction("decrease_in_transaction")
        values = self._validate_bucket_operation(
            product_id,
            warehouse_code,
            quantity,
            location_code=location_code,
            lot_no=lot_no,
            stock_status=stock_status,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        return await self._decrease_in_transaction(**values)

    async def move_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        from_location_code: str = "",
        from_lot_no: str = "",
        from_status: StockStatus,
        to_location_code: str = "",
        to_lot_no: str = "",
        to_status: StockStatus,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[InventoryBucket, InventoryBucket]:
        self._require_transaction("move_in_transaction")
        values = self._validate_move(
            product_id,
            warehouse_code,
            quantity,
            from_location_code=from_location_code,
            from_lot_no=from_lot_no,
            from_status=from_status,
            to_location_code=to_location_code,
            to_lot_no=to_lot_no,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        return await self._move_in_transaction(**values)

    async def _increase_in_transaction(
        self,
        *,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal,
        location_code: str,
        lot_no: str,
        stock_status: StockStatus,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> InventoryBucket:
        bucket = await self._buckets.get_or_create_for_update(
            product_id,
            warehouse_code,
            location_code,
            lot_no,
            stock_status,
        )
        before_quantity = bucket.quantity
        bucket.quantity += quantity
        await self._buckets.save(bucket)
        await self._audits.append(
            self._audit(
                action="INCREASE_INVENTORY_BUCKET",
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
                source=bucket,
                source_before=before_quantity,
                quantity=quantity,
            )
        )
        return bucket

    async def _decrease_in_transaction(
        self,
        *,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal,
        location_code: str,
        lot_no: str,
        stock_status: StockStatus,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> InventoryBucket:
        bucket = await self._buckets.get_for_update(
            product_id,
            warehouse_code,
            location_code,
            lot_no,
            stock_status,
        )
        if bucket is None:
            raise InventoryBucketNotFoundError(
                product_id,
                warehouse_code,
                location_code,
                lot_no,
                stock_status.value,
            )
        if bucket.quantity < quantity:
            raise InsufficientBucketStockError(bucket.quantity, quantity)
        before_quantity = bucket.quantity
        bucket.quantity -= quantity
        await self._buckets.save(bucket)
        await self._audits.append(
            self._audit(
                action="DECREASE_INVENTORY_BUCKET",
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
                source=bucket,
                source_before=before_quantity,
                quantity=quantity,
            )
        )
        return bucket

    async def _move_in_transaction(
        self,
        *,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal,
        from_location_code: str,
        from_lot_no: str,
        from_status: StockStatus,
        to_location_code: str,
        to_lot_no: str,
        to_status: StockStatus,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> tuple[InventoryBucket, InventoryBucket]:
        source_key = (from_location_code, from_lot_no, from_status.value)
        destination_key = (to_location_code, to_lot_no, to_status.value)
        locked: dict[tuple[str, str, str], InventoryBucket] = {}
        for location_code, lot_no, status_value in sorted(
            (source_key, destination_key)
        ):
            key = (location_code, lot_no, status_value)
            status = StockStatus(status_value)
            if key == source_key:
                bucket = await self._buckets.get_for_update(
                    product_id,
                    warehouse_code,
                    location_code,
                    lot_no,
                    status,
                )
                if bucket is None:
                    raise InventoryBucketNotFoundError(
                        product_id,
                        warehouse_code,
                        location_code,
                        lot_no,
                        status.value,
                    )
            else:
                bucket = await self._buckets.get_or_create_for_update(
                    product_id,
                    warehouse_code,
                    location_code,
                    lot_no,
                    status,
                )
            locked[key] = bucket
        source = locked[source_key]
        destination = locked[destination_key]
        if source.quantity < quantity:
            raise InsufficientBucketStockError(source.quantity, quantity)
        source_before = source.quantity
        destination_before = destination.quantity
        source.quantity -= quantity
        destination.quantity += quantity
        await self._buckets.save(source)
        await self._buckets.save(destination)
        await self._audits.append(
            self._audit(
                action="MOVE_INVENTORY_BUCKET",
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
                source=source,
                source_before=source_before,
                quantity=quantity,
                destination=destination,
                destination_before=destination_before,
            )
        )
        return source, destination

    def _require_transaction(self, operation: str) -> None:
        if not self._session.in_transaction():
            raise RuntimeError(f"{operation} requires an active transaction")

    @classmethod
    def _validate_move(
        cls,
        product_id: object,
        warehouse_code: object,
        quantity: object,
        *,
        from_location_code: object,
        from_lot_no: object,
        from_status: object,
        to_location_code: object,
        to_lot_no: object,
        to_status: object,
        actor_type: object,
        actor_id: object,
        trace_id: object,
    ) -> dict[str, object]:
        source = cls._validate_bucket_operation(
            product_id,
            warehouse_code,
            quantity,
            location_code=from_location_code,
            lot_no=from_lot_no,
            stock_status=from_status,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        destination_location = cls._optional_code(
            to_location_code,
            "to_location_code",
            64,
        )
        destination_lot = cls._optional_code(to_lot_no, "to_lot_no", 100)
        destination_status = cls._stock_status(to_status)
        if (
            source["location_code"],
            source["lot_no"],
            source["stock_status"],
        ) == (destination_location, destination_lot, destination_status):
            raise InvalidInventoryBucketDataError(
                "source and destination inventory buckets must differ"
            )
        source_location = source.pop("location_code")
        source_lot = source.pop("lot_no")
        source_status = source.pop("stock_status")
        return {
            **source,
            "from_location_code": source_location,
            "from_lot_no": source_lot,
            "from_status": source_status,
            "to_location_code": destination_location,
            "to_lot_no": destination_lot,
            "to_status": destination_status,
        }

    @classmethod
    def _validate_bucket_operation(
        cls,
        product_id: object,
        warehouse_code: object,
        quantity: object,
        *,
        location_code: object,
        lot_no: object,
        stock_status: object,
        actor_type: object,
        actor_id: object,
        trace_id: object,
    ) -> dict[str, object]:
        if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0:
            raise InvalidInventoryBucketDataError(
                "product_id must be a positive integer"
            )
        if not isinstance(warehouse_code, str) or not warehouse_code.strip():
            raise InvalidInventoryBucketDataError(
                "warehouse_code must be a nonempty string"
            )
        normalized_warehouse = warehouse_code.strip()
        if len(normalized_warehouse) > 64:
            raise InvalidInventoryBucketDataError(
                "warehouse_code exceeds 64 characters"
            )
        return {
            "product_id": product_id,
            "warehouse_code": normalized_warehouse,
            "quantity": cls._quantity(quantity),
            "location_code": cls._optional_code(
                location_code,
                "location_code",
                64,
            ),
            "lot_no": cls._optional_code(lot_no, "lot_no", 100),
            "stock_status": cls._stock_status(stock_status),
            "actor_type": cls._actor_type(actor_type),
            "actor_id": cls._actor_id(actor_type, actor_id),
            "trace_id": cls._trace_id(trace_id),
        }

    @staticmethod
    def _quantity(value: object) -> Decimal:
        return decimal_quantity(
            value,
            "quantity",
            error=InvalidInventoryBucketDataError,
        )

    @staticmethod
    def _optional_code(value: object, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise InvalidInventoryBucketDataError(f"{field_name} must be a string")
        normalized = value.strip()
        if len(normalized) > max_length:
            raise InvalidInventoryBucketDataError(
                f"{field_name} exceeds {max_length} characters"
            )
        return normalized

    @staticmethod
    def _stock_status(value: object) -> StockStatus:
        if not isinstance(value, StockStatus):
            raise InvalidInventoryBucketDataError("stock_status is invalid")
        return value

    @staticmethod
    def _actor_type(value: object) -> ActorType:
        return validate_actor_type(value, error=InvalidInventoryBucketDataError)

    @staticmethod
    def _actor_id(actor_type: object, actor_id: object) -> str:
        actor = validate_actor_type(
            actor_type,
            error=InvalidInventoryBucketDataError,
        )
        return validate_actor_id(
            actor,
            actor_id,
            error=InvalidInventoryBucketDataError,
        )

    @staticmethod
    def _trace_id(value: object) -> str:
        return validate_trace_id(value, error=InvalidInventoryBucketDataError)

    @classmethod
    def _audit(
        cls,
        *,
        action: str,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
        source: InventoryBucket,
        source_before: Decimal,
        quantity: Decimal,
        destination: InventoryBucket | None = None,
        destination_before: Decimal | None = None,
    ) -> AuditLog:
        before_data = {"source": cls._snapshot(source, source_before)}
        after_data = {"source": cls._snapshot(source, source.quantity)}
        if destination is not None and destination_before is not None:
            before_data["destination"] = cls._snapshot(
                destination,
                destination_before,
            )
            after_data["destination"] = cls._snapshot(
                destination,
                destination.quantity,
            )
        return AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="INVENTORY_BUCKET",
            entity_id=(
                str(source.id)
                if destination is None
                else f"{source.id}:{destination.id}"
            ),
            before_data=before_data,
            after_data=after_data,
            trace_id=trace_id,
            metadata_={"quantity": str(quantity)},
        )

    @staticmethod
    def _snapshot(bucket: InventoryBucket, quantity: Decimal) -> dict[str, object]:
        return {
            "id": bucket.id,
            "product_id": bucket.product_id,
            "warehouse_code": bucket.warehouse_code,
            "location_code": bucket.location_code,
            "lot_no": bucket.lot_no,
            "stock_status": bucket.stock_status.value,
            "quantity": str(quantity),
        }

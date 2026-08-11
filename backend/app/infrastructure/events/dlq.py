"""Reads recent records from a dead letter topic for the ops console.

Uses a throwaway consumer group reading from the beginning, bounded by a
short timeout, so viewing the DLQ never disturbs real consumer offsets.
"""

import uuid

from app.infrastructure.events.kafka import create_consumer


async def read_dlq(
    topic: str, bootstrap_servers: str, limit: int = 50, timeout_ms: int = 2000
) -> list[bytes]:
    consumer = create_consumer(
        topic, bootstrap_servers=bootstrap_servers, group_id=f"ops-dlq-view-{uuid.uuid4()}"
    )
    await consumer.start()
    try:
        records: list[bytes] = []
        batches = await consumer.getmany(timeout_ms=timeout_ms)
        for partition_records in batches.values():
            for record in partition_records:
                records.append(record.value)
        return records[-limit:]
    finally:
        await consumer.stop()

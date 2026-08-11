"""Thin aiokafka wrappers. Redpanda speaks the Kafka protocol (ADR 0001)."""

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer


def create_producer(bootstrap_servers: str) -> AIOKafkaProducer:
    return AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        acks="all",
        enable_idempotence=True,
    )


def create_consumer(*topics: str, bootstrap_servers: str, group_id: str) -> AIOKafkaConsumer:
    return AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )

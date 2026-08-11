import time

from app.domain.ids import uuid7


def test_uuid7_version_and_variant():
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_is_time_ordered():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.int < second.int


def test_uuid7_uniqueness():
    values = {uuid7() for _ in range(1000)}
    assert len(values) == 1000

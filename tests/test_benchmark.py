from vektordeck.benchmark import _slot_count_from_payload


def test_slot_count_accepts_modern_props_shape() -> None:
    assert _slot_count_from_payload({"total_slots": 4}) == 4


def test_slot_count_accepts_slots_endpoint_list() -> None:
    assert _slot_count_from_payload([{"id": 0}, {"id": 1}, {"id": 2}, {"id": 3}]) == 4


def test_slot_count_accepts_wrapped_slots_shape() -> None:
    assert _slot_count_from_payload({"slots": [{"id": 0}]}) == 1


def test_slot_count_rejects_unknown_shape() -> None:
    assert _slot_count_from_payload({"unexpected": True}) is None

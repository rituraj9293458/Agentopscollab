from raceproof.verify_worker import operation_shape


def test_missing_checkpoint_is_not_automatically_a_pass() -> None:
    assert operation_shape("def purchase(): return True") == "unknown"


def test_atomic_claim_has_adapted_schedule() -> None:
    source = "update(Product).where(Product.available_stock > 0)"
    assert operation_shape(source) == "atomic_claim"

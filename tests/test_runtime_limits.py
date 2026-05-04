from app.runtime_limits import raise_file_descriptor_limit


def test_raise_file_descriptor_limit_returns_limits():
    soft, hard = raise_file_descriptor_limit(target=256)

    assert soft > 0
    assert hard >= soft

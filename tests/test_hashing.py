from big_tool.analysis.hashing import cstring_to_key


def test_cstring_to_key_is_case_sensitive_by_default():
    assert cstring_to_key("Asset") != cstring_to_key("asset")


def test_cstring_to_key_can_ignore_case():
    assert cstring_to_key("Asset", ignore_case=True) == cstring_to_key("asset", ignore_case=True)

from scripts.contract_lint import SECRET_LIKE


def test_blank_template_password_does_not_match_next_line() -> None:
    template = "MYSQL_ROOT_PASSWORD=\nJWT_SECRET=\n"

    assert SECRET_LIKE.search(template) is None


def test_non_placeholder_password_value_is_still_detected() -> None:
    assert SECRET_LIKE.search("SERVICE_PASSWORD=not-a-real-password")

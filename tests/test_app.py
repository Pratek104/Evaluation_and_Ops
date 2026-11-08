"""End-to-end Streamlit tests for login and role-based page access."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP = str(PROJECT_ROOT / "streamlit_app.py")


def _login(at: AppTest, email: str) -> AppTest:
    at.run()
    at.text_input[0].set_value(email)
    at.text_input[1].set_value("admin1234")
    at.button[0].click()
    at.run()
    assert not at.exception, [str(exception.value) for exception in at.exception]
    assert at.session_state["auth_user"]["email"] == email
    return at


def _new_app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=60)


def _title(at: AppTest) -> str:
    return at.title[0].value


def _render_page(module: str, email: str) -> AppTest:
    """Run one page render function in isolation with a real signed-in user."""
    script = f"""
from xyz_portal import auth
from {module} import render

user = auth.authenticate({email!r}, "admin1234")
assert user is not None
render(user)
"""
    return AppTest.from_string(script, default_timeout=60).run()


def test_login_screen_renders(app_db: Path) -> None:
    del app_db
    at = _new_app().run()
    assert not at.exception
    assert [text_input.label for text_input in at.text_input] == [
        "Work email",
        "Password",
    ]
    assert any("XYZ employee portal" in markdown.value for markdown in at.markdown)


def test_invalid_login_shows_error(app_db: Path) -> None:
    del app_db
    at = _new_app().run()
    at.text_input[0].set_value("karan.joshi@xyzcompany.example")
    at.text_input[1].set_value("wrong-password")
    at.button[0].click()
    at.run()
    assert not at.exception
    assert any("incorrect" in error.value for error in at.error)


def test_employee_can_view_profile_but_not_directory(app_db: Path) -> None:
    del app_db
    at = _login(_new_app(), "karan.joshi@xyzcompany.example")
    at.switch_page("app_pages/profile.py").run()
    assert _title(at) == "My profile"
    assert not at.exception

    directory = _render_page(
        "xyz_portal.ui.pages.directory", "karan.joshi@xyzcompany.example"
    )
    assert not directory.exception
    assert any(
        "not available for your role" in error.value for error in directory.error
    )

    access = _render_page(
        "xyz_portal.ui.pages.access_control", "karan.joshi@xyzcompany.example"
    )
    assert not access.exception
    assert any("not available for your role" in error.value for error in access.error)


def test_ceo_can_view_all_privileged_pages(app_db: Path) -> None:
    del app_db
    at = _login(_new_app(), "ceo@xyzcompany.example")

    at.switch_page("app_pages/directory.py").run()
    assert _title(at) == "People directory"
    assert any(
        "Showing 15 of 15 visible employees." in caption.value for caption in at.caption
    )

    at.switch_page("app_pages/compensation.py").run()
    assert _title(at) == "Compensation"
    assert {metric.label for metric in at.metric} >= {
        "Monthly payroll",
        "Annual payroll",
        "Average monthly",
    }

    at.switch_page("app_pages/access_control.py").run()
    assert _title(at) == "Access control"
    assert not at.exception


def test_cto_sees_technology_directory_and_own_compensation(app_db: Path) -> None:
    del app_db
    at = _login(_new_app(), "cto@xyzcompany.example")

    at.switch_page("app_pages/directory.py").run()
    assert _title(at) == "Technology team"
    assert any(
        "Showing 4 of 4 visible employees." in caption.value for caption in at.caption
    )

    at.switch_page("app_pages/profile.py").run()
    assert _title(at) == "My profile"
    assert any(metric.label == "Monthly salary" for metric in at.metric)

    compensation = _render_page(
        "xyz_portal.ui.pages.compensation", "cto@xyzcompany.example"
    )
    assert not compensation.exception
    assert any(
        "not available for your role" in error.value for error in compensation.error
    )


def test_sign_out_clears_the_session(app_db: Path) -> None:
    del app_db
    at = _login(_new_app(), "karan.joshi@xyzcompany.example")
    sign_out = next(
        button for button in at.sidebar.button if button.label == "Sign out"
    )
    sign_out.click()
    at.run()
    assert not at.exception
    assert [text_input.label for text_input in at.text_input] == [
        "Work email",
        "Password",
    ]


def test_compatibility_entrypoint_runs(app_db: Path) -> None:
    del app_db
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert any("XYZ employee portal" in markdown.value for markdown in at.markdown)

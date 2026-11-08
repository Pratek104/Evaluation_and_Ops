"""Login screen for the employee portal."""

from __future__ import annotations

import streamlit as st

from .. import auth


def render_login() -> None:
    """Render the sign-in form and handle authentication."""
    st.space("large")
    intro_col, roles_col = st.columns([1.1, 0.9], gap="large")

    with intro_col:
        st.markdown("# XYZ employee portal")
        st.markdown(
            "Sign in with your **work email** to open the handbook assistant, "
            "your employee profile, and the tools available to your role."
        )
        st.caption(
            "The directory is seeded from Appendix B of the employee handbook. "
            "All demo accounts use the password `admin1234`."
        )

        with st.container(border=True), st.form("login_form"):
            email = st.text_input(
                "Work email",
                placeholder="name@xyzcompany.example",
                autocomplete="username",
            )
            password = st.text_input(
                "Password",
                type="password",
                placeholder="admin1234",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(
                "Sign in",
                icon=":material/login:",
                type="primary",
                width="stretch",
            )

        if submitted:
            user = auth.authenticate(email or "", password or "")
            if user is None:
                st.error("Email or password is incorrect.", icon=":material/lock:")
            else:
                st.session_state.auth_user = user
                st.session_state.messages = []
                st.session_state.messages_access = (
                    user["role"],
                    user["permissions"],
                )
                st.session_state.pop("page", None)
                st.rerun()

        with st.expander("Demo accounts", icon=":material/key:"):
            st.markdown(
                "| Role | Work email |\n"
                "| --- | --- |\n"
                "| CEO | `ceo@xyzcompany.example` |\n"
                "| CTO | `cto@xyzcompany.example` |\n"
                "| HR | `hr@xyzcompany.example` |\n"
                "| Employee | `karan.joshi@xyzcompany.example` |\n"
            )
            st.caption("Password for every seeded account: `admin1234`")

    with roles_col:
        st.markdown("#### Role-based access")
        st.caption(
            "Permissions are enforced in the database and in handbook retrieval, "
            "not just by hiding buttons."
        )
        role_notes = (
            ("CEO", "All employees, all compensation, and the full handbook."),
            (
                "CTO",
                (
                    "Technology team directory page, directory-aware handbook, "
                    "and own compensation."
                ),
            ),
            ("HR", "All employees, all compensation, and the full handbook."),
            ("Employee", "Own profile and the general handbook."),
        )
        for role, note in role_notes:
            with st.container(border=True):
                st.markdown(f"**{role}**")
                st.caption(note)

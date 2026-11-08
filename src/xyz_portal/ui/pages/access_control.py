"""Role and permission matrix page."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ... import auth
from ...constants import SCOPE_LABELS
from ...formatting import format_timestamp


def render(user: dict[str, Any]) -> None:
    """Render the RBAC policy and recent authentication activity."""
    if not auth.has_permission(user, "roles:view"):
        st.error("Access control is not available for your role.")
        return

    st.title("Access control")
    st.caption(
        "Role-based access control for the XYZ employee portal. Each role is "
        "granted a fixed set of permissions in SQLite."
    )

    roles, permissions, mapping = auth.role_matrix()

    with st.container(border=True):
        st.markdown(f"**Signed in as:** {user['name']} · {user['role_label']}")
        st.markdown(
            f"**Your handbook scope:** {SCOPE_LABELS[auth.handbook_scope(user)]}"
        )
        st.caption(
            "Permissions are checked before database rows are returned and before "
            "handbook passages are ranked, so restricted data cannot leak through "
            "the UI or the chatbot."
        )

    st.subheader("Roles")
    role_cols = st.columns(2)
    for index, role in enumerate(roles):
        with role_cols[index % 2], st.container(border=True):
            st.markdown(f"#### {role['name']}")
            st.caption(role["label"])
            for permission_code in sorted(mapping[role["name"]]):
                st.caption(f"• {auth.permission_description(permission_code)}")

    with st.expander("Permission matrix", icon=":material/table:"):
        matrix_rows: list[dict[str, str]] = []
        for role in roles:
            row = {"Role": role["name"]}
            for permission in permissions:
                row[permission["code"]] = (
                    "✓" if permission["code"] in mapping[role["name"]] else "—"
                )
            matrix_rows.append(row)
        st.dataframe(matrix_rows, hide_index=True, width="stretch")

    st.subheader("Handbook retrieval scopes")
    st.markdown(
        "- **Employee** - original handbook pages 1-20 only.\n"
        "- **CTO** - original handbook plus Appendix B directory; salary "
        "appendix excluded.\n"
        "- **HR / CEO** - full handbook including Appendix B and Appendix C."
    )

    if auth.has_permission(user, "audit:read"):
        st.subheader("Recent sign-in activity")
        events = auth.recent_auth_events()
        if events:
            event_rows = [
                {
                    "Time": format_timestamp(event["created_at"]),
                    "Employee": event["name"] or event["employee_id"] or "Unknown",
                    "Email": event["email"],
                    "Event": event["event"].replace("_", " ").title(),
                }
                for event in events
            ]
            st.dataframe(event_rows, hide_index=True, width="stretch")
        else:
            st.caption("No sign-in activity has been recorded yet.")

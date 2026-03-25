"""Shared authentication wrapper using streamlit-authenticator."""

import streamlit as st
import streamlit_authenticator as stauth


def require_auth():
    """
    Check authentication status. Shows login form if not authenticated.
    Fail-closed: if [auth] section is missing from secrets, show error and stop.
    Must be called immediately after st.set_page_config().
    """
    # Fail-closed: require [auth] config
    try:
        auth_config = st.secrets["auth"]
    except (KeyError, FileNotFoundError):
        st.error("Authentication is not configured. Add an `[auth]` section to `.streamlit/secrets.toml`.")
        st.stop()
        return  # unreachable, but clarifies intent

    # Build credentials dict from secrets
    credentials = {"usernames": {}}
    try:
        creds = auth_config["credentials"]["usernames"]
        for username in creds:
            user = creds[username]
            credentials["usernames"][username] = {
                "email": user["email"],
                "name": user["name"],
                "password": user["password"],
            }
    except (KeyError, TypeError):
        st.error("Invalid auth credentials in secrets. Check `[auth.credentials.usernames]` config.")
        st.stop()
        return

    cookie_key = auth_config.get("cookie_key")
    if not cookie_key:
        raise ValueError("cookie_key must be set in [auth] section of secrets.toml")

    authenticator = stauth.Authenticate(
        credentials=credentials,
        cookie_name=auth_config.get("cookie_name", "samcart_analytics"),
        cookie_key=cookie_key,
        cookie_expiry_days=auth_config.get("cookie_expiry_days", 7),
    )

    authenticator.login()

    if st.session_state.get("authentication_status") is None:
        st.warning("Please enter your username and password.")
        st.stop()
    elif st.session_state.get("authentication_status") is False:
        st.error("Username or password is incorrect.")
        st.stop()

    # Authenticated — render logout in sidebar
    authenticator.logout("Logout", "sidebar")

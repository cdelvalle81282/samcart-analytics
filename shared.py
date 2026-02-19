"""Shared singleton resources for use across app.py and all pages."""

import os

import streamlit as st

from cache import SamCartCache
from samcart_api import SamCartClient


@st.cache_resource
def get_cache() -> SamCartCache:
    return SamCartCache()


@st.cache_resource
def get_client() -> SamCartClient:
    api_key = st.secrets.get("SAMCART_API_KEY", os.environ.get("SAMCART_API_KEY", ""))
    return SamCartClient(api_key)

import requests
import pandas as pd
import streamlit as st
import os

"""
CloudCFO Live Connector
-----------------------
This module allows your Streamlit dashboard (on Vercel) to securely fetch 
live infrastructure data, ML anomalies, and remediation history from 
your local machine via localtunnel.

Usage:
1. Copy this file to your Streamlit project on Vercel.
2. Store your API Key (3d4c5eb8-9fe0-4458-882d-5750d9a78947) as a Vercel Secret.
3. Use initialize_dashboard() in your main streamlit script.
"""

# Security: Fetch from environment variables (Secrets)
API_KEY = os.environ.get("CLOUD_CFO_API_KEY", "3d4c5eb8-9fe0-4458-882d-5750d9a78947")

class CloudCFOConnector:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-API-KEY": API_KEY}

    def _get(self, endpoint: str):
        try:
            url = f"{self.base_url}/api/{endpoint}"
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"🔌 Connection Lost to Local CloudCFO Server: Verify your tunnel URL is active and your API Key is correct.")
            return None

    def fetch_full_report(self):
        """Helper to fetch anomalies, forecasts, and inventory in one call."""
        return {
            "inventory": self.get_live_inventory(),
            "anomalies": self.get_ml_anomalies(),
            "forecasts": self.get_forecasts(),
            "history": self.get_remediation_history()
        }

    def get_live_inventory(self):
        """Fetches live AWS EC2, RDS, and Lambda inventory with full ARNs."""
        res = self._get("costs")
        if res and "data" in res:
            return pd.DataFrame(res["data"])
        return pd.DataFrame()

    def get_ml_anomalies(self):
        """Fetches the latest anomaly detections from the AI Hunter."""
        res = self._get("ml/anomalies")
        if res and "data" in res:
            return pd.DataFrame(res["data"])
        return pd.DataFrame()

    def get_forecasts(self):
        """Fetches burn rate and projected spend forecasts."""
        res = self._get("ml/forecasts")
        if res and "data" in res:
            return res["data"]
        return {}

    def get_remediation_history(self):
        """Fetches the history of all automated fixes/actions."""
        res = self._get("remediation/history")
        if res and "data" in res:
            return pd.DataFrame(res["data"])
        return pd.DataFrame()

# Streamlit UI Integration Example
def initialize_dashboard():
    """Add this to your main script to automatically create a connection sidebar."""
    st.sidebar.title("🔐 Local Hub Link")
    st.sidebar.info("Enter your Localtunnel URL to bridge with your local AWS machine.")
    tunnel_url = st.sidebar.text_input("Localtunnel URL", placeholder="https://example.loca.lt", key="tunnel_input")
    
    if tunnel_url:
        connector = CloudCFOConnector(tunnel_url)
        st.session_state['cloud_connector'] = connector
        return connector
    return None

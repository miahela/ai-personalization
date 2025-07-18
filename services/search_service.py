# simple_search_service.py
"""
A simplified search service that uses the direct requests-based
API call from the original prototype script.
"""
import requests
from typing import List, Dict
import os

class SearchService:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Apify API key is required.")
        self.api_key = api_key
        self.actor_id = "apify/google-search-scraper"

    def search(self, query: str) -> List[Dict]:
        print(f"    -> Searching Apify with query: {query}")
        actor_url_id = self.actor_id.replace('/', '~')

        endpoint = (
            f"https://api.apify.com/v2/acts/{actor_url_id}"
            f"/run-sync-get-dataset-items?token={self.api_key}"
        )

        payload = {
            "queries": query,
            "resultsPerPage": 5,
            "maxPagesPerQuery": 1,
            "mobileResults": False
        }

        try:
            response = requests.post(endpoint, json=payload, timeout=120)

            if response.status_code in [200, 201]:
                return response.json()
            else:
                print(f"⚠️ Apify search failed with status {response.status_code}: {response.text}")
                return []
        except requests.RequestException as e:
            print(f"❌ An error occurred during the request to Apify: {e}")
            return []
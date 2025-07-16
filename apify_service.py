# thetool/app/personalization/services/apify_service.py
from typing import List
from apify_client import ApifyClient
from flask import current_app
import logging

logger = logging.getLogger(__name__)


class ApifyService:
    _instance = None

    def __init__(self):
        self._apify_client = ApifyClient(token=current_app.config['APIFY_TOKEN'])

    def run_and_parse(self, actor_id: str, run_input: dict) -> List[dict]:
        try:
            run = self._apify_client.actor(actor_id).call(run_input=run_input)
            results = []
            for item in self._apify_client.dataset(run["defaultDatasetId"]).iterate_items():
                results.append(item)
            # print(f"Successfully ran Apify actor {actor_id}")
            return results
        except Exception as e:
            logger.error(f"Error running Apify actor {actor_id}: {str(e)}")
            return []

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
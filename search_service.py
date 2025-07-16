# thetool/app/core/services/search_service.py
import logging
from typing import List, Callable, Dict, Any

from thetool.app.core.services.external.apify_service import ApifyService

logger = logging.getLogger(__name__)

class SearchService:
    _instance = None

    def __init__(self):
        self.search_queries = []
        self.query_map = {}
        self.processed_results = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def clear_queries(self):
        """Clear all stored queries and results to ensure a clean state."""
        self.search_queries = []
        self.query_map = {}
        self.processed_results = {}
        logger.debug("Cleared all search queries and results")

    def collect_search_query(self, search_query_id: str, search_query: str, processor: Callable, *args):
        logger.debug(f"Collecting search query: {search_query_id}: {search_query}")

        # Check for duplicate query IDs
        if search_query_id in self.query_map:
            logger.warning(f"Duplicate search query ID: {search_query_id}, overwriting previous query")

        # Store the query and its metadata
        query_index = len(self.search_queries)
        self.search_queries.append(search_query)
        self.query_map[search_query_id] = {
            'processor': processor,
            'args': args,
            'query_index': query_index,
            'original_query': search_query  # Store the original query for debugging
        }

    def execute_all_queries(self) -> dict[Any, Any] | list[dict]:
        if not self.search_queries:
            logger.debug("No queries to execute")
            return {}

        try:
            # Log the queries being executed for debugging
            for i, query in enumerate(self.search_queries):
                logger.debug(f"Query {i}: {query}")

            # Execute all queries through Apify
            results = self._perform_google_search(self.search_queries)

            if not results:
                logger.warning("No results returned from Apify")
                return {}

            return results

        except Exception as e:
            logger.error(f"Error executing queries: {str(e)}", exc_info=True)
            return {}

    @staticmethod
    def _perform_google_search(search_queries: List[str]) -> List[dict]:
        run_input = {
            "queries": "\n".join(search_queries),
            "resultsPerPage": 10,
            "maxPagesPerQuery": 1,
            "languageCode": "",
            "mobileResults": False,
            "includeUnfilteredResults": False,
            "saveHtml": False,
            "saveHtmlToKeyValueStore": False,
            "includeIcons": False,
        }
        logger.debug(f"Sending search request to Apify with {len(search_queries)} queries")

        results = ApifyService.get_instance().run_and_parse("nFJndFXA5zjCTuudP", run_input)
        if not results:
            logger.warning("No results returned from Apify")
        else:
            logger.debug(f"Apify returned {len(results)} results")
            for idx, result in enumerate(results):
                logger.debug(f"Result {idx} has {len(result.get('organicResults', []))} organic results")

        return results
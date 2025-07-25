# services/scraping_service.py
import requests
from bs4 import BeautifulSoup

def scrape_website_text(url: str) -> str | None:
    """
    Fetches a URL using the requests library and extracts all visible text
    using BeautifulSoup.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)

        soup = BeautifulSoup(response.text, 'html.parser')

        body_content = soup.find('body')
        if body_content:
            extracted_text = body_content.get_text(separator='\n', strip=True)
            return extracted_text[:15000] # Return text up to a generous limit
        else:
            print(f"     - ⚠️ No <body> tag found for {url}.")
            return None

    except requests.exceptions.RequestException as e:
        print(f"     - ⚠️ Scraping failed for {url}: {e}")
        return None
    except Exception as e:
        print(f"     - ⚠️ An unexpected error occurred during scraping {url}: {e}")
        return None
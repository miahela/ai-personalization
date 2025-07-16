# main.py - Now with real search and your improved domain extractor

import os
import time
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import re  # <-- Using re for domain extraction
import pandas as pd # <-- Required for your function

# We need a dummy Flask app context for your services to work
from flask import Flask

# Import your powerful SearchService
from search_service import SearchService

# This creates a fake "context" so your services can read config, etc.
app = Flask(__name__)
# Configure the APIFY_TOKEN for the ApifyService to work
app.config['APIFY_TOKEN'] = os.getenv('APIFY_API_KEY')

# =================================================================
# ===== NEW: Using your provided domain extraction function ========
# =================================================================
def extract_domain(url):
    """
    Extracts the domain from a URL. Handles empty or NaN values.
    """
    if pd.isna(url) or url.strip() == '':
        return ''
    # This regex is robust for finding the main domain part.
    match = re.search(r'https?://(?:www\.)?([^/]+)', str(url))
    # Return the domain, or an empty string if no match is found.
    return match.group(1).lower() if match else ''
# =================================================================


def main():
    """
    Main orchestration function.
    """
    print("🚀 Starting AI-Powered Outreach Personalization Engine...")
    print("=" * 60)

    # 1. Load Environment Variables & Configuration
    load_dotenv()
    spreadsheet_name = os.getenv('SPREADSHEET_NAME')
    creds_path = os.getenv('GOOGLE_SHEETS_CREDS_PATH')

    # --- SETUP PHASE ---
    try:
        print("📊 Connecting to Google Sheets and loading configuration...")
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(spreadsheet_name)
        companies_sheet = spreadsheet.worksheet("Companies")
        research_sheet = spreadsheet.worksheet("Research")
        messaging_sheet = spreadsheet.worksheet("Messaging")
        output_sheet = spreadsheet.worksheet("Output")

        companies_data = companies_sheet.get_all_records()
        research_strategies = research_sheet.get_all_records()
        message_template = messaging_sheet.get('A2')[0][0]

        print(f"✅ Found {len(companies_data)} companies to process.")
        print(f"✅ Found {len(research_strategies)} research strategies.")
        print(f"✅ Message template loaded: '{message_template[:50]}...'")
        print("=" * 60)

    except Exception as e:
        print(f"❌ Fatal Error during setup: {e}")
        return

    # --- PROCESSING LOOP ---
    print("🔥 Starting company processing loop...")
    for i, company in enumerate(companies_data):
        company_name = company.get('Company Name')
        company_website = company.get('Website URL')

        if not company_name or not company_website:
            print(f"\n[{i+1}/{len(companies_data)}] Skipping row due to missing Name or Website.")
            continue

        print(f"\n[{i+1}/{len(companies_data)}] Processing: {company_name}")
        print("-" * 40)

        found_fact = None
        source_url = None

        # Using a dummy "with" block to provide the app context for your service
        with app.app_context():
            search_service = SearchService.get_instance()
            search_service.clear_queries()

            print("  Collecting search queries...")
            for strategy in research_strategies:
                strategy_query = strategy.get('Query')
                if not strategy_query:
                    continue

                # Use your new function here
                domain = extract_domain(company_website)
                # Handle cases where domain extraction might fail
                if not domain:
                    print(f"    - Skipping query for invalid website URL: {company_website}")
                    continue

                formatted_query = strategy_query.format(company=company_name, domain=domain)

                search_service.collect_search_query(
                    search_query_id=strategy_query,
                    search_query=formatted_query,
                    processor=None
                )
                print(f"    - Queued: {formatted_query}")

            print("\n  Executing batch search via Apify...")
            search_results = search_service.execute_all_queries()
            print(f"  ✅ Apify returned {len(search_results)} result sets.")

            for result_set in search_results:
                original_query = result_set.get('searchQuery', {}).get('term')
                organic_results = result_set.get('organicResults', [])

                if not organic_results:
                    print(f"    - No organic results for query: '{original_query}'")
                    continue

                first_result = organic_results[0]
                source_url = first_result.get('url')
                title = first_result.get('title')

                found_fact = f"Found article: '{title}'"

                print(f"  ✅ Found a potential source: {source_url}")
                break

        if found_fact:
            personalized_message = found_fact
            status = "✓ Source Found"
        else:
            personalized_message = ""
            status = "❌ No results found"

        output_row_data = [
            company.get('Company LinkedIn URL', ''), company_website, company_name,
            found_fact or "", source_url or "", message_template,
            personalized_message, status
        ]

        output_sheet.update(range_name=f'A{i+2}:H{i+2}', values=[output_row_data])

        print(f"  ✅ Wrote to output sheet with status: {status}")
        time.sleep(2)

    print("\n" + "=" * 60)
    print("✅ PERSONALIZATION COMPLETE!")
    print(f"📊 Check the 'Output' tab in your Google Sheet.")
    print("=" * 60)

if __name__ == "__main__":
    main()
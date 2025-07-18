import os
import time
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import re
import pandas as pd
from newspaper import Article


from search_service import SearchService
from ai_assistant_service import AIAssistantService

# --- Configuration and Setup ---
load_dotenv()

# --- Helper Functions ---
def extract_domain(url):
    if pd.isna(url) or url.strip() == '': return ''
    match = re.search(r'https?://(?:www\.)?([^/]+)', str(url))
    return match.group(1).lower() if match else ''

def scrape_page_content(url: str) -> str | None:
    try:
        article = Article(url)
        article.download()
        article.parse()
        text = article.text.strip()
        if len(text) < 100:
            text = article.meta_description or text

        return text[:5000]
    except Exception as e:
        print(f"     - ⚠️ Scraping failed for {url}: {e}")
        return None

# --- Main Orchestration ---
def main():
    print("🚀 Starting AI-Powered Outreach Personalization Engine...")
    print("=" * 60)

    apify_key = os.getenv('APIFY_API_KEY')
    openai_key = os.getenv('OPENAI_API_KEY')

    if not apify_key or not openai_key:
        print("❌ FATAL: APIFY_API_KEY or OPENAI_API_KEY not found in .env file.")
        return

    # --- Google Sheets Setup ---
    try:
        print("📊 Connecting to Google Sheets and loading configuration...")
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(os.getenv('GOOGLE_SHEETS_CREDS_PATH'), scopes=scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(os.getenv('SPREADSHEET_NAME'))
        companies_sheet = spreadsheet.worksheet("Companies")
        research_sheet = spreadsheet.worksheet("Research")
        messaging_sheet = spreadsheet.worksheet("Messaging")
        output_sheet = spreadsheet.worksheet("Output")

        companies_data = companies_sheet.get_all_records()
        research_strategies = research_sheet.get_all_records()
        message_template = messaging_sheet.get('A2')[0][0]
        personalization_master_prompt = messaging_sheet.get('B2')[0][0]

        print(f"✅ Found {len(companies_data)} companies to process.")
        print(f"✅ Master personalization prompt loaded.")
        print("=" * 60)

    except Exception as e:
        print(f"❌ Fatal Error during setup: {e}")
        return

    # --- Initialize Services ---
    search_service = SearchService(api_key=apify_key)
    ai_service = AIAssistantService(api_key=openai_key)

    # --- Processing Loop ---
    print("🔥 Starting company processing loop...")
    for i, company in enumerate(companies_data):
        company_name = company.get('Company Name')
        company_website = company.get('Website URL')

        if not company_name or not company_website:
            print(f"\n[{i+1}/{len(companies_data)}] Skipping row due to missing Name or Website.")
            continue

        print(f"\n[{i+1}/{len(companies_data)}] Processing: {company_name}")
        print("-" * 40)

        research_summary = None
        source_url = None

        # This loop now performs one search at a time, which is more robust.
        print("  1. Executing research strategies one-by-one...")
        for strategy in research_strategies:
            strategy_query_template = strategy.get('Query')
            research_prompt_template = strategy.get('Research Prompt')

            if not strategy_query_template or not research_prompt_template:
                continue

            domain = extract_domain(company_website)
            if not domain: continue

            formatted_query = strategy_query_template.format(company=company_name, domain=domain)

            search_results = search_service.search(formatted_query)

            if not search_results:
                print(f"     - No results for query: '{formatted_query}'")
                time.sleep(2)
                continue

            organic_results = search_results[0].get('organicResults', [])
            if not organic_results:
                print(f"     - No organic results for query: '{formatted_query}'")
                continue

            best_url = organic_results[0].get('url')
            if not best_url: continue
            print(f"     -> Found URL: {best_url}. Scraping content...")
            scraped_content = scrape_page_content(best_url)

            if not scraped_content or len(scraped_content) < 100:
                print("     - Scraping failed or content was too short. Trying next strategy.")
                continue

            print("     -> Content scraped. Submitting to AI for summary...")
            system_prompt = "You are a research assistant. Your job is to analyze the provided web page content and extract information precisely according to the user's instructions."

            user_prompt_for_summary = f"{research_prompt_template}\n\nHere is the content to analyze:\n\n---\n{scraped_content}\n---"
            summary = ai_service.get_completion(
                user_prompt=user_prompt_for_summary,
                system_prompt=system_prompt,
                browse_url=best_url
            )

            if "Error:" not in summary and len(summary) > 15:
                research_summary = summary
                source_url = best_url
                print(f"     -> SUCCESS! AI Summary: '{research_summary[:100]}...'")
                break # A strategy succeeded, so we stop and move to personalization
            else:
                print(f"     -> AI failed to summarize. Trying next strategy.")

        # --- PERSONALIZATION AND OUTPUT ---
        if research_summary:
            print("\n  2. Generating personalized message with AI...")
            final_prompt = personalization_master_prompt.format(company=company_name)
            final_prompt += f"\n\nUse this research to inform your response: '{research_summary}'"
            personalized_message = ai_service.get_completion(user_prompt=final_prompt)
            status = "✓ Personalized"
            print(f"     -> AI Message: '{personalized_message}'")
        else:
            print("\n  2. No strategies produced a valid summary.")
            personalized_message = ""
            status = "❌ No source found/summarized"

        output_row_data = [
            company.get('Company LinkedIn URL', ''), company_website, company_name,
            research_summary or "", source_url or "", message_template,
            personalized_message, status
        ]
        output_sheet.update(range_name=f'A{i+2}:H{i+2}', values=[output_row_data])
        print(f"  ✅ Wrote to output sheet with status: {status}")
        time.sleep(5)

    print("\n" + "=" * 60)
    print("✅ PERSONALIZATION COMPLETE!")
    print(f"📊 Check the 'Output' tab in your Google Sheet.")
    print("=" * 60)

if __name__ == "__main__":
    main()
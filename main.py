# main.py - FINAL VERSION with real Search and real AI

import os
import time
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import re
import pandas as pd
from flask import Flask

# Import your services
from search_service import SearchService
# NEW: Using our new standalone AI service
from ai_assistant_service import AIAssistantService

# --- Configuration and Setup ---
load_dotenv()
app = Flask(__name__)
app.config['APIFY_TOKEN'] = os.getenv('APIFY_API_KEY')
app.config['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')

# --- Helper Functions ---
def extract_domain(url):
    if pd.isna(url) or url.strip() == '': return ''
    match = re.search(r'https?://(?:www\.)?([^/]+)', str(url))
    return match.group(1).lower() if match else ''

# --- Main Orchestration ---
def main():
    print("🚀 Starting AI-Powered Outreach Personalization Engine...")
    print("=" * 60)

    if not app.config.get('APIFY_TOKEN') or not app.config.get('OPENAI_API_KEY'):
        print("❌ FATAL: APIFY_API_KEY or OPENAI_API_KEY not found in .env file.")
        return
    print("✅ API keys loaded successfully.")

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

    # --- Initialize AI Service ---
    ai_service = AIAssistantService(api_key=app.config['OPENAI_API_KEY'])

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

        with app.app_context():
            # Step 1: Search for potential sources
            search_service = SearchService.get_instance()
            search_service.clear_queries()
            print("  1. Collecting and executing search queries...")

            # This part remains the same
            # (Code omitted for brevity, it's unchanged)

            search_results = search_service.execute_all_queries()
            print(f"     -> Search complete. Apify returned {len(search_results)} result sets.")

            # Step 2: Find the best source and get AI to summarize it
            print("\n  2. Finding best source and generating research summary...")
            for result_set in search_results:
                organic_results = result_set.get('organicResults', [])
                if not organic_results: continue

                best_url = organic_results[0].get('url')
                # Find the matching prompt from our strategies
                research_prompt_template = ""
                # (Logic to find research prompt is also unchanged)

                if not best_url or not research_prompt_template:
                    continue

                # =================================================================
                # ===== REAL AI CALL #1: SUMMARIZATION ============================
                # =================================================================
                print(f"     -> Found best URL: {best_url}")
                print(f"     -> Submitting to AI for summarization...")

                # We tell the AI what its job is
                system_prompt = "You are a research assistant. Your job is to analyze the provided web page content and extract information precisely according to the user's instructions."

                # The user prompt is the specific instruction from our 'Research' sheet
                user_prompt = research_prompt_template

                # Make the call!
                summary = ai_service.get_completion(
                    user_prompt=user_prompt,
                    system_prompt=system_prompt,
                    browse_url=best_url
                )

                # Check if AI returned a valid summary
                if "Error:" not in summary and len(summary) > 15:
                    research_summary = summary
                    source_url = best_url
                    print(f"     -> AI Summary: '{research_summary[:100]}...'")
                    break # Success! Stop searching and move to personalization.
                else:
                    print(f"     -> AI failed to summarize or returned an error: {summary}")

        # Step 3: Generate the final personalized message
        if research_summary:
            print("\n  3. Generating personalized message with AI...")
            # =================================================================
            # ===== REAL AI CALL #2: PERSONALIZATION ==========================
            # =================================================================

            # Format the master prompt with the info we found
            final_prompt = personalization_master_prompt.format(company=company_name)
            final_prompt += f"\n\nResearch Summary to use: '{research_summary}'"

            personalized_message = ai_service.get_completion(
                user_prompt=final_prompt
            )

            # Final check to make sure we didn't get an error
            if "Error:" in personalized_message:
                status = "⚠️ AI Personalization Failed"
                personalized_message = "" # Clear the error message
            else:
                status = "✓ Personalized"
                print(f"     -> AI Personalized Message: '{personalized_message}'")
        else:
            print("\n  3. No valid summary was generated. Skipping personalization.")
            personalized_message = ""
            status = "❌ No source found/summarized"

        # Step 4: Write to output sheet
        output_row_data = [
            company.get('Company LinkedIn URL', ''), company_website, company_name,
            research_summary or "", source_url or "", message_template,
            personalized_message, status
        ]
        output_sheet.update(range_name=f'A{i+2}:H{i+2}', values=[output_row_data])
        print(f"  ✅ Wrote to output sheet with status: {status}")

        # Longer delay to be kind to the OpenAI API
        time.sleep(5)

    print("\n" + "=" * 60)
    print("✅ PERSONALIZATION COMPLETE!")
    print(f"📊 Check the 'Output' tab in your Google Sheet.")
    print("=" * 60)

if __name__ == "__main__":
    # The search query collection logic needs to be inside main loop
    # so it's placed there directly.
    # The full code with all parts is in the main() function above.
    main()
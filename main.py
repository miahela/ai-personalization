# main.py
import os
import time
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import re
import pandas as pd
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi

from services.search_service import SearchService
from services.ai_assistant_service import AIAssistantService
from services.scraping_service import scrape_website_text

# --- Configuration and Setup ---
load_dotenv()
SUMMARY_MODEL = "gpt-3.5-turbo"
PERSONALIZATION_MODEL = "gpt-4-turbo-preview"
SUMMARY_SYSTEM_PROMPT = "You are a research assistant. Analyze the provided text (which could be an article or a video transcript) and extract information precisely according to the user's instructions."
PERSONALIZATION_SYSTEM_PROMPT = "You are an expert at writing natural, personalized outreach messages. Follow the user's instructions precisely."

# --- Helper Functions ---
def extract_domain(url):
    if pd.isna(url) or url.strip() == '': return ''
    match = re.search(r'https{0,1}://(?:www\.)?([^/]+)', str(url))
    return match.group(1).lower() if match else ''

def get_video_id(url: str) -> str | None:
    parsed_url = urlparse(url)
    if "youtube.com" in parsed_url.hostname:
        video_id = parse_qs(parsed_url.query).get("v")
        if video_id: return video_id[0]
    elif "youtu.be" in parsed_url.hostname:
        return parsed_url.path[1:]
    return None

def get_youtube_transcript(video_id: str) -> str | None:
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        transcript_text = " ".join([d['text'] for d in transcript_list])
        return transcript_text[:7000]
    except Exception as e:
        print(f"     - ⚠️ Could not get transcript for video ID {video_id}: {e}")
        return None

def process_company(company: dict, research_strategies: list, services: dict, master_prompt: str) -> dict:
    company_name = company.get('Company Name')
    company_website = company.get('Website URL')

    print(f"\n▶️  Processing: {company_name}")
    print("=" * 40)

    research_summary = None
    source_url = None

    for i, strategy in enumerate(research_strategies):
        if research_summary: break

        print(f"\n  [Strategy {i+1}/{len(research_strategies)}]")

        strategy_query = strategy.get('Query')
        research_prompt = strategy.get('Research Prompt')
        if not strategy_query or not research_prompt: continue
        if '{domain}' in strategy_query and not company_website:
            print(f"    - 🟡 SKIPPING: Strategy requires a website, but none provided.")
            continue
        domain = extract_domain(company_website) if company_website else ""
        formatted_query = strategy_query.format(company=company_name, domain=domain)
        search_results = services['search'].search(formatted_query)
        if not search_results or not search_results[0].get('organicResults'):
            print(f"    - ⚪️ INFO: No search results returned for this query.")
            continue

        top_results = search_results[0]['organicResults'][:3]
        print(f"    - ✅ SEARCH: Found {len(top_results)} URLs. Trying top {min(len(top_results), 3)}.")

        for j, result in enumerate(top_results):
            if research_summary: break
            url = result.get('url')
            if not url: continue

            print(f"\n    [URL {j+1}/{len(top_results)}] -> {url}")

            content, video_id = None, get_video_id(url)
            if video_id:
                print("      - 🟡 INFO: YouTube link found. Fetching transcript...")
                content = get_youtube_transcript(video_id)
            else:
                print("      - 🟡 INFO: Standard URL. Scraping content...")
                content = scrape_website_text(url)

            if not content:
                print("      - 🔴 FAILED: Scraping returned no content (likely blocked or error).")
                continue
            if len(content) < 150:
                print("      - 🔴 FAILED: Scraped content was too short to be useful.")
                continue

            # --- PREVIEW OF SCRAPED CONTENT ---
            print("      - ✅ SCRAPED: Successfully retrieved content.")
            print("        " + "-"*20 + " Content Preview " + "-"*20)
            print(f"        {content[:400].replace(chr(10), ' ')}...")
            print("        " + "-"*57)

            print("      - 🟡 INFO: Submitting content to Summarization AI (GPT-3.5)...")
            potential_summary = services['ai'].get_completion(
                user_prompt=f"My request is: '{research_prompt}'\n\nContent to Analyze:\n---\n{content}\n---",
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                model=SUMMARY_MODEL, max_tokens=200
            )

            # --- PREVIEW OF AI RESPONSE & ERROR DIFFERENTIATION ---
            if potential_summary.startswith("AI_REFUSAL"):
                print(f"      - 🔴 FAILED: AI refused to summarize the content: {potential_summary}")
                continue
            elif "Error:" in potential_summary:
                print(f"      - 🔴 FAILED: An API error occurred during summarization: {potential_summary}")
                continue
            else:
                research_summary = potential_summary
                source_url = url
                print("      - ✅ SUCCESS: AI summary generated.")
                print("        " + "-"*20 + " AI Summary " + "-"*20)
                print(f"        {research_summary}")
                print("        " + "-"*52)
                break

    personalized_message = ""
    status = "❌ No Source Summarized"

    if research_summary:
        print("\n  [Personalization Step]")
        print("    - 🟡 INFO: Submitting summary to Personalization AI (GPT-4)...")
        final_prompt = master_prompt.format(summary=research_summary, company=company_name, domain=extract_domain(company_website) if company_website else "")

        personalized_message = services['ai'].get_completion(
            user_prompt=final_prompt,
            system_prompt=PERSONALIZATION_SYSTEM_PROMPT,
            model=PERSONALIZATION_MODEL
        )

        if "Error:" in personalized_message or personalized_message == "AI_REFUSAL":
            status = "⚠️ Personalization Failed"
            print(f"    - 🔴 FAILED: An API error occurred during personalization.")
            personalized_message = ""
        else:
            status = "✓ Personalized"
            print("    - ✅ SUCCESS: Personalized message generated.")
            print("      " + "-"*20 + " Final Message " + "-"*20)
            print(f"      {personalized_message}")
            print("      " + "-"*55)
    else:
        print("\n  [Personalization Step]")
        print("    - ⚪️ INFO: No valid summary was generated, skipping personalization.")

    return {
        "research_summary": research_summary or "",
        "source_url": source_url or "",
        "personalized_message": personalized_message,
        "status": status
    }

def main():
    print("🚀 Starting AI-Powered Outreach Personalization Engine...")
    print("=" * 60)

    apify_key = os.getenv('APIFY_API_KEY')
    openai_key = os.getenv('OPENAI_API_KEY')
    if not apify_key or not openai_key:
        print("❌ FATAL: API keys not found.")
        return
    print("✅ API keys loaded successfully.")

    try:
        print("📊 Connecting to Google Sheets...")
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
        print(f"✅ Loaded {len(companies_data)} companies and {len(research_strategies)} strategies.")
        print("=" * 60)
    except Exception as e:
        print(f"❌ Fatal Error during setup: {e}")
        return

    services = {
        'search': SearchService(api_key=apify_key),
        'ai': AIAssistantService(api_key=openai_key)
    }

    print("🔥 Starting company processing loop...")
    for i, company in enumerate(companies_data):
        company_name = company.get('Company Name')
        has_website = company.get('Website URL')
        has_linkedin = company.get('Company LinkedIn URL')
        if not company_name or (not has_website and not has_linkedin):
            print(f"\nSkipping row {i+2} due to missing data.")
            continue

        result = process_company(
            company=company,
            research_strategies=research_strategies,
            services=services,
            master_prompt=personalization_master_prompt
        )

        output_row_data = [
            company.get('Company LinkedIn URL', ''),
            company.get('Website URL', ''),
            company.get('Company Name', ''),
            result['research_summary'],
            result['source_url'],
            message_template,
            result['personalized_message'],
            result['status']
        ]
        output_sheet.update(range_name=f'A{i+2}:H{i+2}', values=[output_row_data])
        print(f"  ✅ Wrote to output sheet with status: {result['status']}")
        time.sleep(5)

    print("\n" + "=" * 60)
    print("✅ PERSONALIZATION COMPLETE!")
    print(f"📊 Check the 'Output' tab in your Google Sheet.")
    print("=" * 60)

if __name__ == "__main__":
    main()
# main.py

import os
import time
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import re
import pandas as pd
from newspaper import Article, Config

from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi

from services.search_service import SearchService
from services.ai_assistant_service import AIAssistantService

# --- Configuration and Setup ---
load_dotenv()
GPT35_MODEL = "gpt-3.5-turbo"
GPT4_MODEL = "gpt-4-turbo-preview"

# --- Helper Functions ---
def extract_domain(url):
    if pd.isna(url) or url.strip() == '': return ''
    match = re.search(r'https?://(?:www\.)?([^/]+)', str(url))
    return match.group(1).lower() if match else ''

def scrape_page_content(url: str) -> str | None:
    try:
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'

        article = Article(url, config=config)
        article.download()
        article.parse()
        return article.text[:5000]
    except Exception as e:
        print(f"     - ⚠️ Scraping failed for {url}: {e}")
        return None

def get_video_id(url: str) -> str | None:
    parsed_url = urlparse(url)
    if "youtube.com" in parsed_url.hostname:
        # For URLs like: https://www.youtube.com/watch?v=VIDEO_ID
        video_id = parse_qs(parsed_url.query).get("v")
        if video_id:
            return video_id[0]
    elif "youtu.be" in parsed_url.hostname:
        # For URLs like: https://youtu.be/VIDEO_ID
        return parsed_url.path[1:]
    return None

def get_youtube_transcript(video_id: str) -> str | None:
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        # Join all the text parts of the transcript into a single string
        transcript_text = " ".join([d['text'] for d in transcript_list])
        return transcript_text[:7000] # Limit length for the AI
    except Exception as e:
        print(f"     - ⚠️ Could not get transcript for video ID {video_id}: {e}")
        return None

# --- Main Orchestration ---
def main():
    print("🚀 Starting AI-Powered Outreach Personalization Engine...")
    print("=" * 60)

    apify_key = os.getenv('APIFY_API_KEY')
    openai_key = os.getenv('OPENAI_API_KEY')
    if not apify_key or not openai_key:
        print("❌ FATAL: APIFY_API_KEY or OPENAI_API_KEY not found.")
        return
    print("✅ API keys loaded successfully.")

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
        print("✅ Connected to Google Sheets successfully.")

        companies_data = companies_sheet.get_all_records()
        print(f"✅ Loaded {len(companies_data)} companies from 'Companies' sheet.")
        research_strategies = research_sheet.get_all_records()
        print(f"✅ Loaded {len(companies_data)} companies and {len(research_strategies)} research strategies.")
        message_template = messaging_sheet.get('A2')[0][0]
        personalization_master_prompt = messaging_sheet.get('B2')[0][0]
        print(f"✅ Found {len(companies_data)} companies.")
        print("=" * 60)
    except Exception as e:
        print(f"❌ Fatal Error during setup: {e}")
        return

    search_service = SearchService(api_key=apify_key)
    ai_service = AIAssistantService(api_key=openai_key)

    print("🔥 Starting company processing loop...")
    for i, company in enumerate(companies_data):
        company_name = company.get('Company Name')
        company_website = company.get('Website URL')
        if not company_name or not company_website: continue

        print(f"\n[{i+1}/{len(companies_data)}] Processing: {company_name}")
        print("-" * 40)

        research_summary = None
        source_url = None

        print("  1. Executing research strategies...")
        for strategy in research_strategies:
            if research_summary: break # Exit if we've already found a fact

            strategy_query = strategy.get('Query')
            research_prompt = strategy.get('Research Prompt')
            if not strategy_query or not research_prompt: continue

            domain = extract_domain(company_website)
            if not domain: continue

            formatted_query = strategy_query.format(company=company_name, domain=domain)
            search_results = search_service.search(formatted_query)

            if not search_results or not search_results[0].get('organicResults'):
                print(f"     - No results for query: '{formatted_query}'")
                continue

            # NEW: Try the top 3 organic results
            for result in search_results[0]['organicResults'][:3]:
                if research_summary: break
                url = result.get('url')
                if not url: continue

                content = None
                video_id = get_video_id(url)
                if video_id:
                    print("     -> YouTube link found. Fetching transcript...")
                    content = get_youtube_transcript(video_id)
                else:
                    print("     -> Standard URL. Scraping content...")
                    content = scrape_page_content(url)

                if not content or len(content) < 150:
                    print("     - Scraping failed or content too short.")
                    continue

                print("     -> Content scraped. Submitting for summary... ")
                summary = ai_service.get_completion(
                    user_prompt=f"{research_prompt}\n\nContent:\n---\n{content}\n---",
                    system_prompt="You are a research assistant. Extract information precisely according to instructions.",
                    model=GPT35_MODEL, max_tokens=200
                )

                if "Error:" not in summary and summary != "AI_REFUSAL":
                    research_summary = summary
                    source_url = url
                    print(f"     -> SUCCESS! AI Summary: '{research_summary[:100]}...'")
                    break
                else:
                    print(f"     -> AI failed or refused summary.")

        if research_summary:
            print("\n  2. Generating personalized message...")
            final_prompt = (
                f"{personalization_master_prompt}\n\n"
                f"Here is the base message template to start with:\n"
                f"'{message_template}'\n\n"
                f"Here is the research summary you must incorporate:\n"
                f"'{research_summary}'"
            )

            personalized_message = ai_service.get_completion(
                user_prompt=final_prompt,
                system_prompt="You are an expert at writing natural, personalized outreach messages.",
                model=GPT4_MODEL
            )

            status = "✓ Personalized" if "Error:" not in personalized_message and personalized_message != "AI_REFUSAL" else "⚠️ Personalization Failed"
            print(f"     -> AI Message: '{personalized_message}'")
        else:
            print("\n  2. No strategies produced a valid summary.")
            personalized_message = ""
            status = "❌ No source summarized"

        output_row_data = [
            company.get('Company LinkedIn URL', ''), company_website, company_name,
            research_summary or "", source_url or "", message_template,
            personalized_message if status == "✓ Personalized" else "",
            status
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
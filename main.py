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

load_dotenv()

# --- Model Configuration ---
SUMMARY_MODEL = "gpt-3.5-turbo"
PERSONALIZATION_MODEL = "gpt-4-turbo-preview"

# --- System Prompts ---
SUMMARY_SYSTEM_PROMPT = "You are a research assistant. Analyze the provided text (which could be an article or a video transcript) and extract information precisely according to the user's instructions."
PERSONALIZATION_SYSTEM_PROMPT = "You are an expert at writing natural, personalized outreach messages."

# --- Helper Functions ---
def extract_domain(url):
    if pd.isna(url) or url.strip() == '': return ''
    match = re.search(r'https{0,1}://(?:www\.)?([^/]+)', str(url))
    return match.group(1).lower() if match else ''

def scrape_page_content(url: str) -> str | None:
    try:
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
        article = Article(url, config=config)
        article.download()
        article.parse()
        return article.text[:7000]
    except Exception as e:
        print(f"     - ⚠️ Scraping failed for {url}: {e}")
        return None

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

def process_company(company: dict, research_strategies: list, services: dict) -> dict:
    """
    Processes a single company, from research to personalization.
    Returns a dictionary with the results.
    """
    company_name = company.get('Company Name')
    company_website = company.get('Website URL')

    print(f"\nProcessing: {company_name}")
    print("-" * 40)

    research_summary = None
    source_url = None

    print("  1. Executing research strategies...")
    for strategy in research_strategies:
        if research_summary: break

        strategy_query = strategy.get('Query')
        research_prompt = strategy.get('Research Prompt')
        if not strategy_query or not research_prompt: continue

        domain = extract_domain(company_website)
        if not domain: continue

        formatted_query = strategy_query.format(company=company_name, domain=domain)
        search_results = services['search'].search(formatted_query)

        if not search_results or not search_results[0].get('organicResults'):
            print(f"     - No results for query: '{formatted_query}'")
            continue

        for result in search_results[0]['organicResults'][:3]:
            if research_summary: break
            url = result.get('url')
            if not url: continue

            print(f"     -> Found URL: {url}.")
            content = None
            video_id = get_video_id(url)

            if video_id:
                print("     -> YouTube link. Fetching transcript...")
                content = get_youtube_transcript(video_id)
            else:
                print("     -> Standard URL. Scraping content...")
                content = scrape_page_content(url)

            if not content or len(content) < 150:
                print("     - Failed to get valid content.")
                continue

            print("     -> Content retrieved. Submitting for summary...")
            summary = services['ai'].get_completion(
                user_prompt=f"{research_prompt}\n\nContent:\n---\n{content}\n---",
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                model=SUMMARY_MODEL, max_tokens=200
            )

            if "Error:" not in summary and summary != "AI_REFUSAL":
                research_summary = summary
                source_url = url
                print(f"     -> SUCCESS! AI Summary: '{research_summary[:100]}...'")
                break
            else:
                print(f"     -> AI failed or refused summary.")

    # --- Personalization Step ---
    personalized_message = ""
    status = "❌ No source summarized"

    if research_summary:
        print("\n  2. Generating personalized message...")
        final_prompt = (
            f"{services['master_prompt']}\n\n"
            f"Here is the base message template to start with:\n"
            f"'{services['template']}'\n\n"
            f"Here is the research summary you must incorporate:\n"
            f"'{research_summary}'"
        )

        personalized_message = services['ai'].get_completion(
            user_prompt=final_prompt,
            system_prompt=PERSONALIZATION_SYSTEM_PROMPT,
            model=PERSONALIZATION_MODEL
        )

        if "Error:" not in personalized_message and personalized_message != "AI_REFUSAL":
            status = "✓ Personalized"
            # Check if the AI's response already includes the greeting.
            # If not, prepend it.
            if not personalized_message.strip().lower().startswith('{name}'):
                # We take the part of the message AFTER the greeting and append it
                greeting = "{Name}, good to connect. "
                # This logic is tricky. Let's simplify and just prepend for now.
                # Let's assume the AI prompt is good enough to handle this.
                # A simpler fix is to adjust the prompt to be more explicit.
                pass # The prompt is now responsible for the full structure
            print(f"     -> AI Message: '{personalized_message}'")
        else:
            status = "⚠️ Personalization Failed"
            personalized_message = ""
    else:
        print("\n  2. No strategies produced a valid summary.")

    return {
        "research_summary": research_summary or "",
        "source_url": source_url or "",
        "personalized_message": personalized_message,
        "status": status
    }

# --- Main Orchestration ---
def main():
    print("🚀 Starting AI-Powered Outreach Personalization Engine...")
    print("=" * 60)

    # --- Setup ---
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

    # --- Initialize Services ---
    services = {
        'search': SearchService(api_key=apify_key),
        'ai': AIAssistantService(api_key=openai_key),
        'template': message_template,
        'master_prompt': personalization_master_prompt.replace('{Name}', 'the recipient') # Make prompt generic
    }

    # --- Main Loop ---
    print("🔥 Starting company processing loop...")
    for i, company in enumerate(companies_data):
        if not company.get('Company Name') or not company.get('Website URL'):
            print(f"\nSkipping row {i+2} due  to missing data.")
            continue

        result = process_company(company, research_strategies, services)

        final_message_output = result['personalized_message']
        if result['status'] == "✓ Personalized" and not final_message_output.startswith('{Name}'):
            # The AI can sometimes forget the placeholder. We'll add it back.
            # A more robust solution is to split the template and insert the AI sentence.
            greeting = "{Name}, good to connect. "
            if "good to connect." in final_message_output:
                # AI likely rewrote the whole thing, let's try to find the new part
                parts = final_message_output.split("good to connect.")
                final_message_output = greeting + parts[1].strip()
            else: # If AI just gave the sentence, prepend it
                base_question = "What’s the process typically look like to become an approved vendor for retail fixtures or millwork?"
                final_message_output = f"{greeting}{result['personalized_message']} {base_question}"


        output_row_data = [
            company.get('Company LinkedIn URL', ''),
            company.get('Website URL', ''),
            company.get('Company Name', ''),
            result['research_summary'],
            result['source_url'],
            services['template'],
            final_message_output if result['status'] == "✓ Personalized" else "",
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
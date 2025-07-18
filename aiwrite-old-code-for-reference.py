"""
AI-Powered Outreach Personalization
Reads companies from Google Sheets, researches each one, and generates personalized messages.
"""

# ===== IMPORTS =====
import os
import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
import openai
from newspaper import Article
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from tenacity import retry, stop_after_attempt, wait_exponential
import re
from urllib.parse import urlparse, quote
import tldextract

# ===== CONFIGURATION =====
load_dotenv()

# API Keys
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_SHEETS_CREDS_PATH = os.getenv('GOOGLE_SHEETS_CREDS_PATH', 'credentials.json')
SPREADSHEET_NAME = os.getenv('SPREADSHEET_NAME', 'Sample PQ')
APIFY_API_KEY = os.getenv('APIFY_API_KEY')

# Model Configuration
GPT35_MODEL = "gpt-3.5-turbo"
GPT4_MODEL = "gpt-4-turbo-preview"

# Rate Limits
SEARCHES_PER_MINUTE = 10
OPENAI_REQUESTS_PER_MINUTE = 50

# Cache Settings
CACHE_DIR = "cache"
CACHE_EXPIRY_DAYS = 30

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY

# ===== DATA CLASSES =====
@dataclass
class Company:
    linkedin_url: str
    website_url: str
    name: str

@dataclass
class ResearchResult:
    fact: str
    source_url: str
    confidence: bool

# ===== GOOGLE SHEETS FUNCTIONS =====
def init_sheets_client():
    """Initialize Google Sheets connection with Drive API access"""
    print("📊 Connecting to Google Sheets...")

    # Define the scope - NOW INCLUDING DRIVE API
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/spreadsheets'
    ]

    # Authenticate
    creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDS_PATH, scopes=scope)

    # Initialize both clients
    sheets_client = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)

    # Open the spreadsheet
    try:
        spreadsheet = sheets_client.open(SPREADSHEET_NAME)
        print(f"✅ Connected to '{SPREADSHEET_NAME}'")
        return spreadsheet, drive_service
    except Exception as e:
        print(f"❌ Error opening spreadsheet: {e}")
        raise

def get_cell_comment(drive_service, spreadsheet_id: str, cell_range: str) -> Optional[str]:
    """Get comment from a specific cell using Drive API"""
    try:
        # Get the comments for the spreadsheet
        comments = drive_service.comments().list(
            fileId=spreadsheet_id,
            fields='comments(content,anchor)',
            includeDeleted=False
        ).execute()

        # Find comment for our specific cell
        for comment in comments.get('comments', []):
            anchor = comment.get('anchor', {})
            # Check if this comment is for our cell (A2)
            if anchor.get('type') == 'workbook-range' and 'A2' in anchor.get('range', ''):
                return comment.get('content', '')

        return None
    except Exception as e:
        print(f"⚠️  Error reading comment: {e}")
        return None

def read_companies(spreadsheet) -> List[Company]:
    """Read all companies from Companies tab"""
    print("📖 Reading companies...")

    try:
        sheet = spreadsheet.worksheet('Companies')
        records = sheet.get_all_records()

        companies = []
        for record in records:
            # Handle different possible column names
            linkedin = record.get('Company Linkedin Url') or record.get('Company LinkedIn URL')
            website = record.get('Website URL')
            name = record.get('Company Name')

            if linkedin and website and name:
                companies.append(Company(
                    linkedin_url=linkedin.strip(),
                    website_url=website.strip(),
                    name=name.strip()
                ))

        print(f"✅ Found {len(companies)} companies")
        return companies
    except Exception as e:
        print(f"❌ Error reading companies: {e}")
        raise

def read_research_strategies(spreadsheet) -> List[Dict[str,str]]:
    """
    Read query templates and prompts from Research tab.
    Returns a list of dicts: [{"Query": str, "Prompt": str}, ...]
    """
    sheet = spreadsheet.worksheet('Research')
    records = sheet.get_all_records()
    strategies = []
    for record in records:
        q = record.get('Query', '').strip()
        p = record.get('Prompt', '').strip()
        if q and p:
            strategies.append({"Query": q, "Prompt": p})
    print(f"✅ Found {len(strategies)} research strategies")
    return strategies

def read_message_template(spreadsheet, drive_service) -> Tuple[str, str]:
    """Read template and instructions from Messaging tab"""
    print("💬 Reading message template...")

    try:
        sheet = spreadsheet.worksheet('Messaging')

        # Get the template from A2
        template = sheet.get('A2')[0][0]

        # Get the comment (instructions) from A2 using Drive API
        spreadsheet_id = spreadsheet.id
        instructions = get_cell_comment(drive_service, spreadsheet_id, 'Messaging!A2')

        if not instructions:
            # Fallback to default instructions
            instructions = """Original template: {template}
Fact to mention: {fact}

Task: Add exactly ONE sentence after the greeting that naturally mentions the fact.
The sentence should flow naturally and be under 15 words.
Keep everything else EXACTLY the same.

Return ONLY the complete personalized message."""
            print("  ⚠️  No comment found, using default instructions")
        else:
            print("  ✅ Found custom instructions in cell comment")

        print(f"✅ Found message template")
        return template, instructions
    except Exception as e:
        print(f"❌ Error reading message template: {e}")
        raise

def init_output_sheet(spreadsheet):
    """Initialize the Output tab with headers"""
    print("📝 Initializing Output tab...")

    try:
        # Try to get existing Output sheet or create new one
        try:
            sheet = spreadsheet.worksheet('Output')
            sheet.clear()
        except:
            sheet = spreadsheet.add_worksheet(title='Output', rows=1000, cols=10)

        # Write headers
        headers = [
            'Company LinkedIn URL',
            'Website URL',
            'Company Name',
            'Research Found',
            'Research Source',
            'Message',
            'Personalized Message',
            'Status'
        ]

        sheet.update('A1:H1', [headers])

        # Format headers (bold)
        sheet.format('A1:H1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
        })

        print("✅ Output tab ready")
        return sheet
    except Exception as e:
        print(f"❌ Error initializing output sheet: {e}")
        raise

def write_output_row(sheet, row_num: int, row_data: List[str]):
    """Write one result row to Output tab"""
    try:
        # Row num + 2 because of header and 0-indexing
        range_name = f'A{row_num + 2}:H{row_num + 2}'
        sheet.update(range_name, [row_data])

        # Color code based on status
        status = row_data[7]
        if status == "✓ Good":
            color = {'red': 0.85, 'green': 0.92, 'blue': 0.83}
        elif status == "⚠️ Review":
            color = {'red': 1, 'green': 0.95, 'blue': 0.8}
        else:
            color = {'red': 1, 'green': 0.9, 'blue': 0.9}

        sheet.format(f'H{row_num + 2}', {'backgroundColor': color})
    except Exception as e:
        print(f"❌ Error writing row {row_num}: {e}")

# ===== RESEARCH FUNCTIONS =====
def clean_url(url: str) -> str:
    """Clean and standardize URL"""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def search_web_apify(query: str) -> List[Dict]:
    endpoint = (
        f"https://api.apify.com/v2/acts/apify~google-search-scraper"
        "/run-sync-get-dataset-items"
        f"?token={APIFY_API_KEY}"
    )
    payload = {
        "queries": query,            # string, not list
        "resultsPerPage": 10,
        "maxPagesPerQuery": 1,
        "mobileResults": False
    }

    resp = requests.post(endpoint, json=payload, timeout=60)
    print("APIFY REQUEST →", endpoint, payload)
    print("APIFY RESPONSE STATUS →", resp.status_code)
    print("APIFY RESPONSE TEXT →", repr(resp.text))
    if not resp.ok:
        print(f"⚠️ Apify HTTP {resp.status_code}: {resp.text[:200]}")
        return []
    return resp.json()  # list of {url, title, snippet, ...}

def scrape_page(url: str) -> Optional[str]:
    """Scrape webpage content using newspaper3k"""
    try:
        url = clean_url(url)
        article = Article(url)
        article.download()
        article.parse()

        # Get text content
        text = article.text

        # If text is too short, try to get meta description
        if len(text) < 100:
            text = article.meta_description or text

        return text[:5000]  # Limit length
    except Exception as e:
        print(f"⚠️  Error scraping {url}: {e}")
        return None

def search_youtube(query: str) -> List[str]:
    """Search YouTube and return video IDs"""
    # Simple YouTube search - returns mock data for now
    # In production, use YouTube Data API
    return []

def get_youtube_transcript(video_id: str) -> Optional[str]:
    """Get transcript for a YouTube video"""
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        text = ' '.join([entry['text'] for entry in transcript])
        return text[:5000]  # Limit length
    except Exception as e:
        print(f"⚠️  Error getting transcript: {e}")
        return None

def research_company(company: Company, strategies: List[Dict[str,str]]) -> Optional[ResearchResult]:
    """Execute each Research tab strategy in order, returning the first good fact."""
    for idx, step in enumerate(strategies, start=1):
        raw_q   = step["Query"]
        prompt  = step["Prompt"]
        # Extract just the apex domain (e.g. "acme.com")
        ext     = tldextract.extract(company.website_url)
        domain  = f"{ext.domain}.{ext.suffix}"
        # Format your search string
        query   = raw_q.format(company=company.name, domain=domain)
        print(f"  Strategy {idx}/{len(strategies)}: {query}")

        content = None
        source  = None

        # 1) If it's an 'about' query, just let Google pick the right URL
        if query.startswith("site:") and "about" in query.lower():
            results = search_web_apify(query)
            for r in results[:3]:
                url = r.get("url")
                if not url: continue
                txt = scrape_page(url)
                if txt and len(txt) > 50:
                    content, source = txt, url
                    break

        # 2) Otherwise treat as a generic web search
        else:
            results = search_web_apify(query)
            for r in results[:3]:
                url = r.get("url")
                if not url: continue
                txt = scrape_page(url)
                if txt and len(txt) > 50:
                    content, source = txt, url
                    break

        # 3) Summarize & quality-check
        if content:
            fact = summarize_with_gpt35(content, prompt)
            if fact and len(fact) > 20:
                print(f"    ✓ Found fact: {fact[:60]}…")
                return ResearchResult(fact=fact,
                                      source_url=source or company.website_url,
                                      confidence=True)
        time.sleep(1)  # rate-limit between strategies

    print("    ❌ No good facts found")
    return None

# ===== AI FUNCTIONS =====
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def summarize_with_gpt35(content: str, prompt: str) -> Optional[str]:
    """Use GPT-3.5 to extract facts"""
    try:
        # Limit content length to save tokens
        content = content[:3000]

        full_prompt = f"{prompt}\n\nContent:\n{content}\n\nExtracted fact (1-2 sentences):"

        response = openai.chat.completions.create(
            model=GPT35_MODEL,
            messages=[
                {"role": "system", "content": "You are a research assistant extracting specific facts from content."},
                {"role": "user", "content": full_prompt}
            ],
            temperature=0,
            max_tokens=100
        )

        fact = response.choices[0].message.content.strip()

        # Clean up common GPT responses
        fact = fact.replace('"', '').replace("'", '')
        if fact.lower().startswith(('the company', 'they', 'it')):
            return None

        return fact
    except Exception as e:
        print(f"    ⚠️ GPT-3.5 error: {e}")
        return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def generate_message_with_gpt4(template: str, fact: str, instructions: str) -> str:
    """Use GPT-4 to create personalized message"""
    try:
        # Replace placeholders in the instructions
        prompt = instructions.replace('{template}', template).replace('{fact}', fact)

        response = openai.chat.completions.create(
            model=GPT4_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert at writing natural, personalized outreach messages."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"    ⚠️ GPT-4 error: {e}")
        return template  # Return original on error

# ===== UTILITY FUNCTIONS =====
def get_cache_key(company_name: str) -> str:
    """Generate cache key for company"""
    return hashlib.md5(company_name.encode()).hexdigest()

def cache_result(company_name: str, result: ResearchResult):
    """Cache research results to avoid duplicate API calls"""
    cache_key = get_cache_key(company_name)
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    try:
        with open(cache_file, 'w') as f:
            json.dump({
                'fact': result.fact,
                'source_url': result.source_url,
                'confidence': result.confidence,
                'timestamp': datetime.now().isoformat()
            }, f)
    except Exception as e:
        print(f"⚠️  Cache write error: {e}")

def get_cached_result(company_name: str) -> Optional[ResearchResult]:
    """Retrieve cached result if exists and not expired"""
    cache_key = get_cache_key(company_name)
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                data = json.load(f)

            # Check if cache is expired
            timestamp = datetime.fromisoformat(data['timestamp'])
            if datetime.now() - timestamp < timedelta(days=CACHE_EXPIRY_DAYS):
                return ResearchResult(
                    fact=data['fact'],
                    source_url=data['source_url'],
                    confidence=data['confidence']
                )
    except Exception as e:
        print(f"⚠️  Cache read error: {e}")

    return None

# ===== MAIN ORCHESTRATION =====
def main():
    """Main execution flow"""
    print("\n🚀 Starting AI-Powered Outreach Personalization Engine")
    print("=" * 60)

    # Test mode - process only first 5 companies
    TEST_MODE = os.getenv('TEST_MODE', 'true').lower() == 'true'

    try:
        # 1. Connect to Google Sheets with Drive API
        spreadsheet, drive_service = init_sheets_client()

        # 2. Load all configurations
        companies = read_companies(spreadsheet)
        strategies = read_research_strategies(spreadsheet)
        template, instructions = read_message_template(spreadsheet, drive_service)

        # Limit companies in test mode
        if TEST_MODE and len(companies) > 5:
            print(f"\n⚠️  TEST MODE: Processing only first 5 companies")
            companies = companies[:5]

        print(f"\n📊 Processing {len(companies)} companies")
        print(f"🔍 Using {len(strategies)} research strategies")
        print(f"💬 Message template: {template[:50]}...")

        # 3. Initialize Output tab
        output_sheet = init_output_sheet(spreadsheet)

        # 4. Process each company
        print("\n" + "=" * 60)
        print("STARTING RESEARCH")
        print("=" * 60)

        for i, company in enumerate(companies):
            print(f"\n[{i+1}/{len(companies)}] {company.name}")
            print("-" * 40)

            # Check cache first
            cached = get_cached_result(company.name)

            if cached:
                result = cached
                print("  ✓ Using cached research")
            else:
                # Execute research strategies
                result = research_company(company, strategies)
                if result:
                    cache_result(company.name, result)

            # Generate personalized message
            if result and result.fact:
                print(f"  📝 Generating personalized message...")
                personalized = generate_message_with_gpt4(template, result.fact, instructions)
                status = "✓ Good" if result.confidence else "⚠️ Review"
            else:
                personalized = template  # No personalization
                status = "❌ No fact found"
                result = ResearchResult(fact="", source_url="", confidence=False)

            # Write to Output tab
            output_row = [
                company.linkedin_url,
                company.website_url,
                company.name,
                result.fact,
                result.source_url,
                template,
                personalized,
                status
            ]

            write_output_row(output_sheet, i, output_row)
            print(f"  ✅ Status: {status}")

            # Rate limiting
            if i < len(companies) - 1:  # Don't wait after last company
                time.sleep(2)

        print("\n" + "=" * 60)
        print("✅ PERSONALIZATION COMPLETE!")
        print(f"📊 Check the 'Output' tab in your Google Sheet")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    # Create required directories
    os.makedirs(CACHE_DIR, exist_ok=True)

    # Run the main function
    main()
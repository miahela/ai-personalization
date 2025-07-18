import logging
from openai import OpenAI, APIError, RateLimitError

logger = logging.getLogger(__name__)

class AIAssistantService:
    def __init__(self, api_key: str, model: str = 'gpt-4-turbo', max_tokens: int = 500):
        if not api_key:
            raise ValueError("OpenAI API key not configured.")

        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.client = OpenAI(api_key=self.api_key)
        print("✅ Standalone AI Assistant Service Initialized.")

    def get_completion(self, user_prompt: str, system_prompt: str = None, browse_url: str = None) -> str:
        if not self.client:
            logger.error("OpenAI client not initialized.")
            return "Error: AI client not initialized."

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": user_prompt})

        try:
            if browse_url:
                messages[-1]['content'] += f"\n\nReference URL to browse: {browse_url}"

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=0.2,
            )

            if response.choices and len(response.choices) > 0:
                generated_text = response.choices[0].message.content.strip()
                generated_text = generated_text.replace('"', '').strip()
                return generated_text
            else:
                logger.error("No response choices from OpenAI API.")
                return "Error: No response from AI."
        except RateLimitError as e:
            logger.warning("Rate limit exceeded with OpenAI API. Waiting and retrying might be needed.")
            return f"Error: Rate limit exceeded. {e}"
        except APIError as e:
            logger.error(f"OpenAI API error: {e}")
            return f"Error: OpenAI API error. {e}"
        except Exception as e:
            logger.error(f"An unexpected error occurred in get_completion: {e}", exc_info=True)
            return f"Error: An unexpected error occurred. {e}"
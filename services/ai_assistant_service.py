# services/ai_assistant_service.py
import logging
from openai import OpenAI, APIError, RateLimitError

logger = logging.getLogger(__name__)

class AIAssistantService:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("OpenAI API key not configured.")

        self.api_key = api_key
        self.client = OpenAI(api_key=self.api_key)
        print("✅ AI Assistant Service Initialized.")

    def get_completion(self, user_prompt: str, system_prompt: str, model: str, max_tokens: int = 500) -> str:
        if not self.client:
            logger.error("OpenAI client not initialized.")
            return "Error: AI client not initialized."

        # Add the refusal instruction to the system prompt
        system_prompt += "\nIf you cannot fulfill the request or find the required information, you MUST respond with only the word: NO"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
            )

            if response.choices:
                generated_text = response.choices[0].message.content.strip()
                if generated_text.upper().startswith("NO:"):
                    return f"AI_REFUSAL ({generated_text})"
                return generated_text.replace('"', '').strip()
            else:
                logger.error("No response choices from OpenAI API.")
                return "Error: No response from AI."
        except RateLimitError as e:
            logger.warning(f"Rate limit exceeded with OpenAI API. {e}")
            return f"Error: Rate limit exceeded."
        except APIError as e:
            logger.error(f"OpenAI API error: {e}")
            return f"Error: OpenAI API error."
        except Exception as e:
            logger.error(f"An unexpected error occurred in get_completion: {e}", exc_info=True)
            return f"Error: An unexpected error occurred."
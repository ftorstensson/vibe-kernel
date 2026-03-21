import re
import json
import logging

# Entry 029: Force logs to terminal immediately
logger = logging.getLogger("uvicorn.error")

def get_clean_text(response):
    """Entry 077/080: Physically joins parts to avoid 'Multiple content parts' error."""
    try:
        # Join all text parts from the first candidate
        return "".join([part.text for part in response.candidates[0].content.parts])
    except Exception:
        try:
            return response.text
        except:
            return "ERROR: Could not harvest text from response."

def hammer_json(raw_text):
    """Entry 031/050: Strips Markdown blocks and ensures a single JSON object."""
    try:
        clean_json = re.sub(r'^\`\`\`json\s*|\`\`\`$', '', raw_text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(clean_json)
        return parsed[0] if isinstance(parsed, list) else parsed
    except Exception as e:
        logger.error(f"JSON Hammer Failed: {e}")
        return {"error": "JSON_PARSE_FAILED", "raw": raw_text}

def wash_link(url):
    """Entry 080: Extract raw URI from any accidental Markdown wrappers."""
    if not url: return ""
    clean = re.sub(r'[\\(\\)\]\\[]', '', url)
    return clean.strip()

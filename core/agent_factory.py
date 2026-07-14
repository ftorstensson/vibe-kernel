import os
from dotenv import load_dotenv
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig, Tool

load_dotenv()

# Regional Physics (Advisor Mandate)
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = "us-central1" 

if PROJECT_ID:
    vertexai.init(project=PROJECT_ID, location=LOCATION)

class AgentFactory:
    @staticmethod
    def get_clerk():
        """IQ: 0.0 - Extraction (Gemini 2.5 Flash)"""
        return GenerativeModel("gemini-2.5-flash"), GenerationConfig(temperature=0.0)

    @staticmethod
    def get_partner_pm():
        """EQ: 0.4 - Social PM (Gemini 2.5 Pro)"""
        return GenerativeModel("gemini-2.5-pro"), GenerationConfig(temperature=0.4)

    @staticmethod
    def get_hound():
        """IQ: 0.1 - Grounded Specialist (Gemini 2.5 Flash)"""
        # Entry 050/063: Native Google Search Tool
        search_tool = Tool.from_dict({"google_search": {}})
        return GenerativeModel(
            "gemini-2.5-flash",
            tools=[search_tool]
        ), GenerationConfig(temperature=0.1)

    @staticmethod
    def get_clinical_auditor():
        """IQ: 0.0 - The Deadbolt (Gemini 2.5 Flash)"""
        return GenerativeModel("gemini-2.5-flash"), GenerationConfig(temperature=0.0)

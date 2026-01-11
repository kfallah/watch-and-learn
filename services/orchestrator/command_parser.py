"""Command Parser for Multi-Agent Browser Swarm.

Uses LangChain + Gemini 2.0 Flash for intelligent command parsing and result synthesis.
Parses natural language commands like "Look up 5 YC companies evaluation value"
into structured SwarmCommand objects for task distribution.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Literal, Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from models import SwarmCommand, CompanyInfo

logger = logging.getLogger(__name__)

# Default path to companies data
COMPANIES_JSON_PATH = Path("/app/data/companies.json")

# Gemini API Key (same as used by workers)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


class ParsedCommand(BaseModel):
    """Structured output from LLM command parsing."""
    action: Literal["lookup", "analyze", "compare", "track"] = Field(
        description="The type of action to perform"
    )
    query_type: Literal["valuation", "overview", "funding", "team", "product"] = Field(
        description="What type of information to retrieve"
    )
    target_count: int = Field(
        description="Number of companies to research (1-6)",
        ge=1,
        le=6
    )
    specific_companies: list[str] = Field(
        default_factory=list,
        description="Specific company names mentioned by user"
    )
    industry_filter: Optional[str] = Field(
        default=None,
        description="Filter companies by industry if mentioned"
    )
    reasoning: str = Field(
        description="Brief explanation of how the command was interpreted"
    )


class CommandParser:
    """LangChain-powered command parser with Gemini 2.0 Flash."""

    def __init__(self, companies_path: Optional[Path] = None):
        self.companies_path = companies_path or COMPANIES_JSON_PATH
        self.companies: list[CompanyInfo] = []
        self._load_companies()
        self._setup_llm()

    def _setup_llm(self):
        """Initialize LangChain with Gemini 2.0 Flash."""
        if not GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not found - falling back to regex parsing")
            self.llm = None
            return

        try:
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                temperature=0,
                google_api_key=GEMINI_API_KEY,
            )

            # Build company context for the prompt
            company_names = [c.name for c in self.companies[:50]]  # Limit context
            company_list = ", ".join(company_names) if company_names else "No companies loaded"

            self.parse_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are a command parser for a browser automation swarm that researches YC companies.

AVAILABLE COMPANIES (Winter 2025 batch):
{company_list}

TASK: Parse the user's natural language command into a structured research request.

RULES:
1. Determine the action type (lookup/analyze/compare/track)
2. Identify the query type (valuation/overview/funding/team/product)
3. Extract the number of companies to research (default: 5, max: 5)
4. Identify any specific company names mentioned
5. Note any industry filters (fintech, healthcare, AI, etc.)

OUTPUT: Return ONLY a valid JSON object with this structure:
{{
  "action": "lookup|analyze|compare|track",
  "query_type": "valuation|overview|funding|team|product",
  "target_count": 1-5,
  "specific_companies": [],
  "industry_filter": null,
  "reasoning": "brief explanation"
}}"""),
                ("human", "{user_command}")
            ])

            self.synthesis_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a financial analyst synthesizing research results about YC companies.

TASK: Create a professional markdown table summarizing the research findings.

RULES:
1. Format as a clean markdown table
2. Include relevant columns based on query type
3. Add a brief insight/summary at the end
4. Handle missing data gracefully with "N/A" or "Unknown"
5. Be concise but informative"""),
                ("human", """Query Type: {query_type}
Research Results:
{results}

Create a professional summary table and brief analysis.""")
            ])

            logger.info("LangChain Gemini 2.0 Flash initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize LangChain: {e}")
            self.llm = None

    def _load_companies(self):
        """Load companies from JSON file."""
        try:
            if self.companies_path.exists():
                with open(self.companies_path, "r") as f:
                    data = json.load(f)

                # Handle multiple formats:
                # 1. List format: [{company1}, {company2}]
                # 2. Dict with "companies" key: {"companies": [...]}
                # 3. Dict with company IDs as keys: {"company-id": {company_data}, ...}
                if isinstance(data, list):
                    companies_data = data
                elif isinstance(data, dict) and "companies" in data:
                    companies_data = data["companies"]
                elif isinstance(data, dict):
                    # Handle dict with company IDs as keys (hash table format)
                    companies_data = list(data.values())
                else:
                    companies_data = []

                self.companies = [
                    CompanyInfo(**c) if isinstance(c, dict) else CompanyInfo(name=str(c))
                    for c in companies_data
                ]
                logger.info(f"Loaded {len(self.companies)} companies from {self.companies_path}")
            else:
                logger.warning(f"Companies file not found: {self.companies_path}")
        except Exception as e:
            logger.error(f"Error loading companies: {e}")
            self.companies = []

    def parse(self, user_input: str) -> SwarmCommand:
        """Parse a natural language command into a SwarmCommand.

        Uses Gemini 2.0 Flash for intelligent parsing, with regex fallback.
        """
        # Try LLM parsing first
        if self.llm:
            try:
                parsed = self._parse_with_llm(user_input)
                if parsed:
                    logger.info(f"LLM parsed: {parsed.reasoning}")
                    return SwarmCommand(
                        action=parsed.action,
                        count=parsed.target_count,
                        companies=parsed.specific_companies,
                        query_type=parsed.query_type,
                        raw_input=user_input,
                    )
            except Exception as e:
                logger.warning(f"LLM parsing failed, falling back to regex: {e}")

        # Fallback to regex parsing
        return self._parse_with_regex(user_input)

    def _parse_with_llm(self, user_input: str) -> Optional[ParsedCommand]:
        """Parse command using Gemini 2.0 Flash."""
        chain = self.parse_prompt | self.llm

        response = chain.invoke({"user_command": user_input})
        content = response.content

        # Clean up response if it has markdown code blocks
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        # Parse JSON response
        data = json.loads(content)
        return ParsedCommand(**data)

    def _parse_with_regex(self, user_input: str) -> SwarmCommand:
        """Fallback regex-based parsing."""
        input_lower = user_input.lower()

        # Determine action type
        action = self._detect_action(input_lower)
        count = self._extract_count(input_lower)
        mentioned_companies = self._extract_company_names(user_input)
        query_type = self._detect_query_type(input_lower)

        return SwarmCommand(
            action=action,
            count=count,
            companies=mentioned_companies,
            query_type=query_type,
            raw_input=user_input,
        )

    def _detect_action(self, text: str) -> str:
        """Detect the action type from user input."""
        action_patterns = {
            "lookup": ["look up", "lookup", "find", "search", "get"],
            "analyze": ["analyze", "analyse", "research", "investigate", "study"],
            "compare": ["compare", "comparison", "versus", "vs"],
            "track": ["track", "monitor", "watch", "follow"],
        }

        for action, patterns in action_patterns.items():
            for pattern in patterns:
                if pattern in text:
                    return action

        return "lookup"

    def _extract_count(self, text: str) -> int:
        """Extract the number of companies to process."""
        patterns = [
            r'(\d+)\s*(?:yc\s*)?compan(?:y|ies)',
            r'top\s*(\d+)',
            r'first\s*(\d+)',
            r'(\d+)\s*startups?',
            r'look\s*up\s*(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return min(int(match.group(1)), 6)  # Cap at 6

        return 5

    def _extract_company_names(self, text: str) -> list[str]:
        """Extract specific company names mentioned in the input."""
        mentioned = []
        for company in self.companies:
            if company.name.lower() in text.lower():
                mentioned.append(company.name)
        return mentioned

    def _detect_query_type(self, text: str) -> str:
        """Detect what type of information to retrieve."""
        query_patterns = {
            "valuation": ["valuation", "value", "worth", "market cap", "funding"],
            "overview": ["overview", "summary", "about", "description"],
            "team": ["team", "founders", "employees", "staff"],
            "funding": ["funding", "investment", "raised", "series"],
            "product": ["product", "service", "offering", "technology"],
        }

        for query_type, patterns in query_patterns.items():
            for pattern in patterns:
                if pattern in text:
                    return query_type

        return "valuation"

    def get_companies_for_task(self, command: SwarmCommand) -> list[CompanyInfo]:
        """Get the list of companies to process based on the command."""
        if command.companies:
            return [
                c for c in self.companies
                if c.name in command.companies
            ][:command.count]
        else:
            return self.companies[:command.count]

    def generate_task_prompts(self, command: SwarmCommand) -> list[tuple[str, str]]:
        """Generate task prompts for each company."""
        companies = self.get_companies_for_task(command)
        prompts = []

        for company in companies:
            prompt = self._build_prompt(company, command.query_type)
            prompts.append((company.name, prompt))

        return prompts

    def _build_prompt(self, company: CompanyInfo, query_type: str) -> str:
        """Build a specific prompt for researching a company."""
        base_info = f"Company: {company.name}"
        if company.website:
            base_info += f"\nWebsite: {company.website}"
        if company.description:
            base_info += f"\nDescription: {company.description}"

        prompts = {
            "valuation": f"""Research the current valuation of {company.name}.

{base_info}

Please:
1. Navigate to search engines and financial news sites
2. Look for recent funding rounds, valuations, or market cap information
3. Find the most recent valuation estimate with its source
4. Report the valuation amount and the source of the information

Respond with the valuation amount (e.g., "$10B" or "$500M") and the source (e.g., "TechCrunch", "Forbes").""",

            "overview": f"""Provide an overview of {company.name}.

{base_info}

Please research and provide:
1. What the company does
2. Key products or services
3. Target market
4. Notable achievements or news""",

            "funding": f"""Research the funding history of {company.name}.

{base_info}

Please find:
1. Total funding raised
2. Most recent funding round (Series A, B, etc.)
3. Key investors
4. Funding round dates""",

            "team": f"""Research the team at {company.name}.

{base_info}

Please find:
1. Founders and their backgrounds
2. Key executives
3. Team size
4. Notable advisors""",

            "product": f"""Research the product/service of {company.name}.

{base_info}

Please find:
1. Main product or service
2. Key features
3. Competitive advantages
4. Target customers""",
        }

        return prompts.get(query_type, prompts["valuation"])

    def format_results_as_markdown_table(
        self,
        results: list[dict],
        query_type: str = "valuation",
    ) -> str:
        """Format task results as a markdown table.

        Uses Gemini 2.0 Flash for intelligent synthesis if available.
        """
        # Try LLM synthesis first
        if self.llm and results:
            try:
                return self._synthesize_with_llm(results, query_type)
            except Exception as e:
                logger.warning(f"LLM synthesis failed, using basic formatter: {e}")

        # Fallback to basic formatting
        return self._format_basic_table(results, query_type)

    def _synthesize_with_llm(self, results: list[dict], query_type: str) -> str:
        """Synthesize results using Gemini 2.0 Flash for intelligent analysis."""
        chain = self.synthesis_prompt | self.llm

        # Format results for the prompt
        results_text = json.dumps(results, indent=2, default=str)

        response = chain.invoke({
            "query_type": query_type,
            "results": results_text
        })

        return response.content

    def _format_basic_table(self, results: list[dict], query_type: str) -> str:
        """Basic markdown table formatting (fallback)."""
        if query_type == "valuation":
            header = "| Company | Valuation | Source | Confidence | Status |"
            separator = "|---------|-----------|--------|------------|--------|"
            rows = []

            for r in results:
                status_icon = "✓" if r.get("status") == "completed" else "✗"
                rows.append(
                    f"| {r.get('company_name', 'Unknown')} | "
                    f"{r.get('valuation', 'Unknown')} | "
                    f"{r.get('source', 'Unknown')} | "
                    f"{r.get('confidence', 'Low')} | "
                    f"{status_icon} |"
                )

            return f"## YC Company Valuations\n\n{header}\n{separator}\n" + "\n".join(rows)

        else:
            header = "| Company | Result | Status |"
            separator = "|---------|--------|--------|"
            rows = []

            for r in results:
                status_icon = "✓" if r.get("status") == "completed" else "✗"
                result_summary = r.get("raw_response", "")[:100] + "..."
                rows.append(
                    f"| {r.get('company_name', 'Unknown')} | "
                    f"{result_summary} | "
                    f"{status_icon} |"
                )

            return f"## Research Results\n\n{header}\n{separator}\n" + "\n".join(rows)

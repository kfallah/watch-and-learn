"""Command Parser for Multi-Agent Browser Swarm.

Parses natural language commands like "Look up 5 YC companies evaluation value"
into structured SwarmCommand objects for task distribution.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from models import SwarmCommand, CompanyInfo

logger = logging.getLogger(__name__)

# Default path to companies data
COMPANIES_JSON_PATH = Path("/app/data/companies.json")


class CommandParser:
    """Parses natural language commands into structured task requests."""

    def __init__(self, companies_path: Optional[Path] = None):
        self.companies_path = companies_path or COMPANIES_JSON_PATH
        self.companies: list[CompanyInfo] = []
        self._load_companies()

    def _load_companies(self):
        """Load companies from JSON file."""
        try:
            if self.companies_path.exists():
                with open(self.companies_path, "r") as f:
                    data = json.load(f)

                # Handle both list format and dict with "companies" key
                if isinstance(data, list):
                    companies_data = data
                elif isinstance(data, dict) and "companies" in data:
                    companies_data = data["companies"]
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

        Examples:
            - "Look up 5 YC companies evaluation value"
            - "Research valuation for Airbnb, Stripe, Notion"
            - "Find company valuations"
            - "Analyze 10 companies from YC W25"
        """
        input_lower = user_input.lower()

        # Determine action type
        action = self._detect_action(input_lower)

        # Extract count
        count = self._extract_count(input_lower)

        # Extract specific companies if mentioned
        mentioned_companies = self._extract_company_names(user_input)

        # Determine query type
        query_type = self._detect_query_type(input_lower)

        command = SwarmCommand(
            action=action,
            count=count,
            companies=mentioned_companies,
            query_type=query_type,
            raw_input=user_input,
        )

        logger.info(f"Parsed command: action={action}, count={count}, query_type={query_type}")
        return command

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

        return "lookup"  # Default action

    def _extract_count(self, text: str) -> int:
        """Extract the number of companies to process."""
        # Look for patterns like "5 companies", "top 10", "first 3"
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
                return int(match.group(1))

        # Default count
        return 5

    def _extract_company_names(self, text: str) -> list[str]:
        """Extract specific company names mentioned in the input."""
        mentioned = []

        # Check if any known company names are mentioned
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

        return "valuation"  # Default query type

    def get_companies_for_task(self, command: SwarmCommand) -> list[CompanyInfo]:
        """Get the list of companies to process based on the command."""
        if command.companies:
            # User specified specific companies
            return [
                c for c in self.companies
                if c.name in command.companies
            ][:command.count]
        else:
            # Return first N companies from loaded data
            return self.companies[:command.count]

    def generate_task_prompts(self, command: SwarmCommand) -> list[tuple[str, str]]:
        """Generate task prompts for each company.

        Returns:
            List of (company_name, prompt) tuples
        """
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
        """Format task results as a markdown table for chat display."""
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
            # Generic table format
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

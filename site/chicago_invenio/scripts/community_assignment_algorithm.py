#!/usr/bin/env python3
"""
Community Assignment Algorithm based on com_col_data.csv
"""

import csv
import re
import unicodedata
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict


def slugify(text):
    """Convert text to slug format (same as load_as_coms_colls.py)."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # remove punctuation (keep letters, numbers, whitespace and hyphens)
    text = re.sub(r"[^\w\s-]", "", text)
    # replace whitespace/underscores with hyphens and collapse consecutive hyphens
    text = re.sub(r"[\s_]+", "-", text.strip().lower())
    return text.strip("-")


class CommunityAssignmentAlgorithm:
    def __init__(self, csv_file_path: str):
        """Initialize the algorithm with the community/collection mapping CSV."""
        self.csv_file_path = csv_file_path
        self.community_map = self._load_community_map()

    def _load_community_map(self) -> Dict:
        """Load and organize the community mapping data."""
        mapping = {
            "by_692": defaultdict(set),  # Center/Institute -> Communities
            "by_691": defaultdict(set),  # Department -> Communities
            "by_690": defaultdict(set),  # Division -> Communities
            "by_336": defaultdict(set),  # Resource Type -> Communities
            "dissertation_map": {},  # Department -> Dissertation Community
            "dissertation_div_map": {},  # Division -> Dissertation Community
            "exact_combinations": {},  # (690,691,692,336) -> Community
        }

        with open(self.csv_file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                field_690 = row["690__a"].strip()
                field_691 = row["691__a"].strip()
                field_692 = row["692__a"].strip()
                field_336 = row["336__a"].strip()
                community = row["Community"].strip()
                collection = row["Collection"].strip()

                if not community:
                    continue

                # Store exact combinations for precise matching
                combo_key = (field_690, field_691, field_692, field_336)
                mapping["exact_combinations"][combo_key] = {
                    "community": community,
                    "collection": collection,
                }

                # Map individual fields to communities (but skip dissertation-specific mappings)
                if field_692:
                    mapping["by_692"][field_692].add(community)
                if field_691:
                    # Don't add dissertation communities to general department mapping
                    if not (
                        field_336.strip().lower() == "dissertation"
                        and community == "UChicago Dissertations"
                    ):
                        mapping["by_691"][field_691].add(community)
                if field_690:
                    # Don't add dissertation communities to general division mapping
                    if not (
                        field_336.strip().lower() == "dissertation"
                        and community == "UChicago Dissertations"
                    ):
                        mapping["by_690"][field_690].add(community)
                if field_336:
                    mapping["by_336"][field_336].add(community)

                # Special handling for dissertations
                if field_336.strip().lower() == "dissertation" and field_691:
                    mapping["dissertation_map"][field_691] = community
                if field_336.strip().lower() == "dissertation" and field_690:
                    mapping["dissertation_div_map"][field_690] = community

        return mapping

    def assign_communities(
        self,
        divisions: List[str] = None,
        departments: List[str] = None,
        centers: List[str] = None,
        resource_type: str = None,
    ) -> Dict:
        """
        Assign communities based on MARC field values.

        Args:
            divisions: List of 690$a values
            departments: List of 691$a values
            centers: List of 692$a values
            resource_type: 336$a value

        Returns:
            Dict with 'communities', 'collections', 'method', and 'confidence'
        """
        divisions = divisions or []
        departments = departments or []
        centers = centers or []

        # Find ALL possible community matches from all fields (comprehensive strategy)
        all_matches = self._find_all_possible_matches(
            divisions, departments, centers, resource_type
        )

        # Add exact combination match if found (but don't exclude other matches)
        exact_match = self._find_exact_combination_match(
            divisions, departments, centers, resource_type
        )
        if exact_match and exact_match["community"] not in all_matches["communities"]:
            all_matches["communities"].append(exact_match["community"])
            all_matches["details"]["matched_on"].append(
                f"exact:{exact_match['community']}"
            )

        if all_matches["communities"]:
            return all_matches

        # No match found
        return {
            "communities": [],
            "collections": [],
            "method": "no_match",
            "confidence": "none",
            "details": {
                "input": {
                    "divisions": divisions,
                    "departments": departments,
                    "centers": centers,
                    "resource_type": resource_type,
                }
            },
        }

    def _find_exact_combination_match(
        self,
        divisions: List[str],
        departments: List[str],
        centers: List[str],
        resource_type: str,
    ) -> Optional[Dict]:
        """Find exact combination matches in the CSV."""
        # Try all possible combinations of the input fields
        for div in [""] + divisions:
            for dept in [""] + departments:
                for center in [""] + centers:
                    for rtype in ["", resource_type or ""]:
                        combo_key = (div, dept, center, rtype)
                        if combo_key in self.community_map["exact_combinations"]:
                            return self.community_map["exact_combinations"][combo_key]
        return None

    def _find_all_possible_matches(
        self,
        divisions: List[str],
        departments: List[str],
        centers: List[str],
        resource_type: str,
    ) -> Dict:
        """Find ALL possible community matches from all sources."""
        communities = set()
        method_used = []

        # 1. Find ALL matching centers/institutes (692)
        for center in centers:
            if center in self.community_map["by_692"]:
                communities.update(self.community_map["by_692"][center])
                method_used.append(f"center:{center}")

        # 2. Find ALL matching departments (691)
        for dept in departments:
            if dept in self.community_map["by_691"]:
                communities.update(self.community_map["by_691"][dept])
                method_used.append(f"department:{dept}")

        # 3. Find ALL matching divisions (690)
        for div in divisions:
            if div in self.community_map["by_690"]:
                communities.update(self.community_map["by_690"][div])
                method_used.append(f"division:{div}")

        # 4. Add dissertation-specific communities ONLY for actual dissertations
        if resource_type and resource_type.lower() in [
            "dissertation",
            "publication-dissertation",
        ]:
            # Check department-based dissertation mappings
            for dept in departments:
                if dept in self.community_map["dissertation_map"]:
                    communities.add(self.community_map["dissertation_map"][dept])
                    method_used.append(f"dissertation:dept:{dept}")

            # Check division-based dissertation mappings
            for div in divisions:
                if div in self.community_map["dissertation_div_map"]:
                    communities.add(self.community_map["dissertation_div_map"][div])
                    method_used.append(f"dissertation:div:{div}")

            # Add general dissertation community only for actual dissertations with departments
            if departments:
                communities.add("UChicago Dissertations")
                method_used.append("dissertation:general")

        # Fuzzy matching has been removed to prevent false positive assignments

        confidence = "high" if len(communities) >= 1 else "none"

        return {
            "communities": list(communities),
            "collections": [],  # Would need additional logic to determine collections
            "method": "comprehensive_all_sources",
            "confidence": confidence,
            "details": {
                "matched_on": method_used,
                "total_communities": len(communities),
                "strategy": "include ALL possible matches (exact + dissertation)",
            },
        }

    def _find_dissertation_match(self, departments: List[str]) -> Dict:
        """Special handling for dissertations."""
        communities = set()

        for dept in departments:
            if dept in self.community_map["dissertation_map"]:
                communities.add(self.community_map["dissertation_map"][dept])

        # Default dissertation community if no specific match
        if not communities and departments:
            communities.add("UChicago Dissertations")

        return {
            "communities": list(communities),
            "collections": [],
            "method": "dissertation_specific",
            "confidence": "high" if len(communities) == 1 else "medium",
            "details": {"matched_departments": departments},
        }


def test_algorithm():
    """Test the algorithm with sample data."""
    csv_path = "/home/jabbi/PycharmProjects/chicago-invenio/site/chicago_invenio/scripts/com_col_data.csv"
    algorithm = CommunityAssignmentAlgorithm(csv_path)

    # Test cases
    test_cases = [
        # Case 1: Exact department match
        {
            "input": {
                "divisions": ["Arts & Humanities Division"],
                "departments": ["Philosophy"],
                "centers": [],
                "resource_type": None,
            },
            "expected": "Arts & Humanities Division",
        },
        # Case 2: Dissertation
        {
            "input": {
                "divisions": [],
                "departments": ["Philosophy"],
                "centers": [],
                "resource_type": "Dissertation",
            },
            "expected": "UChicago Dissertations",
        },
        # Case 3: Center-based assignment
        {
            "input": {
                "divisions": [],
                "departments": [],
                "centers": ["Enrico Fermi Institute"],
                "resource_type": None,
            },
            "expected": "Centers and Institutes",
        },
        # Case 4: Multiple departments (should find ALL)
        {
            "input": {
                "divisions": [],
                "departments": ["Gaming Islam", "Middle Eastern Studies"],
                "centers": [],
                "resource_type": None,
            },
            "expected": [
                "Gaming Islam",
                "Arts & Humanities Division",
            ],  # Should find both
        },
        # Case 5: Record with division, department AND center (should find ALL)
        {
            "input": {
                "divisions": ["Physical Sciences Division"],
                "departments": ["Physics"],
                "centers": ["Enrico Fermi Institute"],
                "resource_type": None,
            },
            "expected": [
                "Physical Sciences Division",
                "Centers and Institutes",
            ],  # Should find both
        },
    ]

    for i, test_case in enumerate(test_cases, 1):
        result = algorithm.assign_communities(**test_case["input"])
        print(f"\nTest Case {i}:")
        print(f"Input: {test_case['input']}")
        print(f"Result: {result}")
        print(f"Expected: {test_case['expected']}")


if __name__ == "__main__":
    test_algorithm()

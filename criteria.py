"""Configurable procurement evaluation criteria module.

This module defines the default evaluation criteria for BIDVEIL,
provides validation for criteria configurations, and handles
score normalization for manual evaluation.
"""

from __future__ import annotations

from typing import Any


DEFAULT_CRITERIA = [
    {
        "id": "technical_compliance",
        "name": "Technical Compliance",
        "weight": 0.30,
        "description": "Alignment with technical requirements and specifications",
        "scale": {"min": 0, "max": 100, "step": 1},
        "required": True,
        "auto_calculated": False,
    },
    {
        "id": "price_competitiveness",
        "name": "Price Competitiveness",
        "weight": 0.25,
        "description": "Competitive pricing relative to budget and market rates",
        "scale": {"min": 0, "max": 100, "step": 1},
        "required": False,
        "auto_calculated": True,
    },
    {
        "id": "relevant_experience",
        "name": "Relevant Experience",
        "weight": 0.20,
        "description": "Past experience with similar projects and domain expertise",
        "scale": {"min": 0, "max": 100, "step": 1},
        "required": True,
        "auto_calculated": False,
    },
    {
        "id": "delivery_timeline",
        "name": "Delivery Timeline",
        "weight": 0.15,
        "description": "Proposed delivery schedule and ability to meet deadlines",
        "scale": {"min": 0, "max": 100, "step": 1},
        "required": True,
        "auto_calculated": False,
    },
    {
        "id": "eligibility_and_documentation",
        "name": "Eligibility & Documentation",
        "weight": 0.10,
        "description": "Compliance with eligibility requirements and documentation completeness",
        "scale": {"min": 0, "max": 100, "step": 1},
        "required": True,
        "auto_calculated": False,
    },
]


def validate_criteria_config(criteria: list[dict[str, Any]]) -> tuple[bool, str]:
    """Validate a criteria configuration.

    Args:
        criteria: List of criterion dictionaries

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(criteria, list):
        return False, "Criteria must be a list"

    if not criteria:
        return False, "Criteria cannot be empty"

    # Check for unique IDs
    ids = [c.get("id") for c in criteria]
    if len(ids) != len(set(ids)):
        return False, "Criteria must have unique IDs"

    # Validate weights sum to 1.0 (with floating point tolerance)
    total_weight = sum(c.get("weight", 0) for c in criteria)
    if abs(total_weight - 1.0) > 0.001:
        return False, f"Criteria weights must sum to 1.0, got {total_weight:.3f}"

    # Validate each criterion
    for i, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            return False, f"Criterion at index {i} must be an object"

        # Required fields
        required_fields = ["id", "name", "weight", "scale"]
        for field in required_fields:
            if field not in criterion:
                return False, f"Criterion at index {i} missing required field: {field}"

        # Validate weight is a number between 0 and 1
        weight = criterion.get("weight")
        if not isinstance(weight, (int, float)):
            return False, f"Criterion '{criterion.get('id')}' weight must be a number"
        if not (0 <= weight <= 1):
            return False, f"Criterion '{criterion.get('id')}' weight must be between 0 and 1"

        # Validate scale
        scale = criterion.get("scale")
        if not isinstance(scale, dict):
            return False, f"Criterion '{criterion.get('id')}' scale must be an object"
        if "min" not in scale or "max" not in scale:
            return False, f"Criterion '{criterion.get('id')}' scale must have min and max"
        if scale["min"] >= scale["max"]:
            return False, f"Criterion '{criterion.get('id')}' scale min must be less than max"

    return True, ""


def get_criteria_weights(criteria: list[dict[str, Any]]) -> dict[str, float]:
    """Extract weights from criteria configuration.

    Args:
        criteria: List of criterion dictionaries

    Returns:
        Dictionary mapping criterion IDs to weights
    """
    return {c["id"]: c["weight"] for c in criteria}


def get_required_criteria_ids(criteria: list[dict[str, Any]]) -> list[str]:
    """Get list of required criterion IDs.

    Args:
        criteria: List of criterion dictionaries

    Returns:
        List of criterion IDs that are required
    """
    return [c["id"] for c in criteria if c.get("required", False)]


def get_auto_calculated_criteria_ids(criteria: list[dict[str, Any]]) -> list[str]:
    """Get list of auto-calculated criterion IDs.

    Args:
        criteria: List of criterion dictionaries

    Returns:
        List of criterion IDs that are auto-calculated
    """
    return [c["id"] for c in criteria if c.get("auto_calculated", False)]


def validate_score(score: int, criterion: dict[str, Any]) -> tuple[bool, str]:
    """Validate a score against a criterion's scale.

    Args:
        score: The score to validate
        criterion: The criterion definition

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(score, (int, float)):
        return False, "Score must be a number"

    scale = criterion.get("scale", {})
    min_score = scale.get("min", 0)
    max_score = scale.get("max", 100)

    if not (min_score <= score <= max_score):
        return False, f"Score must be between {min_score} and {max_score}"

    return True, ""


def normalize_price_score(quoted_price: float, max_budget: float) -> int:
    """Calculate a normalized price competitiveness score.

    This formula gives:
    - 100 points for bids at or below budget
    - Decreasing scores for bids over budget (but not zero)
    - Explicit handling for edge cases

    Args:
        quoted_price: The vendor's quoted price
        max_budget: The maximum budget for the tender

    Returns:
        Normalized score between 0 and 100
    """
    # Check for invalid price first
    if quoted_price <= 0:
        # Invalid price - give lowest score
        return 0

    # Check for invalid budget
    if max_budget <= 0:
        # No budget specified - give neutral score
        return 50

    if quoted_price <= max_budget:
        # Within budget - full points
        return 100

    # Over budget - calculate penalty
    # Formula: 100 - ((over_budget_amount / max_budget) * 100)
    # This ensures over-budget bids still get some points unless extremely over
    over_budget_ratio = (quoted_price - max_budget) / max_budget
    score = 100 - (over_budget_ratio * 100)

    # Clamp to minimum of 0 (but allow some points for moderately over-budget)
    return int(round(max(0, min(100, score))))


def validate_vendor_scores(
    vendor: dict[str, Any],
    criteria: list[dict[str, Any]],
    tender: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate a vendor's scores against criteria requirements.

    Args:
        vendor: Vendor dictionary with scores
        criteria: List of criterion definitions
        tender: Tender configuration (for price normalization)

    Returns:
        Tuple of (is_valid, list_of_error_messages)
    """
    errors = []
    scores = vendor.get("scores", {})

    if not isinstance(scores, dict):
        errors.append("Vendor scores must be an object")
        return False, errors

    # Auto-calculate price score if not provided (before validation)
    auto_ids = get_auto_calculated_criteria_ids(criteria)
    for criterion_id in auto_ids:
        if criterion_id not in scores:
            if criterion_id == "price_competitiveness":
                quoted_price = vendor.get("quotedPrice", 0)
                max_budget = tender.get("maximumBudget", 0)
                scores[criterion_id] = normalize_price_score(quoted_price, max_budget)

    # Check required scores are present (excluding auto-calculated)
    required_ids = get_required_criteria_ids(criteria)
    for criterion_id in required_ids:
        if criterion_id not in scores:
            criterion = next((c for c in criteria if c["id"] == criterion_id), None)
            criterion_name = criterion.get("name", criterion_id) if criterion else criterion_id
            errors.append(f"Missing required score: {criterion_name}")

    # Validate score ranges for present scores
    for criterion_id, score in scores.items():
        criterion = next((c for c in criteria if c["id"] == criterion_id), None)
        if not criterion:
            errors.append(f"Unknown criterion: {criterion_id}")
            continue

        valid, error = validate_score(score, criterion)
        if not valid:
            criterion_name = criterion.get("name", criterion_id)
            errors.append(f"Invalid score for {criterion_name}: {error}")

    return len(errors) == 0, errors


def normalize_vendor_scores(
    vendor: dict[str, Any],
    criteria: list[dict[str, Any]],
    tender: dict[str, Any],
) -> dict[str, Any]:
    """Normalize and validate a vendor's scores.

    This function:
    1. Validates scores against criteria
    2. Auto-calculates missing auto-calculated scores
    3. Returns the normalized vendor object

    Args:
        vendor: Vendor dictionary
        criteria: List of criterion definitions
        tender: Tender configuration

    Returns:
        Normalized vendor dictionary

    Raises:
        ValueError: If validation fails
    """
    # Ensure scores object exists
    if "scores" not in vendor:
        vendor["scores"] = {}

    valid, errors = validate_vendor_scores(vendor, criteria, tender)
    if not valid:
        raise ValueError("; ".join(errors))

    return vendor

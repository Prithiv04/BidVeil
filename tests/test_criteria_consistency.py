"""Test frontend-backend criteria consistency.

This test ensures that the frontend CRITERIA_CONFIG and weights
match the backend DEFAULT_CRITERIA configuration.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from criteria import DEFAULT_CRITERIA


def test_frontend_backend_criteria_match():
    """Test that frontend and backend use the same criteria IDs and weights."""
    # Backend criteria from criteria.py
    backend_criteria = DEFAULT_CRITERIA
    backend_weights = {c["id"]: c["weight"] for c in backend_criteria}
    backend_ids = set(c["id"] for c in backend_criteria)
    
    # Expected frontend weights (from static/app.js)
    frontend_weights = {
        "technical_compliance": 0.3,
        "price_competitiveness": 0.25,
        "relevant_experience": 0.2,
        "delivery_timeline": 0.15,
        "eligibility_and_documentation": 0.1,
    }
    
    # Expected frontend CRITERIA_CONFIG (manual scoring only, excluding auto-calculated)
    frontend_manual_criteria = [
        "technical_compliance",
        "relevant_experience",
        "delivery_timeline",
        "eligibility_and_documentation",
    ]
    
    # Test 1: Backend weights match expected frontend weights
    assert backend_weights == frontend_weights, (
        f"Backend weights mismatch. Backend: {backend_weights}, "
        f"Expected: {frontend_weights}"
    )
    
    # Test 2: Backend has all expected criteria
    assert backend_ids == set(frontend_weights.keys()), (
        f"Backend criteria IDs mismatch. Backend: {backend_ids}, "
        f"Expected: {set(frontend_weights.keys())}"
    )
    
    # Test 3: Manual criteria are subset of all criteria
    assert set(frontend_manual_criteria).issubset(backend_ids), (
        f"Manual criteria not in backend. Manual: {set(frontend_manual_criteria)}, "
        f"Backend: {backend_ids}"
    )
    
    # Test 4: Price competitiveness is marked as auto-calculated
    price_criterion = next(c for c in backend_criteria if c["id"] == "price_competitiveness")
    assert price_criterion["auto_calculated"] is True, (
        "price_competitiveness should be marked as auto_calculated"
    )
    
    # Test 5: Manual criteria are not auto-calculated
    for criterion_id in frontend_manual_criteria:
        criterion = next(c for c in backend_criteria if c["id"] == criterion_id)
        assert criterion["auto_calculated"] is False, (
            f"{criterion_id} should not be auto_calculated"
        )
    
    print("✓ All frontend-backend criteria consistency tests passed")


def test_weights_sum_to_one():
    """Test that criteria weights sum to 1.0."""
    total_weight = sum(c["weight"] for c in DEFAULT_CRITERIA)
    assert abs(total_weight - 1.0) < 0.001, (
        f"Criteria weights must sum to 1.0, got {total_weight}"
    )
    print("✓ Weights sum to 1.0")


def test_price_normalization_formula():
    """Test price score normalization formula matches frontend implementation."""
    from criteria import normalize_price_score
    
    # Test case 1: Within budget
    assert normalize_price_score(500000, 1000000) == 100, (
        "Within budget should get full score"
    )
    
    # Test case 2: Exactly at budget
    assert normalize_price_score(1000000, 1000000) == 100, (
        "At budget should get full score"
    )
    
    # Test case 3: Slightly over budget
    score = normalize_price_score(1100000, 1000000)
    expected = 100 - ((1100000 - 1000000) / 1000000) * 100
    assert abs(score - expected) < 1, (
        f"Over budget score mismatch. Got {score}, expected {expected}"
    )
    
    # Test case 4: Zero budget (returns neutral score per backend logic)
    assert normalize_price_score(500000, 0) == 50, (
        "Zero budget should result in neutral score (50)"
    )
    
    # Test case 5: Zero price
    assert normalize_price_score(0, 1000000) == 0, (
        "Zero price should result in 0 score"
    )
    
    print("✓ Price normalization formula tests passed")


if __name__ == "__main__":
    test_frontend_backend_criteria_match()
    test_weights_sum_to_one()
    test_price_normalization_formula()
    print("\n✅ All criteria consistency tests passed!")

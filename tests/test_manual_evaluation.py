"""Tests for manual evaluation functionality."""

import pytest
import app as bidveil
import criteria


def test_default_criteria_valid():
    """Default criteria configuration should be valid."""
    valid, error = criteria.validate_criteria_config(criteria.DEFAULT_CRITERIA)
    assert valid, f"Default criteria should be valid: {error}"


def test_criteria_weights_sum_to_one():
    """Criteria weights must sum to 1.0."""
    valid, error = criteria.validate_criteria_config(criteria.DEFAULT_CRITERIA)
    assert valid, error
    
    weights = criteria.get_criteria_weights(criteria.DEFAULT_CRITERIA)
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"


def test_criteria_unique_ids():
    """Criteria must have unique IDs."""
    ids = [c["id"] for c in criteria.DEFAULT_CRITERIA]
    assert len(ids) == len(set(ids)), "Criteria IDs must be unique"


def test_criteria_scale_validation():
    """Criteria scale definitions should be valid."""
    for criterion in criteria.DEFAULT_CRITERIA:
        scale = criterion.get("scale")
        assert "min" in scale, f"Criterion {criterion['id']} missing scale min"
        assert "max" in scale, f"Criterion {criterion['id']} missing scale max"
        assert scale["min"] < scale["max"], f"Criterion {criterion['id']} scale min must be less than max"


def test_criteria_invalid_weights():
    """Invalid weight configuration should be rejected."""
    invalid_criteria = [
        {
            "id": "test",
            "name": "Test",
            "weight": 0.5,
            "scale": {"min": 0, "max": 100},
        }
    ]
    valid, error = criteria.validate_criteria_config(invalid_criteria)
    assert not valid, "Single criterion with weight 0.5 should be invalid (sum != 1.0)"
    assert "sum to 1.0" in error.lower()


def test_price_normalization_within_budget():
    """Bids within budget should get full points."""
    assert criteria.normalize_price_score(50000, 100000) == 100
    assert criteria.normalize_price_score(100000, 100000) == 100
    # Note: 0 price is handled as invalid, returns 0


def test_price_normalization_over_budget():
    """Over-budget bids should get reduced but non-zero scores."""
    score = criteria.normalize_price_score(150000, 100000)
    assert 0 <= score <= 100, "Over-budget score should be between 0 and 100"
    assert score < 100, "Over-budget bid should get less than full points"
    
    # More over budget = lower score
    score_1 = criteria.normalize_price_score(120000, 100000)
    score_2 = criteria.normalize_price_score(200000, 100000)
    assert score_2 < score_1, "More over budget should result in lower score"


def test_price_normalization_no_budget():
    """With no budget, should return neutral score."""
    # When max_budget is 0, it returns 50 (neutral)
    assert criteria.normalize_price_score(50000, 0) == 50
    # When both are 0, price is invalid so returns 0
    assert criteria.normalize_price_score(0, 0) == 0


def test_price_normalization_edge_cases():
    """Edge cases for price normalization."""
    assert criteria.normalize_price_score(-1000, 100000) == 0, "Negative price should get 0"
    assert criteria.normalize_price_score(50000, -1000) == 50, "Negative budget should return neutral"


def test_validate_score_valid():
    """Valid scores should pass validation."""
    criterion = {"scale": {"min": 0, "max": 100}}
    valid, error = criteria.validate_score(50, criterion)
    assert valid, error
    assert error == ""


def test_validate_score_out_of_range():
    """Scores out of range should fail validation."""
    criterion = {"scale": {"min": 0, "max": 100}}
    valid, error = criteria.validate_score(150, criterion)
    assert not valid
    assert "between" in error.lower()
    
    valid, error = criteria.validate_score(-10, criterion)
    assert not valid


def test_validate_vendor_scores_valid():
    """Valid vendor scores should pass validation."""
    vendor = {
        "vendorName": "Test Vendor",
        "quotedPrice": 50000,
        "scores": {
            "technical_compliance": 80,
            "relevant_experience": 75,
            "delivery_timeline": 90,
            "eligibility_and_documentation": 85,
        }
    }
    tender = {"maximumBudget": 100000}
    valid, errors = criteria.validate_vendor_scores(vendor, criteria.DEFAULT_CRITERIA, tender)
    assert valid, f"Valid scores should pass: {errors}"
    assert len(errors) == 0


def test_validate_vendor_scores_missing_required():
    """Missing required scores should fail validation."""
    vendor = {
        "vendorName": "Test Vendor",
        "quotedPrice": 50000,
        "scores": {
            "technical_compliance": 80,
            # Missing other required scores
        }
    }
    tender = {"maximumBudget": 100000}
    valid, errors = criteria.validate_vendor_scores(vendor, criteria.DEFAULT_CRITERIA, tender)
    assert not valid, "Missing required scores should fail validation"
    assert len(errors) > 0
    assert any("Missing" in error for error in errors)


def test_validate_vendor_scores_auto_calculates_price():
    """Price score should be auto-calculated if not provided."""
    vendor = {
        "vendorName": "Test Vendor",
        "quotedPrice": 50000,
        "scores": {
            "technical_compliance": 80,
            "relevant_experience": 75,
            "delivery_timeline": 90,
            "eligibility_and_documentation": 85,
        }
    }
    tender = {"maximumBudget": 100000}
    criteria.normalize_vendor_scores(vendor, criteria.DEFAULT_CRITERIA, tender)
    assert "price_competitiveness" in vendor["scores"]
    assert vendor["scores"]["price_competitiveness"] == 100  # Within budget


def test_normalize_vendor_scores_invalid():
    """Invalid scores should raise ValueError."""
    vendor = {
        "vendorName": "Test Vendor",
        "quotedPrice": 50000,
        "scores": {
            "technical_compliance": 150,  # Invalid: > 100
        }
    }
    tender = {"maximumBudget": 100000}
    with pytest.raises(ValueError):
        criteria.normalize_vendor_scores(vendor, criteria.DEFAULT_CRITERIA, tender)


def test_evaluate_manual_scores_basic():
    """Basic manual evaluation should work."""
    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": [
            {
                "vendorName": "Vendor A",
                "quotedPrice": 75000,
                "scores": {
                    "technical_compliance": 80,
                    "relevant_experience": 75,
                    "delivery_timeline": 90,
                    "eligibility_and_documentation": 85,
                },
                "evidence": {
                    "technical_compliance": "Meets all requirements",
                    "relevant_experience": "5 similar projects",
                    "delivery_timeline": "6 months",
                    "eligibility_and_documentation": "All docs provided",
                },
                "strengths": ["Strong technical team"],
                "weaknesses": ["Higher price"],
            }
        ]
    }

    result = bidveil.evaluate_manual_scores(payload)

    assert result["evaluationMode"] == "manual"
    assert len(result["vendors"]) == 1
    assert result["vendors"][0]["vendorName"] == "Vendor A"
    assert result["vendors"][0]["rank"] == 1
    assert "weightedScore" in result["vendors"][0]
    # Check that weighted score is calculated
    assert result["vendors"][0]["weightedScore"] > 0


def test_evaluate_manual_scores_ranking():
    """Manual evaluation should rank vendors correctly."""
    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": [
            {
                "vendorName": "Vendor A",
                "quotedPrice": 75000,
                "scores": {
                    "technical_compliance": 80,
                    "relevant_experience": 75,
                    "delivery_timeline": 90,
                    "eligibility_and_documentation": 85,
                },
            },
            {
                "vendorName": "Vendor B",
                "quotedPrice": 80000,
                "scores": {
                    "technical_compliance": 95,
                    "relevant_experience": 90,
                    "delivery_timeline": 85,
                    "eligibility_and_documentation": 90,
                },
            }
        ]
    }

    result = bidveil.evaluate_manual_scores(payload)

    assert len(result["vendors"]) == 2
    # Vendor B should rank higher due to better scores
    assert result["vendors"][0]["rank"] == 1
    assert result["vendors"][0]["vendorName"] == "Vendor B"
    assert result["vendors"][1]["rank"] == 2
    assert result["vendors"][1]["vendorName"] == "Vendor A"


def test_evaluate_manual_scores_missing_required():
    """Missing required scores should raise error."""
    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": [
            {
                "vendorName": "Vendor A",
                "quotedPrice": 75000,
                "scores": {
                    # Missing required scores
                },
            }
        ]
    }
    
    with pytest.raises(bidveil.EvaluationServiceError) as exc_info:
        bidveil.evaluate_manual_scores(payload)
    
    assert "Missing" in str(exc_info.value)


def test_evaluate_manual_scores_invalid_score():
    """Invalid scores should raise error."""
    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": [
            {
                "vendorName": "Vendor A",
                "quotedPrice": 75000,
                "scores": {
                    "technical_compliance": 150,  # Invalid
                    "relevant_experience": 75,
                    "delivery_timeline": 90,
                    "eligibility_and_documentation": 85,
                },
            }
        ]
    }

    with pytest.raises(bidveil.EvaluationServiceError) as exc_info:
        bidveil.evaluate_manual_scores(payload)

    assert "Invalid" in str(exc_info.value) or "between" in str(exc_info.value).lower()


def test_evaluate_manual_scores_no_bids():
    """No bids should raise error."""
    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": []
    }
    
    with pytest.raises(bidveil.EvaluationServiceError) as exc_info:
        bidveil.evaluate_manual_scores(payload)
    
    assert "at least one vendor" in str(exc_info.value).lower()


def test_manual_evaluate_endpoint():
    """Manual evaluation endpoint should work."""
    from flask import Flask
    client = bidveil.app.test_client()

    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": [
            {
                "vendorName": "Vendor A",
                "quotedPrice": 75000,
                "scores": {
                    "technical_compliance": 80,
                    "relevant_experience": 75,
                    "delivery_timeline": 90,
                    "eligibility_and_documentation": 85,
                },
            }
        ]
    }

    response = client.post(
        "/api/evaluate/manual",
        json=payload,
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["evaluationMode"] == "manual"
    assert len(data["vendors"]) == 1
    assert data["vendors"][0]["vendorName"] == "Vendor A"


def test_manual_evaluate_endpoint_invalid():
    """Manual evaluation endpoint should reject invalid input."""
    client = bidveil.app.test_client()

    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": [
            {
                "vendorName": "Vendor A",
                "quotedPrice": 75000,
                "scores": {},  # Missing required scores
            }
        ]
    }

    response = client.post(
        "/api/evaluate/manual",
        json=payload,
    )

    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_get_criteria_weights():
    """Extract weights from criteria configuration."""
    weights = criteria.get_criteria_weights(criteria.DEFAULT_CRITERIA)
    assert isinstance(weights, dict)
    assert "technical_compliance" in weights
    assert weights["technical_compliance"] == 0.30


def test_get_required_criteria_ids():
    """Get list of required criterion IDs."""
    required = criteria.get_required_criteria_ids(criteria.DEFAULT_CRITERIA)
    assert "technical_compliance" in required
    assert "relevant_experience" in required
    assert "delivery_timeline" in required
    assert "eligibility_and_documentation" in required
    # Price is auto-calculated, not required
    assert "price_competitiveness" not in required


def test_get_auto_calculated_criteria_ids():
    """Get list of auto-calculated criterion IDs."""
    auto = criteria.get_auto_calculated_criteria_ids(criteria.DEFAULT_CRITERIA)
    assert "price_competitiveness" in auto

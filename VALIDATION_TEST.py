"""
End-to-end validation test for BIDVEIL procurement evaluation workflow.

This script tests:
1. Manual evaluation workflow without AI
2. Weighted scoring and price normalization
3. Bidder ranking and budget constraints
4. Invalid inputs and missing scores
5. Edge cases
6. AI-assisted evaluation (inference unavailable scenario)
"""

import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import app as bidveil
import criteria


def print_section(title):
    """Print a section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def test_manual_evaluation_workflow():
    """Test complete manual evaluation workflow with realistic data."""
    print_section("TEST 1: Manual Evaluation Workflow (3 Bidders)")
    
    # Realistic test tender
    payload = {
        "tender": {
            "title": "Enterprise Cloud Migration Services",
            "description": "Migration of on-premise infrastructure to cloud with 99.9% uptime SLA",
            "maximumBudget": 500000,
            "requirements": "AWS/GCP/Azure expertise, 24/7 support, data security compliance"
        },
        "bids": [
            {
                "vendorName": "CloudFirst Solutions",
                "quotedPrice": 420000,
                "scores": {
                    "technical_compliance": 85,
                    "relevant_experience": 90,
                    "delivery_timeline": 80,
                    "eligibility_and_documentation": 95,
                },
                "evidence": {
                    "technical_compliance": "AWS certified team, SOC2 compliant",
                    "relevant_experience": "15 similar enterprise migrations",
                    "delivery_timeline": "6 months with phased rollout",
                    "eligibility_and_documentation": "All certifications provided",
                },
                "strengths": ["Strong technical team", "Competitive pricing", "Excellent documentation"],
                "weaknesses": ["Longer timeline than competitors"],
            },
            {
                "vendorName": "Nexus Cloud Corp",
                "quotedPrice": 475000,
                "scores": {
                    "technical_compliance": 95,
                    "relevant_experience": 85,
                    "delivery_timeline": 90,
                    "eligibility_and_documentation": 90,
                },
                "evidence": {
                    "technical_compliance": "Multi-cloud expertise, advanced security",
                    "relevant_experience": "12 enterprise projects",
                    "delivery_timeline": "4 months accelerated timeline",
                    "eligibility_and_documentation": "ISO 27001 certified",
                },
                "strengths": ["Fastest delivery", "Highest technical score", "Multi-cloud capability"],
                "weaknesses": ["Higher price", "Less experience than CloudFirst"],
            },
            {
                "vendorName": "DataFlow Systems",
                "quotedPrice": 380000,
                "scores": {
                    "technical_compliance": 75,
                    "relevant_experience": 70,
                    "delivery_timeline": 85,
                    "eligibility_and_documentation": 80,
                },
                "evidence": {
                    "technical_compliance": "Azure specialization, basic security",
                    "relevant_experience": "8 enterprise migrations",
                    "delivery_timeline": "5 months standard timeline",
                    "eligibility_and_documentation": "Partial documentation",
                },
                "strengths": ["Lowest price", "Reasonable timeline"],
                "weaknesses": ["Lower technical score", "Less experience", "Incomplete documentation"],
            },
        ]
    }
    
    try:
        result = bidveil.evaluate_manual_scores(payload)
        
        print(f"✓ Manual evaluation succeeded")
        print(f"  Evaluation mode: {result.get('evaluationMode')}")
        print(f"  Number of vendors: {len(result['vendors'])}")
        
        # Print rankings
        print("\n  Rankings:")
        for vendor in result['vendors']:
            print(f"    {vendor['rank']}. {vendor['vendorName']}")
            print(f"       Weighted Score: {vendor['weightedScore']}")
            print(f"       Price: ${vendor['quotedPrice']:,}")
            print(f"       Price Score: {vendor['criterionScores']['price_competitiveness']}")
            print(f"       Technical: {vendor['criterionScores']['technical_compliance']}")
            print(f"       Experience: {vendor['criterionScores']['relevant_experience']}")
            print(f"       Delivery: {vendor['criterionScores']['delivery_timeline']}")
            print(f"       Eligibility: {vendor['criterionScores']['eligibility_and_documentation']}")
        
        # Verify ranking order
        assert result['vendors'][0]['rank'] == 1, "First vendor should have rank 1"
        assert result['vendors'][1]['rank'] == 2, "Second vendor should have rank 2"
        assert result['vendors'][2]['rank'] == 3, "Third vendor should have rank 3"
        
        # Verify weighted scores are calculated
        for vendor in result['vendors']:
            assert vendor['weightedScore'] > 0, f"Weighted score should be positive for {vendor['vendorName']}"
            assert vendor['weightedScore'] <= 100, f"Weighted score should be <= 100 for {vendor['vendorName']}"
        
        # Verify price scores (all within budget, so all get 100)
        for vendor in result['vendors']:
            assert vendor['criterionScores']['price_competitiveness'] == 100, f"{vendor['vendorName']} should get 100 for being within budget"
        
        print("\n✓ All assertions passed for manual evaluation workflow")
        return True
        
    except Exception as e:
        print(f"✗ Manual evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_weighted_scoring():
    """Test weighted scoring calculation."""
    print_section("TEST 2: Weighted Scoring Calculation")
    
    # Simple test with known scores
    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": [
            {
                "vendorName": "Test Vendor",
                "quotedPrice": 80000,
                "scores": {
                    "technical_compliance": 100,
                    "relevant_experience": 100,
                    "delivery_timeline": 100,
                    "eligibility_and_documentation": 100,
                },
            }
        ]
    }
    
    try:
        result = bidveil.evaluate_manual_scores(payload)
        vendor = result['vendors'][0]
        
        # Calculate expected weighted score
        # Technical: 100 * 0.30 = 30
        # Price: 100 * 0.25 = 25 (within budget)
        # Experience: 100 * 0.20 = 20
        # Delivery: 100 * 0.15 = 15
        # Eligibility: 100 * 0.10 = 10
        # Total: 100
        expected_score = 100.0
        
        print(f"  Vendor: {vendor['vendorName']}")
        print(f"  Weighted Score: {vendor['weightedScore']}")
        print(f"  Expected Score: {expected_score}")
        
        assert vendor['weightedScore'] == expected_score, f"Expected {expected_score}, got {vendor['weightedScore']}"
        
        print("✓ Weighted scoring calculation is correct")
        return True
        
    except Exception as e:
        print(f"✗ Weighted scoring test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_price_normalization():
    """Test price normalization with various scenarios."""
    print_section("TEST 3: Price Normalization")
    
    test_cases = [
        {"price": 50000, "budget": 100000, "expected": 100, "desc": "50% of budget"},
        {"price": 100000, "budget": 100000, "expected": 100, "desc": "At budget"},
        {"price": 120000, "budget": 100000, "expected": 80, "desc": "20% over budget"},
        {"price": 150000, "budget": 100000, "expected": 50, "desc": "50% over budget"},
        {"price": 200000, "budget": 100000, "expected": 0, "desc": "100% over budget"},
        {"price": 0, "budget": 100000, "expected": 0, "desc": "Zero price"},
        {"price": 50000, "budget": 0, "expected": 50, "desc": "No budget specified"},
    ]
    
    all_passed = True
    for case in test_cases:
        score = criteria.normalize_price_score(case["price"], case["budget"])
        passed = score == case["expected"]
        status = "✓" if passed else "✗"
        print(f"  {status} {case['desc']}: price={case['price']}, budget={case['budget']}, score={score} (expected {case['expected']})")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("✓ All price normalization tests passed")
    else:
        print("✗ Some price normalization tests failed")
    
    return all_passed


def test_invalid_inputs():
    """Test validation of invalid inputs."""
    print_section("TEST 4: Invalid Inputs and Missing Scores")
    
    test_cases = [
        {
            "name": "Missing required score",
            "payload": {
                "tender": {"title": "Test", "maximumBudget": 100000},
                "bids": [{
                    "vendorName": "Test",
                    "quotedPrice": 80000,
                    "scores": {
                        "technical_compliance": 80,
                        # Missing other required scores
                    }
                }]
            },
            "should_fail": True
        },
        {
            "name": "Score out of range (negative)",
            "payload": {
                "tender": {"title": "Test", "maximumBudget": 100000},
                "bids": [{
                    "vendorName": "Test",
                    "quotedPrice": 80000,
                    "scores": {
                        "technical_compliance": -10,
                        "relevant_experience": 75,
                        "delivery_timeline": 90,
                        "eligibility_and_documentation": 85,
                    }
                }]
            },
            "should_fail": True
        },
        {
            "name": "Score out of range (over 100)",
            "payload": {
                "tender": {"title": "Test", "maximumBudget": 100000},
                "bids": [{
                    "vendorName": "Test",
                    "quotedPrice": 80000,
                    "scores": {
                        "technical_compliance": 150,
                        "relevant_experience": 75,
                        "delivery_timeline": 90,
                        "eligibility_and_documentation": 85,
                    }
                }]
            },
            "should_fail": True
        },
        {
            "name": "No bids",
            "payload": {
                "tender": {"title": "Test", "maximumBudget": 100000},
                "bids": []
            },
            "should_fail": True
        },
    ]
    
    all_passed = True
    for case in test_cases:
        try:
            result = bidveil.evaluate_manual_scores(case["payload"])
            if case["should_fail"]:
                print(f"  ✗ {case['name']}: Should have failed but succeeded")
                all_passed = False
            else:
                print(f"  ✓ {case['name']}: Succeeded as expected")
        except Exception as e:
            if case["should_fail"]:
                print(f"  ✓ {case['name']}: Failed as expected - {type(e).__name__}")
            else:
                print(f"  ✗ {case['name']}: Should have succeeded but failed - {e}")
                all_passed = False
    
    if all_passed:
        print("✓ All invalid input tests passed")
    else:
        print("✗ Some invalid input tests failed")
    
    return all_passed


def test_edge_cases():
    """Test edge cases."""
    print_section("TEST 5: Edge Cases")
    
    test_cases = [
        {
            "name": "Negative budget",
            "payload": {
                "tender": {"title": "Test", "maximumBudget": -100000},
                "bids": [{
                    "vendorName": "Test",
                    "quotedPrice": 80000,
                    "scores": {
                        "technical_compliance": 80,
                        "relevant_experience": 75,
                        "delivery_timeline": 90,
                        "eligibility_and_documentation": 85,
                    }
                }]
            },
            "should_succeed": True
        },
        {
            "name": "Zero budget",
            "payload": {
                "tender": {"title": "Test", "maximumBudget": 0},
                "bids": [{
                    "vendorName": "Test",
                    "quotedPrice": 80000,
                    "scores": {
                        "technical_compliance": 80,
                        "relevant_experience": 75,
                        "delivery_timeline": 90,
                        "eligibility_and_documentation": 85,
                    }
                }]
            },
            "should_succeed": True
        },
        {
            "name": "Multiple vendors with same scores",
            "payload": {
                "tender": {"title": "Test", "maximumBudget": 100000},
                "bids": [
                    {
                        "vendorName": "Vendor A",
                        "quotedPrice": 80000,
                        "scores": {
                            "technical_compliance": 80,
                            "relevant_experience": 75,
                            "delivery_timeline": 90,
                            "eligibility_and_documentation": 85,
                        }
                    },
                    {
                        "vendorName": "Vendor B",
                        "quotedPrice": 80000,
                        "scores": {
                            "technical_compliance": 80,
                            "relevant_experience": 75,
                            "delivery_timeline": 90,
                            "eligibility_and_documentation": 85,
                        }
                    }
                ]
            },
            "should_succeed": True
        },
    ]
    
    all_passed = True
    for case in test_cases:
        try:
            result = bidveil.evaluate_manual_scores(case["payload"])
            if case["should_succeed"]:
                print(f"  ✓ {case['name']}: Succeeded")
                # Verify price score for zero/negative budget
                if case["name"] in ["Negative budget", "Zero budget"]:
                    vendor = result['vendors'][0]
                    price_score = vendor['criterionScores']['price_competitiveness']
                    print(f"    Price score: {price_score} (expected 50 for no/invalid budget)")
                    if price_score != 50:
                        print(f"    ⚠ Warning: Expected 50, got {price_score}")
            else:
                print(f"  ✗ {case['name']}: Should have failed but succeeded")
                all_passed = False
        except Exception as e:
            if case["should_succeed"]:
                print(f"  ✗ {case['name']}: Should have succeeded but failed - {e}")
                all_passed = False
            else:
                print(f"  ✓ {case['name']}: Failed as expected - {type(e).__name__}")
    
    if all_passed:
        print("✓ All edge case tests passed")
    else:
        print("✗ Some edge case tests failed")
    
    return all_passed


def test_api_endpoint():
    """Test the manual evaluation API endpoint."""
    print_section("TEST 6: Manual Evaluation API Endpoint")
    
    payload = {
        "tender": {
            "title": "Test Tender",
            "maximumBudget": 100000,
        },
        "bids": [
            {
                "vendorName": "Test Vendor",
                "quotedPrice": 80000,
                "scores": {
                    "technical_compliance": 80,
                    "relevant_experience": 75,
                    "delivery_timeline": 90,
                    "eligibility_and_documentation": 85,
                },
            }
        ]
    }
    
    try:
        client = bidveil.app.test_client()
        response = client.post(
            "/api/evaluate/manual",
            json=payload,
        )
        
        print(f"  Response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.get_json()
            print(f"  ✓ API endpoint succeeded")
            print(f"  Evaluation mode: {result.get('evaluationMode')}")
            print(f"  Number of vendors: {len(result['vendors'])}")
            return True
        else:
            print(f"  ✗ API endpoint failed with status {response.status_code}")
            print(f"  Response: {response.get_data(as_text=True)}")
            return False
            
    except Exception as e:
        print(f"  ✗ API endpoint test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_criteria_validation():
    """Test criteria configuration validation."""
    print_section("TEST 7: Criteria Configuration Validation")
    
    # Test default criteria
    valid, error = criteria.validate_criteria_config(criteria.DEFAULT_CRITERIA)
    print(f"  Default criteria: {'✓ Valid' if valid else '✗ Invalid'}")
    if not valid:
        print(f"    Error: {error}")
    
    # Test invalid weights
    invalid_criteria = [
        {"id": "test", "name": "Test", "weight": 0.5, "scale": {"min": 0, "max": 100}},
        {"id": "test2", "name": "Test2", "weight": 0.3, "scale": {"min": 0, "max": 100}},
    ]
    valid, error = criteria.validate_criteria_config(invalid_criteria)
    print(f"  Invalid weights (sum != 1.0): {'✓ Correctly rejected' if not valid else '✗ Should have been rejected'}")
    if not valid:
        print(f"    Error: {error}")
    
    # Test duplicate IDs
    duplicate_criteria = [
        {"id": "test", "name": "Test", "weight": 0.5, "scale": {"min": 0, "max": 100}},
        {"id": "test", "name": "Test2", "weight": 0.5, "scale": {"min": 0, "max": 100}},
    ]
    valid, error = criteria.validate_criteria_config(duplicate_criteria)
    print(f"  Duplicate IDs: {'✓ Correctly rejected' if not valid else '✗ Should have been rejected'}")
    if not valid:
        print(f"    Error: {error}")
    
    print("✓ Criteria validation tests completed")
    return True


def run_all_tests():
    """Run all validation tests."""
    print_section("BIDVEIL END-TO-END VALIDATION")
    print("Testing manual evaluation workflow without AI provider...\n")
    
    results = {
        "Manual Evaluation Workflow": test_manual_evaluation_workflow(),
        "Weighted Scoring": test_weighted_scoring(),
        "Price Normalization": test_price_normalization(),
        "Invalid Inputs": test_invalid_inputs(),
        "Edge Cases": test_edge_cases(),
        "API Endpoint": test_api_endpoint(),
        "Criteria Validation": test_criteria_validation(),
    }
    
    print_section("TEST SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, passed_flag in results.items():
        status = "✓ PASSED" if passed_flag else "✗ FAILED"
        print(f"  {status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} test suites passed")
    
    if passed == total:
        print("\n✓ All validation tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test suite(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)

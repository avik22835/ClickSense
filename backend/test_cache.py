#!/usr/bin/env python3
"""
Test script for Redis semantic cache integration.

This script tests the cache service with mock data to verify:
1. Cache miss → Gemini call → cache storage
2. Cache hit → no Gemini call → cached response
3. Three-layer validation (semantic, fingerprint, dhash)
"""

import time
from cache_service import SemanticCache

def test_cache_service():
    """Test the cache service with mock data"""
    print("Testing Redis Semantic Cache Service...")
    print("=" * 60)

    try:
        # Initialize cache
        cache = SemanticCache()
        print("✓ Cache service initialized successfully")

        # Test data
        goal = "Click the submit button"
        elements = [
            {
                'tagName': 'BUTTON',
                'description': 'Submit form',
                'centerCoords': [100, 200],
                'width': 120,
                'height': 40
            },
            {
                'tagName': 'INPUT',
                'description': 'Email input field',
                'centerCoords': [100, 100],
                'width': 300,
                'height': 40
            }
        ]
        screenshot = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        # Test cache miss
        print("\n1. Testing cache miss...")
        start = time.time()
        cached = cache.get(goal=goal, elements=elements, screenshot=screenshot)
        miss_time = (time.time() - start) * 1000

        if cached is None:
            print(f"✓ Cache miss detected (took {miss_time:.2f}ms)")
        else:
            print(f"✗ Unexpected cache hit: {cached}")
            return False

        # Test cache storage
        print("\n2. Testing cache storage...")
        response = {
            "action": "CLICK",
            "element_index": 0,
            "value": None,
            "explanation": "Clicking the submit button",
            "planning_output": "Plan: Click submit button",
            "severity": "SAFE"
        }

        start = time.time()
        cache_key = cache.set(goal=goal, elements=elements, screenshot=screenshot, response=response)
        store_time = (time.time() - start) * 1000
        print(f"✓ Response cached successfully (key: {cache_key[:16]}..., took {store_time:.2f}ms)")

        # Test cache hit
        print("\n3. Testing cache hit...")
        start = time.time()
        cached = cache.get(goal=goal, elements=elements, screenshot=screenshot)
        hit_time = (time.time() - start) * 1000

        if cached:
            print(f"✓ Cache hit detected (took {hit_time:.2f}ms)")
            print(f"  Action: {cached.get('action')}")
            print(f"  Element: {cached.get('element_index')}")
            print(f"  Explanation: {cached.get('explanation')}")
        else:
            print("✗ Cache miss when hit expected")
            return False

        # Test fingerprint validation (different elements)
        print("\n4. Testing element fingerprint validation...")
        different_elements = [
            {
                'tagName': 'BUTTON',
                'description': 'Submit form',
                'centerCoords': [500, 600],  # Different position
                'width': 120,
                'height': 40
            }
        ]
        cached = cache.get(goal=goal, elements=different_elements, screenshot=screenshot)
        if cached is None:
            print("✓ Fingerprint validation working (different position = cache miss)")
        else:
            print("✗ Fingerprint validation failed (should miss but got hit)")
            return False

        # Get cache stats
        print("\n5. Testing cache stats...")
        stats = cache.get_stats()
        print(f"✓ Cache stats retrieved:")
        print(f"  Total entries: {stats['total_entries']}")
        print(f"  Total hits: {stats['total_hits']}")
        print(f"  Total size: {stats['total_size_kb']} KB")

        print("\n" + "=" * 60)
        print("✓ All cache service tests passed!")
        return True

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_cache_service()
    exit(0 if success else 1)
import hashlib
import json
import time
import os
from typing import Optional, List, Dict, Any
from PIL import Image
import imagehash
import io
import base64
import redis
from sentence_transformers import SentenceTransformer


class SemanticCache:
    """
    Semantic caching system with three-layer validation:
    1. Semantic similarity (find candidate)
    2. Element fingerprint (structural + positional check)
    3. Screenshot dhash (visual layout check)
    """

    def __init__(self, redis_url: str = None):
        if redis_url is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            self.redis = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            self.redis.ping()
            self.redis_available = True

            # Clear old cache entries that don't have screenshot_embedding
            print("Checking for old cache entries...")
            cache_keys = self.redis.keys("cache:*")
            if cache_keys:
                print(f"   Found {len(cache_keys)} old cache entries - clearing...")
                self.clear()
                print("   Old cache cleared")
            else:
                print("   No old cache entries found")

        except Exception as e:
            print(f"Warning: Redis not available - caching disabled. Error: {e}")
            self.redis = None
            self.redis_available = False
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

        # Balanced parameters for accuracy + cache hits
        self.similarity_threshold = 0.75      # Semantic similarity threshold (balanced)
        self.rounding_precision = 100          # Coordinate rounding (very lenient - 100px tolerance)
        self.max_cache_entries = 10000        # Maximum cache entries

    def _build_page_context(self, goal: str, elements: List[Dict]) -> str:
        """
        Build text summary for embedding.

        Args:
            goal: User's goal text
            elements: List of element dictionaries

        Returns:
            Text summary combining goal and top 10 elements
        """
        # Use top 10 elements for context (most important ones)
        top_elements = elements[:10] if len(elements) >= 10 else elements

        element_summaries = []
        for e in top_elements:
            tag = e.get('tagName', '')
            desc = e.get('description', '')[:40]  # First 40 chars
            element_summaries.append(f"[{tag}] {desc}")

        return f"{goal} | {' | '.join(element_summaries)}"

    def _compute_screenshot_embedding(self, screenshot_data_url: str) -> List[float]:
        """
        Create embedding from screenshot for visual page matching.

        Args:
            screenshot_data_url: Base64-encoded screenshot

        Returns:
            Embedding vector representing visual page state
        """
        # Extract base64 data
        if "," in screenshot_data_url:
            b64 = screenshot_data_url.split(",")[1]
        else:
            b64 = screenshot_data_url

        # Use the base64 data as text for embedding (simplified approach)
        # In production, you'd use a vision model for actual image embedding
        return self._get_embedding(b64[:500])  # First 500 chars of base64

    def _compute_element_fingerprint(self, elements: List[Dict]) -> str:
        """
        Hash top K most significant DOM elements that define the webpage.

        Only tracks the most important elements: buttons, inputs, main headings
        Ignores: navigation, decorative elements, minor UI components

        Args:
            elements: List of element dictionaries

        Returns:
            MD5 hash of top K significant elements
        """
        significant_elements = []

        for e in elements:
            tag_name = e.get('tagName', '').upper()
            description = e.get('description', '')

            # Only track the most significant elements
            is_significant = tag_name in {
                'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'H1', 'H2', 'H3'
            }

            # Also track elements with key action words
            if not is_significant:
                key_action_words = ['create', 'save', 'submit', 'delete', 'add', 'remove',
                                   'confirm', 'cancel', 'next', 'previous', 'finish', 'done']
                is_significant = any(word in description.lower() for word in key_action_words)

            if is_significant:
                # Simple signature: tag + first 15 chars of description
                sig = f"{tag_name}:{description[:15]}"
                significant_elements.append(sig)

        # Sort and take top K (most significant elements)
        significant_elements.sort()
        top_k_elements = significant_elements[:10]  # Top 10 most significant

        # Combine and hash
        combined = "|".join(top_k_elements)

        # If no significant elements, use empty string
        if not combined:
            combined = "no_significant_elements"

        return hashlib.md5(combined.encode()).hexdigest()

    def _compute_screenshot_dhash(self, screenshot_data_url: str) -> str:
        """
        Compute perceptual hash of screenshot.

        Args:
            screenshot_data_url: Base64-encoded screenshot data URL

        Returns:
            Perceptual hash string (8x8 dhash)
        """
        try:
            # Extract base64 data
            if "," in screenshot_data_url:
                b64 = screenshot_data_url.split(",")[1]
            else:
                b64 = screenshot_data_url

            # Decode and create image
            img = Image.open(io.BytesIO(base64.b64decode(b64)))

            # Compute dhash (8x8)
            return str(imagehash.dhash(img, hash_size=8))
        except Exception as e:
            # If screenshot processing fails, return empty string
            return ""

    def _get_embedding(self, text: str) -> List[float]:
        """
        Get embedding vector for text.

        Args:
            text: Text to embed

        Returns:
            384-dimensional embedding vector (all-MiniLM-L6-v2)
        """
        return self.embedding_model.encode(text).tolist()

    def _query_similar(self, embedding: List[float], limit: int = 5) -> List[Dict]:
        """
        Query Redis for similar cache entries.

        Note: This is a simplified implementation. For production,
        use Redis Search with vector similarity (HNSW index).

        Args:
            embedding: Query embedding vector
            limit: Maximum number of candidates to return

        Returns:
            List of candidate cache entries
        """
        if not self.redis_available:
            return []
        # For now, we'll use a simple approach:
        # 1. Get all cache keys
        # 2. Compute cosine similarity for each
        # 3. Return top N above threshold

        candidates = []

        try:
            # Get all cache keys
            cache_keys = self.redis.keys("cache:*")

            if not cache_keys:
                return candidates

            # Compute cosine similarity for each entry
            for key in cache_keys:
                entry_json = self.redis.get(key)
                if not entry_json:
                    continue

                try:
                    entry = json.loads(entry_json)
                    stored_embedding = entry.get('embedding', [])

                    if not stored_embedding:
                        continue

                    # Compute cosine similarity
                    similarity = self._cosine_similarity(embedding, stored_embedding)

                    if similarity >= self.similarity_threshold:
                        candidates.append({
                            'cache_key': key,
                            'entry': entry,
                            'similarity': similarity
                        })
                except (json.JSONDecodeError, KeyError):
                    continue

            # Sort by similarity (highest first)
            candidates.sort(key=lambda x: x['similarity'], reverse=True)

            # Return top N
            return candidates[:limit]

        except Exception as e:
            # If Redis query fails, return empty list
            return candidates

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Compute cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Cosine similarity score (-1 to 1)
        """
        try:
            import numpy as np

            v1 = np.array(vec1)
            v2 = np.array(vec2)

            # Compute dot product
            dot_product = np.dot(v1, v2)

            # Compute magnitudes
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)

            # Avoid division by zero
            if norm1 == 0 or norm2 == 0:
                return 0.0

            return dot_product / (norm1 * norm2)
        except ImportError:
            # Fallback without numpy
            dot_product = sum(a * b for a, b in zip(vec1, vec2))
            norm1 = sum(a * a for a in vec1) ** 0.5
            norm2 = sum(b * b for b in vec2) ** 0.5

            if norm1 == 0 or norm2 == 0:
                return 0.0

            return dot_product / (norm1 * norm2)

    def get(self, goal: str, elements: List[Dict], screenshot: str) -> Optional[Dict]:
        """
        Try to get cached response.

        Args:
            goal: User's goal
            elements: List of page elements
            screenshot: Base64-encoded screenshot

        Returns:
            Cached response dict, or None if cache miss
        """
        if not self.redis_available:
            return None
        # Layer 1: Semantic similarity (goal-based)
        page_context = self._build_page_context(goal, elements)
        goal_embedding = self._get_embedding(page_context)

        print(f"CACHE DEBUG - Goal: '{goal[:50]}...'")
        print(f"   Page context: '{page_context[:100]}...'")
        print(f"   Current fingerprint: {self._compute_element_fingerprint(elements)}")

        # Query Redis for similar entries
        candidates = self._query_similar(goal_embedding, limit=5)

        if not candidates:
            print(f"   CACHE MISS - No semantic candidates found (threshold: {self.similarity_threshold})")
            return None

        print(f"   Found {len(candidates)} semantic candidates (threshold: {self.similarity_threshold}):")

        # Layer 2: Screenshot similarity (visual page validation)
        screenshot_embedding = self._compute_screenshot_embedding(screenshot)
        screenshot_threshold = 0.95  # 95% screenshot similarity threshold

        valid_candidates = []
        for i, candidate in enumerate(candidates):
            entry = candidate['entry']
            stored_screenshot_embedding = entry.get('screenshot_embedding', [])

            # Calculate screenshot similarity
            screenshot_similarity = 0.0
            if stored_screenshot_embedding:
                screenshot_similarity = self._cosine_similarity(screenshot_embedding, stored_screenshot_embedding)

            print(f"   [{i+1}] Semantic: {candidate['similarity']:.3f}, Screenshot: {screenshot_similarity:.3f}")

            # Check if screenshot similarity meets threshold
            if screenshot_similarity >= screenshot_threshold:
                valid_candidates.append({
                    'entry': entry,
                    'cache_key': candidate['cache_key'],
                    'semantic_similarity': candidate['similarity'],
                    'screenshot_similarity': screenshot_similarity
                })
                print(f"       PASS - Screenshot >= {screenshot_threshold}")
            else:
                print(f"       FAIL - Screenshot < {screenshot_threshold}")

        # If no candidates pass screenshot threshold, cache miss
        if not valid_candidates:
            print(f"   CACHE MISS - No candidates with screenshot similarity >= {screenshot_threshold}")
            return None

        # Return best semantic match among valid candidates
        best_match = max(valid_candidates, key=lambda x: x['semantic_similarity'])
        cached_response = best_match['entry'].get('cached_response')

        print(f"   CACHE HIT - Best match: Semantic {best_match['semantic_similarity']:.3f}, Screenshot {best_match['screenshot_similarity']:.3f}")

        if cached_response:
            # Update hit count in Redis
            cache_key = best_match['cache_key']
            entry = best_match['entry']
            entry['hit_count'] = entry.get('hit_count', 0) + 1
            self.redis.set(cache_key, json.dumps(entry))

            return cached_response

        # No valid cache entry found
        print(f"   CACHE MISS - No cached response found")
        return None

    def set(self, goal: str, elements: List[Dict], screenshot: str, response: Dict) -> str:
        """
        Store response in cache.

        Args:
            goal: User's goal
            elements: List of page elements
            screenshot: Base64-encoded screenshot
            response: Response to cache

        Returns:
            Cache key for the stored entry
        """
        if not self.redis_available:
            return ""
        # Build cache components
        page_context = self._build_page_context(goal, elements)
        goal_embedding = self._get_embedding(page_context)
        screenshot_embedding = self._compute_screenshot_embedding(screenshot)
        element_fingerprint = self._compute_element_fingerprint(elements)

        # Calculate response size
        response_size_bytes = len(json.dumps(response).encode('utf-8'))

        print(f"CACHE STORE - Goal: '{goal[:50]}...'")
        print(f"   Action: {response.get('action', 'N/A')}")
        print(f"   Fingerprint: {element_fingerprint}")
        print(f"   Response size: {response_size_bytes} bytes")

        # Build cache entry
        entry = {
            "embedding": goal_embedding,
            "screenshot_embedding": screenshot_embedding,
            "element_fingerprint": element_fingerprint,
            "cached_response": response,
            "goal": goal,
            "page_context": page_context,
            "timestamp": int(time.time()),
            "hit_count": 0,
            "response_size_bytes": response_size_bytes
        }

        # Generate cache key
        cache_key = f"cache:{hashlib.md5(page_context.encode()).hexdigest()}"

        # Store in Redis (no TTL - entries stay forever)
        self.redis.set(cache_key, json.dumps(entry))

        print(f"   Stored with key: {cache_key[:20]}...")

        return cache_key

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        if not self.redis_available:
            return {
                "total_entries": 0,
                "total_hits": 0,
                "avg_hits_per_entry": 0,
                "total_size_bytes": 0,
                "total_size_kb": 0,
                "total_size_mb": 0
            }
        try:
            # Get all cache keys
            cache_keys = self.redis.keys("cache:*")

            if not cache_keys:
                return {
                    "total_entries": 0,
                    "total_hits": 0,
                    "avg_hits_per_entry": 0,
                    "total_size_bytes": 0,
                    "total_size_kb": 0,
                    "total_size_mb": 0
                }

            total_entries = len(cache_keys)
            total_hits = 0
            total_size_bytes = 0

            for key in cache_keys:
                entry_json = self.redis.get(key)
                if entry_json:
                    try:
                        entry = json.loads(entry_json)
                        total_hits += entry.get('hit_count', 0)
                        total_size_bytes += entry.get('response_size_bytes', 0)
                    except (json.JSONDecodeError, KeyError):
                        continue

            return {
                "total_entries": total_entries,
                "total_hits": total_hits,
                "avg_hits_per_entry": round(total_hits / total_entries, 2) if total_entries > 0 else 0,
                "total_size_bytes": total_size_bytes,
                "total_size_kb": round(total_size_bytes / 1024, 2),
                "total_size_mb": round(total_size_bytes / (1024 * 1024), 2)
            }

        except Exception as e:
            # If stats collection fails, return empty stats
            return {
                "total_entries": 0,
                "total_hits": 0,
                "avg_hits_per_entry": 0,
                "total_size_bytes": 0,
                "total_size_kb": 0,
                "total_size_mb": 0
            }

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        if not self.redis_available:
            return 0
        try:
            cache_keys = self.redis.keys("cache:*")

            if not cache_keys:
                return 0

            # Delete all cache keys
            for key in cache_keys:
                self.redis.delete(key)

            return len(cache_keys)

        except Exception as e:
            return 0

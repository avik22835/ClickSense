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
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

        # Research-backed default parameters
        self.similarity_threshold = 0.92      # Semantic similarity threshold
        self.dhash_threshold = 10              # Visual layout threshold (bits out of 64)
        self.rounding_precision = 10           # Coordinate rounding (pixels)
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

    def _compute_element_fingerprint(self, elements: List[Dict]) -> str:
        """
        Hash element structure + positions + sizes.

        Args:
            elements: List of element dictionaries

        Returns:
            MD5 hash of the combined element signatures
        """
        parts = []

        for e in elements:
            # Extract element data
            tag_name = e.get('tagName', '')
            description = e.get('description', '')[:40]
            center_coords = e.get('centerCoords', [0, 0])
            width = e.get('width', 0)
            height = e.get('height', 0)

            # Round coordinates to nearest 10px to absorb micro-variations
            cx = round(center_coords[0] / self.rounding_precision) * self.rounding_precision
            cy = round(center_coords[1] / self.rounding_precision) * self.rounding_precision
            w = round(width / self.rounding_precision) * self.rounding_precision
            h = round(height / self.rounding_precision) * self.rounding_precision

            # Build element signature
            sig = f"{tag_name}:{description}:{cx},{cy}:{w}x{h}"
            parts.append(sig)

        # Combine all elements and hash
        combined = "|".join(parts)
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
        # Layer 1: Semantic similarity
        page_context = self._build_page_context(goal, elements)
        embedding = self._get_embedding(page_context)

        # Query Redis for similar entries
        candidates = self._query_similar(embedding, limit=5)

        for candidate in candidates:
            entry = candidate['entry']

            # Layer 2: Element fingerprint check
            current_fingerprint = self._compute_element_fingerprint(elements)
            stored_fingerprint = entry.get('element_fingerprint', '')

            if stored_fingerprint and current_fingerprint != stored_fingerprint:
                # Page structure changed
                continue

            # Layer 3: Screenshot dhash check
            current_dhash = self._compute_screenshot_dhash(screenshot)
            stored_dhash = entry.get('screenshot_dhash', '')

            if stored_dhash and current_dhash:
                try:
                    # Compute Hamming distance
                    distance = imagehash.hex_to_hash(stored_dhash) - imagehash.hex_to_hash(current_dhash)

                    if distance > self.dhash_threshold:
                        # Visual layout changed
                        continue
                except Exception:
                    # If dhash comparison fails, skip this check
                    pass

            # All checks passed - cache hit!
            cached_response = entry.get('cached_response')

            if cached_response:
                # Update hit count in Redis
                cache_key = candidate['cache_key']
                entry['hit_count'] = entry.get('hit_count', 0) + 1
                self.redis.set(cache_key, json.dumps(entry))

                return cached_response

        # No valid cache entry found
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
        # Build cache components
        page_context = self._build_page_context(goal, elements)
        embedding = self._get_embedding(page_context)
        element_fingerprint = self._compute_element_fingerprint(elements)
        screenshot_dhash = self._compute_screenshot_dhash(screenshot)

        # Calculate response size
        response_size_bytes = len(json.dumps(response).encode('utf-8'))

        # Build cache entry
        entry = {
            "embedding": embedding,
            "element_fingerprint": element_fingerprint,
            "screenshot_dhash": screenshot_dhash,
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

        return cache_key

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
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

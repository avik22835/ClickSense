import os
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from models import ActionRequest, ActionResponse
from llm_engine import run_pipeline
from stats_db import init_stats_db

load_dotenv()

app = FastAPI(title="ClickSense Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/clear-cache")
def clear_cache():
    """Clear all cache entries"""
    from cache_service import SemanticCache
    cache = SemanticCache()
    if cache.redis_available:
        cleared = cache.clear()
        return {"status": "success", "cleared_entries": cleared}
    else:
        return {"status": "error", "message": "Redis not available"}


@app.get("/stats")
def get_stats(time_range: str = "7d", include_details: bool = False):
    """
    Comprehensive performance statistics

    Time ranges:
    - 1d: Last 24 hours
    - 7d: Last 7 days
    - 30d: Last 30 days
    - 90d: Last 90 days
    - all: All time
    """
    db_conn = init_stats_db("stats.db")
    cursor = db_conn.cursor()

    # Calculate time range
    now = time.time()
    time_ranges = {
        "1d": now - (24 * 3600),
        "7d": now - (7 * 24 * 3600),
        "30d": now - (30 * 24 * 3600),
        "90d": now - (90 * 24 * 3600),
        "all": 0
    }
    cutoff_time = time_ranges.get(time_range, time_ranges["7d"])

    stats = {}

    # ── 1. OVERALL PERFORMANCE ────────────────────────────────────────
    cursor.execute("""
        SELECT
            COUNT(*) as total_requests,
            SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits,
            SUM(CASE WHEN cache_hit = 0 THEN 1 ELSE 0 END) as cache_misses,
            AVG(response_time_ms) as avg_response_time_ms,
            MIN(response_time_ms) as min_response_time_ms,
            MAX(response_time_ms) as max_response_time_ms,
            SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as total_errors
        FROM requests
        WHERE timestamp >= ?
    """, (cutoff_time,))

    row = cursor.fetchone()
    total_requests = row[0] or 0
    cache_hits = row[1] or 0
    cache_misses = row[2] or 0

    stats["overall"] = {
        "total_requests": total_requests,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_rate_percent": round((cache_hits / total_requests) * 100, 2) if total_requests > 0 else 0,
        "cache_miss_rate_percent": round((cache_misses / total_requests) * 100, 2) if total_requests > 0 else 0,
        "avg_response_time_ms": round(row[3], 2) if row[3] else 0,
        "min_response_time_ms": round(row[4], 2) if row[4] else 0,
        "max_response_time_ms": round(row[5], 2) if row[5] else 0,
        "error_rate_percent": round((row[6] / total_requests) * 100, 2) if total_requests > 0 else 0,
        "total_errors": row[6] or 0
    }

    # ── 2. TIME SAVINGS FROM CACHING ───────────────────────────────────
    cursor.execute("""
        SELECT
            AVG(response_time_ms) as avg_hit_time_ms,
            COUNT(*) as hit_count
        FROM requests
        WHERE cache_hit = 1 AND timestamp >= ?
    """, (cutoff_time,))

    hit_row = cursor.fetchone()
    avg_hit_time_ms = hit_row[0] if hit_row[0] else 0
    hit_count = hit_row[1] or 0

    cursor.execute("""
        SELECT
            AVG(response_time_ms) as avg_miss_time_ms,
            COUNT(*) as miss_count
        FROM requests
        WHERE cache_hit = 0 AND timestamp >= ?
    """, (cutoff_time,))

    miss_row = cursor.fetchone()
    avg_miss_time_ms = miss_row[0] if miss_row[0] else 0
    miss_count = miss_row[1] or 0

    # Calculate time savings
    time_saved_per_hit_ms = avg_miss_time_ms - avg_hit_time_ms
    total_time_saved_ms = time_saved_per_hit_ms * hit_count
    total_time_saved_seconds = total_time_saved_ms / 1000
    total_time_saved_minutes = total_time_saved_seconds / 60
    total_time_saved_hours = total_time_saved_minutes / 60

    stats["time_savings"] = {
        "avg_response_time_hit_ms": round(avg_hit_time_ms, 2),
        "avg_response_time_miss_ms": round(avg_miss_time_ms, 2),
        "time_saved_per_hit_ms": round(time_saved_per_hit_ms, 2),
        "time_saved_per_hit_seconds": round(time_saved_per_hit_ms / 1000, 2),
        "total_time_saved_ms": round(total_time_saved_ms, 2),
        "total_time_saved_seconds": round(total_time_saved_seconds, 2),
        "total_time_saved_minutes": round(total_time_saved_minutes, 2),
        "total_time_saved_hours": round(total_time_saved_hours, 2),
        "speedup_factor": round(avg_miss_time_ms / avg_hit_time_ms, 2) if avg_hit_time_ms > 0 else 0
    }

    # ── 3. COST SAVINGS (assuming Gemini 2.5 Flash pricing) ─────────────
    # Each miss = 2 Gemini calls (planning + grounding)
    # Each hit = 0 Gemini calls
    avg_tokens_per_request = 3000  # Average tokens per request
    total_tokens_without_cache = total_requests * avg_tokens_per_request
    total_tokens_with_cache = cache_misses * avg_tokens_per_request
    tokens_saved = total_tokens_without_cache - total_tokens_with_cache

    cost_per_1m_tokens = 0.075  # USD for Gemini 2.5 Flash
    cost_without_cache = (total_tokens_without_cache / 1_000_000) * cost_per_1m_tokens
    cost_with_cache = (total_tokens_with_cache / 1_000_000) * cost_per_1m_tokens
    cost_saved = cost_without_cache - cost_with_cache

    stats["cost_savings"] = {
        "total_tokens_used": total_tokens_with_cache,
        "total_tokens_saved": tokens_saved,
        "cost_without_cache_usd": round(cost_without_cache, 4),
        "cost_with_cache_usd": round(cost_with_cache, 4),
        "cost_saved_usd": round(cost_saved, 4),
        "cost_reduction_percent": round((cost_saved / cost_without_cache) * 100, 2) if cost_without_cache > 0 else 0,
        "avg_cost_per_request_usd": round(cost_with_cache / total_requests, 6) if total_requests > 0 else 0
    }

    # ── 4. CACHE HEALTH ────────────────────────────────────────────────
    cursor.execute("""
        SELECT
            COUNT(*) as total_entries,
            SUM(CASE WHEN hit_count > 0 THEN 1 ELSE 0 END) as entries_with_hits,
            SUM(CASE WHEN hit_count = 0 THEN 1 ELSE 0 END) as entries_never_hit,
            AVG(hit_count) as avg_hits_per_entry,
            MAX(hit_count) as max_hits,
            MIN(created_at) as oldest_entry,
            MAX(created_at) as newest_entry
        FROM cache_entries
    """)

    cache_row = cursor.fetchone()
    total_entries = cache_row[0] or 0
    entries_with_hits = cache_row[1] or 0
    entries_never_hit = cache_row[2] or 0

    # Calculate cache size
    cursor.execute("""
        SELECT SUM(response_size_bytes) as total_size
        FROM cache_entries
    """)
    size_row = cursor.fetchone()
    total_cache_size_bytes = size_row[0] or 0

    stats["cache_health"] = {
        "total_entries": total_entries,
        "entries_with_hits": entries_with_hits,
        "entries_never_hit": entries_never_hit,
        "entry_utilization_percent": round((entries_with_hits / total_entries) * 100, 2) if total_entries > 0 else 0,
        "avg_hits_per_entry": round(cache_row[3], 2) if cache_row[3] else 0,
        "max_hits": cache_row[4] or 0,
        "oldest_entry_days": round((now - cache_row[5]) / (24 * 3600), 2) if cache_row[5] else 0,
        "newest_entry_days": round((now - cache_row[6]) / (24 * 3600), 2) if cache_row[6] else 0,
        "total_cache_size_bytes": total_cache_size_bytes,
        "total_cache_size_kb": round(total_cache_size_bytes / 1024, 2),
        "total_cache_size_mb": round(total_cache_size_bytes / (1024 * 1024), 2),
        "avg_entry_size_bytes": round(total_cache_size_bytes / total_entries, 2) if total_entries > 0 else 0
    }

    # ── 5. TASK PERFORMANCE ───────────────────────────────────────────
    cursor.execute("""
        SELECT
            COUNT(*) as total_tasks,
            SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) as completed_tasks,
            SUM(CASE WHEN completed = 0 THEN 1 ELSE 0 END) as failed_tasks,
            AVG(total_steps) as avg_steps_per_task,
            AVG(total_time_seconds) as avg_task_time_seconds,
            AVG(cache_hits) as avg_cache_hits_per_task,
            AVG(user_approvals) as avg_approvals_per_task,
            AVG(user_rejections) as avg_rejections_per_task,
            AVG(skips) as avg_skips_per_task,
            AVG(noop_count) as avg_noops_per_task
        FROM tasks
        WHERE timestamp >= ?
    """, (cutoff_time,))

    task_row = cursor.fetchone()
    total_tasks = task_row[0] or 0
    completed_tasks = task_row[1] or 0

    stats["task_performance"] = {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "failed_tasks": task_row[2] or 0,
        "task_completion_rate_percent": round((completed_tasks / total_tasks) * 100, 2) if total_tasks > 0 else 0,
        "avg_steps_per_task": round(task_row[3], 2) if task_row[3] else 0,
        "avg_task_time_seconds": round(task_row[4], 2) if task_row[4] else 0,
        "avg_task_time_minutes": round(task_row[4] / 60, 2) if task_row[4] else 0,
        "avg_cache_hits_per_task": round(task_row[5], 2) if task_row[5] else 0,
        "avg_approvals_per_task": round(task_row[6], 2) if task_row[6] else 0,
        "avg_rejections_per_task": round(task_row[7], 2) if task_row[7] else 0,
        "avg_skips_per_task": round(task_row[8], 2) if task_row[8] else 0,
        "avg_noops_per_task": round(task_row[9], 2) if task_row[9] else 0
    }

    # ── 6. ACTION DISTRIBUTION ────────────────────────────────────────
    cursor.execute("""
        SELECT
            action,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM requests WHERE timestamp >= ?), 2) as percentage
        FROM requests
        WHERE timestamp >= ? AND action IS NOT NULL
        GROUP BY action
        ORDER BY count DESC
    """, (cutoff_time, cutoff_time))

    action_rows = cursor.fetchall()
    stats["action_distribution"] = [
        {"action": row[0], "count": row[1], "percentage": row[2]}
        for row in action_rows
    ]

    # ── 7. TOP GOALS ───────────────────────────────────────────────────
    cursor.execute("""
        SELECT
            goal,
            COUNT(*) as request_count,
            SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits,
            ROUND(AVG(response_time_ms), 2) as avg_response_time_ms
        FROM requests
        WHERE timestamp >= ?
        GROUP BY goal
        ORDER BY request_count DESC
        LIMIT 10
    """, (cutoff_time,))

    goal_rows = cursor.fetchall()
    stats["top_goals"] = [
        {
            "goal": row[0],
            "request_count": row[1],
            "cache_hits": row[2],
            "cache_hit_rate_percent": round((row[2] / row[1]) * 100, 2) if row[1] > 0 else 0,
            "avg_response_time_ms": row[3]
        }
        for row in goal_rows
    ]

    # ── 8. PERFORMANCE PERCENTILES ────────────────────────────────────
    cursor.execute("""
        SELECT response_time_ms
        FROM requests
        WHERE timestamp >= ?
        ORDER BY response_time_ms
    """, (cutoff_time,))

    all_times = [row[0] for row in cursor.fetchall()]

    if all_times:
        n = len(all_times)
        p50_idx = int(n * 0.5)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)

        stats["percentiles"] = {
            "p50_response_time_ms": round(all_times[p50_idx], 2),
            "p95_response_time_ms": round(all_times[p95_idx], 2),
            "p99_response_time_ms": round(all_times[p99_idx], 2)
        }
    else:
        stats["percentiles"] = {
            "p50_response_time_ms": 0,
            "p95_response_time_ms": 0,
            "p99_response_time_ms": 0
        }

    # ── 9. TIMING BREAKDOWN (for cache misses) ───────────────────────
    cursor.execute("""
        SELECT
            AVG(planning_time_ms) as avg_planning_time_ms,
            AVG(grounding_time_ms) as avg_grounding_time_ms,
            AVG(embedding_time_ms) as avg_embedding_time_ms,
            AVG(cache_lookup_time_ms) as avg_cache_lookup_time_ms
        FROM requests
        WHERE cache_hit = 0 AND timestamp >= ?
    """, (cutoff_time,))

    timing_row = cursor.fetchone()
    stats["timing_breakdown"] = {
        "avg_planning_time_ms": round(timing_row[0], 2) if timing_row[0] else 0,
        "avg_grounding_time_ms": round(timing_row[1], 2) if timing_row[1] else 0,
        "avg_embedding_time_ms": round(timing_row[2], 2) if timing_row[2] else 0,
        "avg_cache_lookup_time_ms": round(timing_row[3], 2) if timing_row[3] else 0
    }

    # ── 10. REQUEST RATE ─────────────────────────────────────────────
    cursor.execute("""
        SELECT
            COUNT(*) as count,
            datetime(timestamp, 'unixepoch', 'localtime') as hour
        FROM requests
        WHERE timestamp >= ?
        GROUP BY strftime('%Y-%m-%d %H', datetime(timestamp, 'unixepoch', 'localtime'))
        ORDER BY hour DESC
        LIMIT 24
    """, (cutoff_time,))

    hourly_rows = cursor.fetchall()
    stats["hourly_request_rate"] = [
        {"hour": row[1], "count": row[0]}
        for row in hourly_rows
    ]

    # Calculate requests per minute (last hour)
    one_hour_ago = now - 3600
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM requests
        WHERE timestamp >= ?
    """, (one_hour_ago,))

    last_hour_count = cursor.fetchone()[0] or 0
    stats["request_rate"] = {
        "requests_per_hour_last_hour": last_hour_count,
        "requests_per_minute_last_hour": round(last_hour_count / 60, 2),
        "avg_requests_per_hour": round(total_requests / ((now - cutoff_time) / 3600), 2) if (now - cutoff_time) > 0 else 0
    }

    # ── 11. NOOP REASONS ───────────────────────────────────────────────
    cursor.execute("""
        SELECT
            noop_count,
            COUNT(*) as count
        FROM tasks
        WHERE timestamp >= ? AND noop_count > 0
        GROUP BY noop_count
        ORDER BY noop_count DESC
    """, (cutoff_time,))

    noop_rows = cursor.fetchall()
    stats["noop_distribution"] = [
        {"noop_count": row[0], "task_count": row[1]}
        for row in noop_rows
    ]

    # ── 12. CACHE ENTRY AGE DISTRIBUTION ────────────────────────────
    cursor.execute("""
        SELECT
            COUNT(*) as count,
            CASE
                WHEN created_at > ? THEN '0-7 days'
                WHEN created_at > ? THEN '7-30 days'
                WHEN created_at > ? THEN '30-90 days'
                ELSE '90+ days'
            END as age_bucket
        FROM cache_entries
        GROUP BY age_bucket
    """, (
        now - (7 * 24 * 3600),
        now - (30 * 24 * 3600),
        now - (90 * 24 * 3600)
    ))

    age_rows = cursor.fetchall()
    stats["cache_age_distribution"] = [
        {"bucket": row[1], "count": row[0]}
        for row in age_rows
    ]

    # ── 13. SUMMARY FOR RESUME ────────────────────────────────────────
    stats["resume_summary"] = {
        "cache_hit_rate_percent": stats["overall"]["cache_hit_rate_percent"],
        "avg_response_time_ms": stats["overall"]["avg_response_time_ms"],
        "time_saved_per_hit_percent": round((time_saved_per_hit_ms / avg_miss_time_ms) * 100, 2) if avg_miss_time_ms > 0 else 0,
        "cost_reduction_percent": stats["cost_savings"]["cost_reduction_percent"],
        "task_completion_rate_percent": stats["task_performance"]["task_completion_rate_percent"],
        "avg_task_time_minutes": stats["task_performance"]["avg_task_time_minutes"],
        "speedup_factor": stats["time_savings"]["speedup_factor"]
    }

    # ── 14. DETAILED BREAKDOWN (if requested) ────────────────────────
    if include_details:
        stats["details"] = {
            "recent_requests": _get_recent_requests(cursor, limit=50),
            "top_cache_entries": _get_top_cache_entries(cursor, limit=20),
            "failed_tasks": _get_failed_tasks(cursor, limit=20)
        }

    db_conn.close()

    return stats


def _get_recent_requests(cursor, limit=50):
    """Get recent requests with details"""
    cursor.execute("""
        SELECT
            timestamp,
            goal,
            cache_hit,
            response_time_ms,
            action,
            error
        FROM requests
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))

    return [
        {
            "timestamp": row[0],
            "goal": row[1],
            "cache_hit": bool(row[2]),
            "response_time_ms": row[3],
            "action": row[4],
            "error": row[5]
        }
        for row in cursor.fetchall()
    ]


def _get_top_cache_entries(cursor, limit=20):
    """Get most frequently hit cache entries"""
    cursor.execute("""
        SELECT
            cache_key,
            goal,
            hit_count,
            created_at,
            last_hit_at
        FROM cache_entries
        ORDER BY hit_count DESC
        LIMIT ?
    """, (limit,))

    now = time.time()
    return [
        {
            "cache_key": row[0],
            "goal": row[1],
            "hit_count": row[2],
            "age_days": round((now - row[3]) / (24 * 3600), 2),
            "last_hit_days_ago": round((now - row[4]) / (24 * 3600), 2) if row[4] else None
        }
        for row in cursor.fetchall()
    ]


def _get_failed_tasks(cursor, limit=20):
    """Get recently failed tasks"""
    cursor.execute("""
        SELECT
            timestamp,
            goal,
            total_steps,
            total_time_seconds,
            error_count
        FROM tasks
        WHERE completed = 0
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))

    return [
        {
            "timestamp": row[0],
            "goal": row[1],
            "total_steps": row[2],
            "total_time_seconds": row[3],
            "error_count": row[4]
        }
        for row in cursor.fetchall()
    ]


@app.post("/api/action", response_model=ActionResponse)
def get_action(request: ActionRequest):
    api_key = request.options.get("geminiKey")
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="GEMINI_API_KEY not set. Add it to backend/.env as GEMINI_API_KEY=your_key_here"
        )

    try:
        return run_pipeline(request, api_key)
    except Exception as e:
        import traceback
        print(f"ERROR in /api/action: {e}")
        print(f"Full traceback:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

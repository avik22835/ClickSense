# backend/stats_db.py
import sqlite3
import time

def init_stats_db(db_path="stats.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Request tracking (every request)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            goal TEXT NOT NULL,
            cache_hit BOOLEAN NOT NULL,
            cache_hit_age_days REAL,
            response_time_ms REAL NOT NULL,
            planning_time_ms REAL,
            grounding_time_ms,
            embedding_time_ms REAL,
            cache_lookup_time_ms REAL,
            action TEXT,
            element_count INTEGER,
            screenshot_size_kb REAL,
            error TEXT,
            user_id TEXT
        )
    """)

    # Cache entry tracking (every cache entry)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_entries (
            cache_key TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            page_context TEXT NOT NULL,
            created_at REAL NOT NULL,
            hit_count INTEGER DEFAULT 0,
            last_hit_at REAL,
            element_fingerprint TEXT NOT NULL,
            screenshot_dhash TEXT,
            response_size_bytes INTEGER
        )
    """)

    # Task tracking (every completed task)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            goal TEXT NOT NULL,
            total_steps INTEGER NOT NULL,
            total_time_seconds REAL NOT NULL,
            completed BOOLEAN NOT NULL,
            cache_hits INTEGER NOT NULL,
            cache_misses INTEGER NOT NULL,
            user_approvals INTEGER NOT NULL,
            user_rejections INTEGER NOT NULL,
            skips INTEGER NOT NULL,
            noop_count INTEGER NOT NULL,
            error_count INTEGER NOT NULL
        )
    """)

    # Daily aggregates (for faster queries)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            total_requests INTEGER DEFAULT 0,
            cache_hits INTEGER DEFAULT 0,
            cache_misses INTEGER DEFAULT 0,
            total_response_time_ms REAL DEFAULT 0,
            total_planning_time_ms REAL DEFAULT 0,
            total_grounding_time_ms REAL DEFAULT 0,
            total_embedding_time_ms REAL DEFAULT 0,
            total_cache_lookup_time_ms REAL DEFAULT 0,
            total_tasks_completed INTEGER DEFAULT 0,
            total_tasks_failed INTEGER DEFAULT 0,
            avg_steps_per_task REAL DEFAULT 0,
            avg_task_time_seconds REAL DEFAULT 0
        )
    """)

    # Indexes for faster queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_cache_hit ON requests(cache_hit)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_goal ON requests(goal)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_entries_created_at ON cache_entries(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_entries_hit_count ON cache_entries(hit_count)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_timestamp ON tasks(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_goal ON tasks(goal)")

    conn.commit()
    return conn


def log_request(
    db_conn,
    goal: str,
    cache_hit: bool,
    response_time_ms: float,
    planning_time_ms: float = None,
    grounding_time_ms: float = None,
    embedding_time_ms: float = None,
    cache_lookup_time_ms: float = None,
    action: str = None,
    element_count: int = None,
    screenshot_size_kb: float = None,
    error: str = None,
    user_id: str = None
):
    """Log a request to the stats database"""
    cursor = db_conn.cursor()

    cursor.execute("""
        INSERT INTO requests
        (timestamp, goal, cache_hit, response_time_ms, planning_time_ms,
         grounding_time_ms, embedding_time_ms, cache_lookup_time_ms,
         action, element_count, screenshot_size_kb, error, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        time.time(), goal, cache_hit, response_time_ms,
        planning_time_ms, grounding_time_ms, embedding_time_ms,
        cache_lookup_time_ms, action, element_count,
        screenshot_size_kb, error, user_id
    ))

    db_conn.commit()


def log_task(
    db_conn,
    goal: str,
    total_steps: int,
    total_time_seconds: float,
    completed: bool,
    cache_hits: int,
    cache_misses: int,
    user_approvals: int,
    user_rejections: int,
    skips: int,
    noop_count: int,
    error_count: int
):
    """Log a completed task to the stats database"""
    cursor = db_conn.cursor()

    cursor.execute("""
        INSERT INTO tasks
        (timestamp, goal, total_steps, total_time_seconds, completed,
         cache_hits, cache_misses, user_approvals, user_rejections,
         skips, noop_count, error_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        time.time(), goal, total_steps, total_time_seconds, completed,
        cache_hits, cache_misses, user_approvals, user_rejections,
        skips, noop_count, error_count
    ))

    db_conn.commit()


def log_cache_entry(
    db_conn,
    cache_key: str,
    goal: str,
    page_context: str,
    element_fingerprint: str,
    screenshot_dhash: str,
    response_size_bytes: int
):
    """Log a cache entry creation"""
    cursor = db_conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO cache_entries
        (cache_key, goal, page_context, created_at, hit_count, last_hit_at,
         element_fingerprint, screenshot_dhash, response_size_bytes)
        VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?)
    """, (
        cache_key, goal, page_context, time.time(),
        element_fingerprint, screenshot_dhash, response_size_bytes
    ))

    db_conn.commit()


def update_cache_hit(db_conn, cache_key: str):
    """Update cache entry hit count and last hit time"""
    cursor = db_conn.cursor()

    cursor.execute("""
        UPDATE cache_entries
        SET hit_count = hit_count + 1,
            last_hit_at = ?
        WHERE cache_key = ?
    """, (time.time(), cache_key))

    db_conn.commit()

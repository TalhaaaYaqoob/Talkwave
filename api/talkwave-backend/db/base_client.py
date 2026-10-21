import os
import ssl
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List

from loguru import logger
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import Pool

from api.constants import DATABASE_URL

DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))

# SSL is only needed for external databases (e.g. Supabase).
# Railway internal Postgres uses private networking — no SSL required.
_USE_SSL = os.getenv("DB_USE_SSL", "").lower() in ("1", "true", "yes") or "supabase" in DATABASE_URL.lower()

# Log the DATABASE_URL being used (masking password)
if "@" in DATABASE_URL:
    _at_index = DATABASE_URL.index("@")
    _prefix = DATABASE_URL[:_at_index]
    _suffix = DATABASE_URL[_at_index:]
    _last_colon = _prefix.rfind(":")
    _masked_url = _prefix[:_last_colon+1] + "***" + _suffix
else:
    _masked_url = DATABASE_URL
logger.info(f"BaseDBClient using DATABASE_URL: {_masked_url} (ssl={_USE_SSL})")

_connect_args: dict = {"prepared_statement_cache_size": 0}
if _USE_SSL:
    _ssl_context = ssl.create_default_context()
    _ssl_context.check_hostname = False
    _ssl_context.verify_mode = ssl.CERT_NONE
    _connect_args["ssl"] = _ssl_context

# Shared singleton engine — one connection pool for the entire application.
_shared_engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    connect_args=_connect_args,
)
_shared_session_factory = async_sessionmaker(
    bind=_shared_engine, class_=AsyncSession, expire_on_commit=False
)

logger.info(
    f"Shared DB engine created: pool_size={DB_POOL_SIZE}, "
    f"max_overflow={DB_MAX_OVERFLOW}, pool_timeout={DB_POOL_TIMEOUT}"
)


class BaseDBClient:
    def __init__(self):
        self.engine = _shared_engine
        self.async_session = _shared_session_factory

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get an async database session as a context manager."""
        async with self.async_session() as session:
            yield session

    async def execute_raw_query(
        self, query: str, params: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a raw SQL query and return results as a list of dictionaries.

        Args:
            query: The SQL query to execute
            params: Optional dictionary of query parameters

        Returns:
            List of dictionaries containing the query results
        """
        async with self.async_session() as session:
            result = await session.execute(text(query), params or {})
            rows = result.fetchall()
            if rows:
                # Convert rows to dictionaries
                columns = result.keys()
                return [dict(zip(columns, row)) for row in rows]
            return []

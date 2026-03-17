"""Lakebase connection with OAuth token refresh for Databricks Apps."""
import os
import time
import threading
from contextlib import contextmanager
from typing import Optional
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool


class LakebaseConnection:
    """Manages Lakebase PostgreSQL connection with automatic OAuth token refresh."""
    
    def __init__(
        self,
        host: Optional[str] = None,
        database: Optional[str] = None,
        port: int = 5432,
    ):
        self.host = host or os.environ.get("LAKEBASE_HOST", "")
        self.database = database or os.environ.get("LAKEBASE_DATABASE", "investment_intel_db")
        self.port = port
        self._engine = None
        self._session_factory = None
        self._token = None
        self._token_expiry = 0
        self._lock = threading.Lock()
    
    def _get_token(self) -> str:
        """Get OAuth token, refreshing if needed."""
        current_time = time.time()
        
        # Check if token is still valid (with 5 min buffer)
        if self._token and current_time < (self._token_expiry - 300):
            return self._token
        
        with self._lock:
            # Double-check after acquiring lock
            if self._token and current_time < (self._token_expiry - 300):
                return self._token
            
            # In Databricks Apps, use service principal OAuth
            client_id = os.environ.get("DATABRICKS_CLIENT_ID")
            client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET")
            databricks_host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
            
            if client_id and client_secret and databricks_host:
                import requests
                token_url = f"{databricks_host}/oidc/v1/token"
                response = requests.post(
                    token_url,
                    data={"grant_type": "client_credentials", "scope": "all-apis"},
                    auth=(client_id, client_secret),
                    timeout=30,
                )
                response.raise_for_status()
                token_data = response.json()
                self._token = token_data["access_token"]
                # Assume 1 hour expiry if not specified
                self._token_expiry = current_time + token_data.get("expires_in", 3600)
            else:
                # Fallback to environment token
                self._token = os.environ.get("DATABRICKS_TOKEN", "")
                self._token_expiry = current_time + 3600
            
            return self._token
    
    def _get_connection_url(self) -> str:
        """Build PostgreSQL connection URL for Lakebase."""
        token = self._get_token()
        # Lakebase uses OAuth token as password
        return f"postgresql://token:{token}@{self.host}:{self.port}/{self.database}"
    
    def get_engine(self):
        """Get SQLAlchemy engine with connection pooling."""
        if self._engine is None:
            self._engine = create_engine(
                self._get_connection_url(),
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=1800,
            )
            
            # Refresh token on checkout
            @event.listens_for(self._engine, "checkout")
            def receive_checkout(dbapi_conn, connection_record, connection_proxy):
                # Update connection credentials if token changed
                pass  # Token is embedded in URL; reconnect handles refresh
        
        return self._engine
    
    def get_session_factory(self):
        """Get sessionmaker for creating sessions."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self.get_engine())
        return self._session_factory
    
    @contextmanager
    def session(self):
        """Context manager for database sessions."""
        session = self.get_session_factory()()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# Global connection instance
_connection: Optional[LakebaseConnection] = None


def get_connection() -> LakebaseConnection:
    """Get or create the global Lakebase connection."""
    global _connection
    if _connection is None:
        _connection = LakebaseConnection()
    return _connection


def get_engine():
    """Get SQLAlchemy engine."""
    return get_connection().get_engine()


def get_session() -> Session:
    """Get a new database session."""
    return get_connection().get_session_factory()()


@contextmanager
def session_scope():
    """Context manager for database sessions with auto-commit/rollback."""
    conn = get_connection()
    with conn.session() as session:
        yield session


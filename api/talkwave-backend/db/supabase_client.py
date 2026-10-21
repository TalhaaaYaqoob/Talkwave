"""
Supabase Client
Provides a singleton Supabase client for direct API access (storage, auth, realtime, etc.)
"""

from supabase import create_client, Client

from api.constants import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

# Singleton Supabase client instance
_supabase_client: Client | None = None


def get_supabase_client() -> Client:
    """
    Get or create the Supabase client instance.
    Uses the service role key for full access to all Supabase features.
    
    Returns:
        Supabase Client instance
    """
    global _supabase_client
    
    if _supabase_client is None:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    
    return _supabase_client


# Convenience alias
supabase = get_supabase_client




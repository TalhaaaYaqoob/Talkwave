from loguru import logger

from api.constants import (
    ENABLE_AWS_S3,
    S3_BUCKET,
    S3_REGION,
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_STORAGE_BUCKET,
)
from api.enums import StorageBackend

from .filesystem import BaseFileSystem, S3FileSystem, SupabaseFileSystem


def get_storage_for_backend(backend: str) -> BaseFileSystem:
    """Get storage instance for a specific backend enum.

    Maps StorageBackend enum codes to actual storage implementations:
    - SUPABASE: Supabase Storage via SupabaseFileSystem (default)
    - S3: AWS S3 via S3FileSystem
    """
    # Supabase Storage implementation (default and recommended)
    if backend == StorageBackend.SUPABASE.value:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are required when using Supabase storage"
            )
        bucket = SUPABASE_STORAGE_BUCKET
        logger.info(
            f"Initializing {backend} storage with bucket '{bucket}' at {SUPABASE_URL}"
        )
        return SupabaseFileSystem(
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_SERVICE_ROLE_KEY,
            bucket_name=bucket,
        )

    # AWS S3 implementation (cloud deployments)
    elif backend == StorageBackend.S3.value:
        if not S3_BUCKET:
            raise ValueError(
                "S3_BUCKET environment variable is required when using S3 storage"
            )
        bucket = S3_BUCKET
        region = S3_REGION
        logger.info(
            f"Initializing {backend} storage with bucket '{bucket}' in region '{region}'"
        )
        return S3FileSystem(bucket, region)

    else:
        raise ValueError(f"Unknown storage backend: {backend}. Use 'supabase' or 's3'.")


def get_current_storage_backend() -> StorageBackend:
    """Get the current storage backend enum."""
    return StorageBackend.get_current_backend()


# Create a single storage instance at module load time
_backend = StorageBackend.get_current_backend()
logger.info(
    f"Initializing storage backend: {_backend.name} (value: {_backend.value}, ENABLE_AWS_S3={ENABLE_AWS_S3})"
)
storage_fs = get_storage_for_backend(_backend.value)


# For backward compatibility, keep get_storage() function
def get_storage() -> BaseFileSystem:
    """Get the module-level storage instance.

    Deprecated: Use 'from api.services.storage import storage_fs' instead.
    """
    return storage_fs

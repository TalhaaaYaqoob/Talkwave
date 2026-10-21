"""
Supabase Storage implementation using the Supabase Storage API.

Supabase provides S3-compatible storage. This implementation uses the
supabase-py client for direct storage operations.
"""

import os
from typing import Any, BinaryIO, Dict, Optional

from loguru import logger

from .base import BaseFileSystem


class SupabaseFileSystem(BaseFileSystem):
    """
    File system implementation using Supabase Storage.
    
    Uses the Supabase Storage REST API via the supabase-py client.
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        bucket_name: str = "voice-audio",
    ):
        """
        Initialize Supabase storage.
        
        Args:
            supabase_url: Supabase project URL (e.g., https://xxx.supabase.co)
            supabase_key: Supabase service role key (for server-side access)
            bucket_name: Storage bucket name (default: voice-audio)
        """
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.bucket_name = bucket_name
        
        try:
            from supabase import create_client
            self.client = create_client(supabase_url, supabase_key)
            self._ensure_bucket_exists()
            logger.info(f"Supabase storage initialized with bucket '{bucket_name}'")
        except ImportError:
            logger.error("supabase-py not installed. Install with: pip install supabase")
            raise
        except Exception as e:
            logger.warning(f"Supabase storage initialization note: {e}")
            # Don't fail startup - bucket might already exist or we may not have permissions
            # to list buckets, but we might still be able to upload
    
    def _ensure_bucket_exists(self):
        """Create bucket if it doesn't exist."""
        try:
            # Try to get bucket info
            buckets = self.client.storage.list_buckets()
            bucket_names = [b.name for b in buckets]
            
            if self.bucket_name not in bucket_names:
                # Create the bucket (public for audio playback)
                self.client.storage.create_bucket(
                    self.bucket_name,
                    options={"public": True}
                )
                logger.info(f"Created Supabase storage bucket: {self.bucket_name}")
        except Exception as e:
            logger.debug(f"Bucket check/creation note: {e}")

    async def acreate_file(self, file_path: str, content: BinaryIO) -> bool:
        """
        Create a new file with the given content.
        
        Args:
            file_path: Path where the file should be created
            content: File content as a binary stream
            
        Returns:
            bool: True if file was created successfully, False otherwise
        """
        try:
            file_content = content.read()
            
            # Determine content type from extension
            content_type = self._get_content_type(file_path)
            
            file_options = {}
            if content_type:
                file_options["content-type"] = content_type
            
            self.client.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=file_content,
                file_options=file_options
            )
            
            logger.debug(f"Created file in Supabase: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create file in Supabase Storage: {e}")
            return False

    async def aupload_file(self, local_path: str, destination_path: str) -> bool:
        """
        Upload a file from local path to destination.
        
        Args:
            local_path: Path to the local file
            destination_path: Path where the file should be uploaded
            
        Returns:
            bool: True if file was uploaded successfully, False otherwise
        """
        try:
            with open(local_path, 'rb') as f:
                file_content = f.read()
            
            # Determine content type from extension
            content_type = self._get_content_type(destination_path)
            
            file_options = {}
            if content_type:
                file_options["content-type"] = content_type
            
            self.client.storage.from_(self.bucket_name).upload(
                path=destination_path,
                file=file_content,
                file_options=file_options
            )
            
            logger.debug(f"Uploaded to Supabase: {local_path} -> {destination_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload to Supabase Storage: {e}")
            return False

    async def aget_signed_url(
        self,
        file_path: str,
        expiration: int = 3600,
        force_inline: bool = False,
        use_internal_endpoint: bool = False,
    ) -> Optional[str]:
        """
        Generate a signed URL for temporary access to a file.
        
        Args:
            file_path: Path to the file
            expiration: URL expiration time in seconds (default: 1 hour)
            force_inline: Force inline display (browser preview vs download)
            use_internal_endpoint: Use internal endpoint (not used for Supabase)
            
        Returns:
            Optional[str]: Signed URL if successful, None otherwise
        """
        try:
            # Try public URL first (for public buckets - faster)
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(file_path)
            
            # Verify the file exists by trying to get a signed URL
            # If the bucket is private, we need a signed URL anyway
            try:
                signed_result = self.client.storage.from_(self.bucket_name).create_signed_url(
                    file_path, expiration
                )
                signed_url = signed_result.get("signedURL") or signed_result.get("signedUrl")
                if signed_url:
                    return signed_url
            except Exception:
                pass
            
            # Fall back to public URL
            return public_url
            
        except Exception as e:
            logger.error(f"Failed to get signed URL from Supabase Storage: {e}")
            return None

    async def aget_file_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Optional[Dict[str, Any]]: File metadata if successful, None otherwise
        """
        try:
            # Extract folder and filename
            folder = os.path.dirname(file_path)
            filename = os.path.basename(file_path)
            
            # List files in the directory
            files = self.client.storage.from_(self.bucket_name).list(folder)
            
            # Find the specific file
            for f in files:
                if f.get("name") == filename:
                    return {
                        "size": f.get("metadata", {}).get("size"),
                        "created_at": f.get("created_at"),
                        "updated_at": f.get("updated_at"),
                        "etag": f.get("metadata", {}).get("eTag"),
                        "content_type": f.get("metadata", {}).get("mimetype"),
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get file metadata from Supabase Storage: {e}")
            return None

    async def aget_presigned_put_url(
        self,
        file_path: str,
        expiration: int = 900,
        content_type: str = "text/csv",
        max_size: int = 10_485_760,
    ) -> Optional[str]:
        """
        Generate a presigned PUT URL for direct file upload.
        
        Note: Supabase Storage doesn't support presigned PUT URLs in the same way
        as S3. This method returns a signed URL that can be used with the Supabase
        client for uploads.
        
        Args:
            file_path: Path where the file should be uploaded
            expiration: URL expiration time in seconds (default: 15 minutes)
            content_type: MIME type of the file (default: text/csv)
            max_size: Maximum file size in bytes (default: 10MB)
            
        Returns:
            Optional[str]: Signed upload URL if successful, None otherwise
        """
        try:
            # Supabase uses a different approach - we create a signed upload URL
            result = self.client.storage.from_(self.bucket_name).create_signed_upload_url(file_path)
            return result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
        except Exception as e:
            logger.error(f"Failed to get presigned PUT URL from Supabase Storage: {e}")
            # Fall back to providing the storage endpoint
            return f"{self.supabase_url}/storage/v1/object/{self.bucket_name}/{file_path}"

    def _get_content_type(self, file_path: str) -> Optional[str]:
        """Get content type based on file extension."""
        ext = os.path.splitext(file_path)[1].lower()
        content_types = {
            '.wav': 'audio/wav',
            '.mp3': 'audio/mpeg',
            '.ogg': 'audio/ogg',
            '.webm': 'audio/webm',
            '.txt': 'text/plain',
            '.csv': 'text/csv',
            '.json': 'application/json',
            '.pdf': 'application/pdf',
        }
        return content_types.get(ext)

    # Legacy sync methods for backward compatibility
    def upload(
        self,
        file: BinaryIO,
        path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Upload a file to Supabase Storage (sync wrapper).
        
        Args:
            file: File-like object to upload
            path: Path/key in the bucket
            content_type: MIME type of the file
            
        Returns:
            Public URL of the uploaded file
        """
        try:
            file_content = file.read()
            
            file_options = {}
            if content_type:
                file_options["content-type"] = content_type
            
            self.client.storage.from_(self.bucket_name).upload(
                path=path,
                file=file_content,
                file_options=file_options
            )
            
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(path)
            logger.debug(f"Uploaded to Supabase: {path}")
            return public_url
            
        except Exception as e:
            logger.error(f"Failed to upload to Supabase Storage: {e}")
            raise

    def download(self, path: str) -> bytes:
        """Download a file from Supabase Storage."""
        try:
            response = self.client.storage.from_(self.bucket_name).download(path)
            return response
        except Exception as e:
            logger.error(f"Failed to download from Supabase Storage: {e}")
            raise

    def delete(self, path: str) -> bool:
        """Delete a file from Supabase Storage."""
        try:
            self.client.storage.from_(self.bucket_name).remove([path])
            logger.debug(f"Deleted from Supabase: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete from Supabase Storage: {e}")
            return False

    def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get a URL for a file."""
        try:
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(path)
            return public_url
        except Exception as e:
            logger.error(f"Failed to get URL from Supabase Storage: {e}")
            raise

    def exists(self, path: str) -> bool:
        """Check if a file exists in Supabase Storage."""
        try:
            folder = os.path.dirname(path)
            filename = os.path.basename(path)
            files = self.client.storage.from_(self.bucket_name).list(folder)
            return any(f.get("name") == filename for f in files)
        except Exception:
            return False

    def list_files(self, prefix: str = "") -> list:
        """List files in Supabase Storage with optional prefix."""
        try:
            files = self.client.storage.from_(self.bucket_name).list(prefix)
            return [f.get("name") for f in files if f.get("name")]
        except Exception as e:
            logger.error(f"Failed to list files from Supabase Storage: {e}")
            return []

"""
Input Validation and Sanitization Utilities.

This module provides functions to validate and sanitize user input
to prevent injection attacks and data corruption.
"""

import re
import html
from typing import Optional
from urllib.parse import urlparse


def sanitize_string(
    value: str,
    max_length: int = 10000,
    strip_html: bool = True,
    strip_null_bytes: bool = True,
) -> str:
    """
    Sanitize a string input by removing potentially dangerous content.
    
    Args:
        value: The string to sanitize
        max_length: Maximum allowed length (truncates if exceeded)
        strip_html: Whether to escape HTML entities
        strip_null_bytes: Whether to remove null bytes
    
    Returns:
        Sanitized string
    """
    if not value:
        return value
    
    # Truncate to max length
    if len(value) > max_length:
        value = value[:max_length]
    
    # Remove null bytes (common injection technique)
    if strip_null_bytes:
        value = value.replace("\x00", "")
    
    # Escape HTML entities to prevent XSS
    if strip_html:
        value = html.escape(value)
    
    return value


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent path traversal attacks.
    
    Args:
        filename: The filename to sanitize
    
    Returns:
        Sanitized filename safe for filesystem operations
    """
    if not filename:
        return "unnamed"
    
    # Remove path separators and null bytes
    filename = filename.replace("/", "_").replace("\\", "_").replace("\x00", "")
    
    # Remove or replace other potentially dangerous characters
    # Allow only alphanumeric, dash, underscore, dot
    filename = re.sub(r'[^\w\-.]', '_', filename)
    
    # Prevent hidden files (starting with dot)
    if filename.startswith("."):
        filename = "_" + filename[1:]
    
    # Limit length
    if len(filename) > 255:
        # Preserve extension if possible
        if "." in filename:
            name, ext = filename.rsplit(".", 1)
            filename = name[:255-len(ext)-1] + "." + ext
        else:
            filename = filename[:255]
    
    return filename or "unnamed"


def validate_phone_number(phone: str) -> tuple[bool, str]:
    """
    Validate and normalize a phone number.
    
    Args:
        phone: Phone number to validate
    
    Returns:
        Tuple of (is_valid, normalized_phone_or_error)
    """
    if not phone:
        return False, "Phone number is required"
    
    # Remove common formatting characters
    cleaned = re.sub(r'[\s\-\.\(\)]', '', phone)
    
    # Must start with + or be numeric
    if not cleaned.startswith('+') and not cleaned.isdigit():
        return False, "Phone number must contain only digits and optional + prefix"
    
    # Add + if not present and looks like international
    if cleaned.isdigit() and len(cleaned) > 10:
        cleaned = '+' + cleaned
    
    # Check length (E.164 format: 8-15 digits after +)
    digits_only = cleaned.lstrip('+')
    if not digits_only.isdigit():
        return False, "Phone number must contain only digits after + prefix"
    
    if len(digits_only) < 7 or len(digits_only) > 15:
        return False, "Phone number must be between 7 and 15 digits"
    
    return True, cleaned


def validate_url(
    url: str,
    allowed_schemes: tuple = ("http", "https"),
    allow_localhost: bool = False,
) -> tuple[bool, str]:
    """
    Validate a URL for safety.
    
    Args:
        url: URL to validate
        allowed_schemes: Tuple of allowed URL schemes
        allow_localhost: Whether to allow localhost URLs
    
    Returns:
        Tuple of (is_valid, url_or_error_message)
    """
    if not url:
        return False, "URL is required"
    
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"
    
    # Check scheme
    if parsed.scheme not in allowed_schemes:
        return False, f"URL scheme must be one of: {', '.join(allowed_schemes)}"
    
    # Check for host
    if not parsed.netloc:
        return False, "URL must have a host"
    
    # Check for localhost (can be a security risk in some contexts)
    if not allow_localhost:
        localhost_patterns = ('localhost', '127.0.0.1', '::1', '0.0.0.0')
        host = parsed.netloc.split(':')[0].lower()
        if any(host == pattern or host.endswith('.' + pattern) for pattern in localhost_patterns):
            return False, "Localhost URLs are not allowed"
    
    # Prevent SSRF with private IP ranges (basic check)
    host = parsed.netloc.split(':')[0]
    private_patterns = [
        r'^10\.',
        r'^172\.(1[6-9]|2[0-9]|3[01])\.',
        r'^192\.168\.',
        r'^169\.254\.',
    ]
    for pattern in private_patterns:
        if re.match(pattern, host):
            return False, "Private IP addresses are not allowed"
    
    return True, url


def validate_json_depth(obj, max_depth: int = 10, current_depth: int = 0) -> bool:
    """
    Validate that a JSON object doesn't exceed maximum nesting depth.
    
    This prevents stack overflow attacks via deeply nested JSON.
    
    Args:
        obj: The object to check
        max_depth: Maximum allowed nesting depth
        current_depth: Current depth (used internally)
    
    Returns:
        True if valid, False if too deep
    """
    if current_depth > max_depth:
        return False
    
    if isinstance(obj, dict):
        for value in obj.values():
            if not validate_json_depth(value, max_depth, current_depth + 1):
                return False
    elif isinstance(obj, list):
        for item in obj:
            if not validate_json_depth(item, max_depth, current_depth + 1):
                return False
    
    return True


def validate_email(email: str) -> tuple[bool, str]:
    """
    Validate an email address format.
    
    Args:
        email: Email address to validate
    
    Returns:
        Tuple of (is_valid, email_or_error_message)
    """
    if not email:
        return False, "Email is required"
    
    # Basic email regex (RFC 5322 simplified)
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, "Invalid email format"
    
    # Check length
    if len(email) > 254:
        return False, "Email too long"
    
    # Check local part length
    local_part = email.split('@')[0]
    if len(local_part) > 64:
        return False, "Email local part too long"
    
    return True, email.lower()


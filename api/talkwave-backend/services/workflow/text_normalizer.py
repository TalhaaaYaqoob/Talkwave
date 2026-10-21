"""
Text Normalizer for STT Output.
Converts common spoken patterns to their written equivalents.
"""

import re
from typing import List, Tuple


# Common spoken patterns to normalize
NORMALIZATION_PATTERNS: List[Tuple[str, str]] = [
    # Email patterns
    (r"\bat the rate of\b", "@"),
    (r"\bat the rate\b", "@"),
    (r"\bat sign\b", "@"),
    (r"\bat symbol\b", "@"),
    (r"\bthe at symbol\b", "@"),
    (r"\bthe at sign\b", "@"),
    (r"\bdot com\b", ".com"),
    (r"\bdot org\b", ".org"),
    (r"\bdot net\b", ".net"),
    (r"\bdot io\b", ".io"),
    (r"\bdot co\b", ".co"),
    (r"\bdot edu\b", ".edu"),
    (r"\bdot gov\b", ".gov"),
    # Phone patterns
    (r"\bdouble (\d)\b", r"\1\1"),
    (r"\btriple (\d)\b", r"\1\1\1"),
    # Common abbreviations
    (r"\bnumber\b", "#"),
    (r"\bdollar sign\b", "$"),
    (r"\bpercent sign\b", "%"),
    (r"\bampersand\b", "&"),
    (r"\basterisk\b", "*"),
    (r"\bhash\b", "#"),
    (r"\bhashtag\b", "#"),
    (r"\bpound sign\b", "#"),
    (r"\bunderscore\b", "_"),
    (r"\bdash\b", "-"),
    (r"\bhyphen\b", "-"),
    # Numbers (spelled out to digits for phone/date contexts)
    (r"\bzero\b", "0"),
    (r"\bone\b", "1"),
    (r"\btwo\b", "2"),
    (r"\bthree\b", "3"),
    (r"\bfour\b", "4"),
    (r"\bfive\b", "5"),
    (r"\bsix\b", "6"),
    (r"\bseven\b", "7"),
    (r"\beight\b", "8"),
    (r"\bnine\b", "9"),
]


def normalize_transcript(text: str, patterns: List[Tuple[str, str]] = None) -> str:
    """
    Normalize STT transcription text by converting common spoken patterns.
    
    Args:
        text: The transcribed text to normalize
        patterns: Optional custom patterns to use (defaults to NORMALIZATION_PATTERNS)
        
    Returns:
        Normalized text with spoken patterns converted to written form
    """
    if not text:
        return text
    
    if patterns is None:
        patterns = NORMALIZATION_PATTERNS
    
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # Clean up any resulting multiple spaces
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result


def normalize_email(text: str) -> str:
    """
    Specifically normalize email-related transcription patterns.
    
    Example: "jane doe at the rate of example dot com" → "janedoe@example.com"
    """
    email_patterns = [
        (r"\bat the rate of\b", "@"),
        (r"\bat the rate\b", "@"),
        (r"\bat sign\b", "@"),
        (r"\bat symbol\b", "@"),
        (r"\bthe at symbol\b", "@"),
        (r"\bthe at sign\b", "@"),
        (r"\bdot com\b", ".com"),
        (r"\bdot org\b", ".org"),
        (r"\bdot net\b", ".net"),
        (r"\bdot io\b", ".io"),
        (r"\bdot co\b", ".co"),
        (r"\bdot edu\b", ".edu"),
        (r"\bdot gov\b", ".gov"),
        (r"\bdot gmail\b", ".gmail"),
        (r"\bgmail dot com\b", "gmail.com"),
        (r"\byahoo dot com\b", "yahoo.com"),
        (r"\boutlook dot com\b", "outlook.com"),
        (r"\bhotmail dot com\b", "hotmail.com"),
    ]
    
    result = text
    for pattern, replacement in email_patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # Remove spaces around @ and dots in email context
    result = re.sub(r'\s*@\s*', '@', result)
    result = re.sub(r'\s*\.\s*(?=com|org|net|io|co|edu|gov)', '.', result)
    
    return result


def normalize_phone_number(text: str) -> str:
    """
    Specifically normalize phone number transcription patterns.
    
    Example: "nine seven two five zero three nine two" → "97250392"
    """
    phone_patterns = [
        (r"\bzero\b", "0"),
        (r"\bone\b", "1"),
        (r"\btwo\b", "2"),
        (r"\bthree\b", "3"),
        (r"\bfour\b", "4"),
        (r"\bfive\b", "5"),
        (r"\bsix\b", "6"),
        (r"\bseven\b", "7"),
        (r"\beight\b", "8"),
        (r"\bnine\b", "9"),
        (r"\bdouble (\d)\b", r"\1\1"),
        (r"\btriple (\d)\b", r"\1\1\1"),
    ]
    
    result = text
    for pattern, replacement in phone_patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # Remove spaces between consecutive digits
    result = re.sub(r'(\d)\s+(\d)', r'\1\2', result)
    
    return result


# Convenience function for use in pipecat engine
def post_process_transcription(text: str) -> str:
    """
    Full post-processing pipeline for STT transcriptions.
    Normalizes common spoken patterns to their written equivalents.
    """
    return normalize_transcript(text)


"""
Knowledge Base API Routes

Endpoints for managing knowledge base documents and chunks.
"""

import io
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from loguru import logger
from pydantic import BaseModel, Field

from api.db.knowledge_base_client import knowledge_base_client
from api.services.auth.depends import get_user

# Document processing imports - supports DOCX and Excel files
try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    logger.warning("python-docx not installed, DOCX support disabled")

try:
    from openpyxl import load_workbook
    XLSX_AVAILABLE = True
except ImportError:
    XLSX_AVAILABLE = False
    logger.warning("openpyxl not installed, Excel support disabled")


router = APIRouter(prefix="/knowledge-base", tags=["knowledge-base"])


# =============================================================================
# Pydantic Models
# =============================================================================


class DocumentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    description: Optional[str] = None
    file_type: str = Field(default="txt", pattern="^(txt|md|pdf|docx|xlsx|xls)$")
    workflow_id: Optional[int] = None


class DocumentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DocumentContentUpdate(BaseModel):
    content: str = Field(..., min_length=1)


class DocumentResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    file_type: str
    file_size_bytes: Optional[int]
    chunk_count: int
    is_active: bool
    processing_status: str
    processing_error: Optional[str]
    created_at: str
    updated_at: str
    workflow_id: Optional[int] = None

    class Config:
        from_attributes = True


class DocumentContentResponse(BaseModel):
    id: int
    name: str
    content: str
    file_type: str
    chunk_count: int

    class Config:
        from_attributes = True


class ChunkResponse(BaseModel):
    id: int
    chunk_index: int
    content: str
    token_count: Optional[int]

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=10)


class SearchResultResponse(BaseModel):
    chunks: List[ChunkResponse]
    total: int


# =============================================================================
# Helper Functions
# =============================================================================


def extract_text_from_docx(content: bytes) -> str:
    """Extract text from a DOCX file."""
    if not DOCX_AVAILABLE:
        raise ValueError("python-docx not installed, cannot process DOCX files")
    
    doc = DocxDocument(io.BytesIO(content))
    paragraphs = []
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)
    
    # Also extract text from tables
    for table in doc.tables:
        for row in table.rows:
            row_text = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    row_text.append(cell_text)
            if row_text:
                paragraphs.append(" | ".join(row_text))
    
    return "\n\n".join(paragraphs)


def extract_text_from_xlsx(content: bytes) -> str:
    """Extract text from an Excel file."""
    if not XLSX_AVAILABLE:
        raise ValueError("openpyxl not installed, cannot process Excel files")
    
    workbook = load_workbook(io.BytesIO(content), data_only=True)
    all_text = []
    
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        sheet_text = [f"=== Sheet: {sheet_name} ==="]
        
        for row in sheet.iter_rows():
            row_values = []
            for cell in row:
                if cell.value is not None:
                    row_values.append(str(cell.value))
            if row_values:
                sheet_text.append(" | ".join(row_values))
        
        if len(sheet_text) > 1:  # More than just the header
            all_text.append("\n".join(sheet_text))
    
    return "\n\n".join(all_text)


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> List[dict]:
    """
    Split text into overlapping chunks.
    
    Args:
        text: The text to chunk
        chunk_size: Target size of each chunk in characters
        overlap: Number of characters to overlap between chunks
    
    Returns:
        List of chunk dictionaries with content and token estimates
    """
    chunks = []
    
    # Clean the text
    text = text.strip()
    if not text:
        return chunks
    
    # Split by paragraphs first
    paragraphs = re.split(r'\n\s*\n', text)
    
    current_chunk = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        # If adding this paragraph would exceed chunk size
        if len(current_chunk) + len(para) + 2 > chunk_size:
            if current_chunk:
                chunks.append({
                    "content": current_chunk.strip(),
                    "token_count": len(current_chunk.split()) * 4 // 3,  # Rough estimate
                })
            
            # Start new chunk with overlap from previous
            if current_chunk and overlap > 0:
                # Get last N characters for overlap
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
    
    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            "content": current_chunk.strip(),
            "token_count": len(current_chunk.split()) * 4 // 3,
        })
    
    return chunks


# Section header patterns for intelligent splitting
_SECTION_HEADER_RE = re.compile(
    r"^(?:"
    r"#{1,6}\s+"                         # Markdown headers: # … ######
    r"|[A-Z][A-Z0-9 .:/\-]{2,80}$"      # ALL-CAPS lines (common PDF headings)
    r"|\d+(?:\.\d+)*\s+[A-Z]"           # Numbered sections: 1.2 Foo
    r"|(?:Chapter|Section|Part|Article)\s+\d+"  # Explicit section labels
    r")",
    re.MULTILINE,
)


def chunk_text_for_retrieval(
    text: str,
    document_name: str = "",
    chunk_size: int = 2000,
    overlap: int = 200,
) -> List[dict]:
    """Split text into retrieval-optimized overlapping chunks.

    Designed for semantic search over very large documents (thousands of pages).
    Each chunk:
      - is ~512 tokens / 2000 chars (configurable)
      - respects section boundaries (markdown headers, numbered sections, ALL-CAPS headings)
      - carries a document-title prefix so it is self-contained when embedded
      - has a generous overlap (200 chars) to avoid losing info at boundaries

    Args:
        text: The raw document text.
        document_name: Document title — prepended to every chunk so embeddings carry context.
        chunk_size: Target chunk size in **characters** (~512 tokens).
        overlap: Number of overlap characters between consecutive chunks.

    Returns:
        List of dicts with ``content`` and ``token_count`` keys.
    """
    text = text.strip()
    if not text:
        return []

    prefix = f"[From: {document_name}]\n" if document_name else ""

    # --- 1. Split into sections (at headers / double-newlines) ---
    # We try to split at section headers first; paragraphs are the fallback unit.
    sections: List[str] = []
    last_end = 0
    for m in _SECTION_HEADER_RE.finditer(text):
        start = m.start()
        if start > last_end:
            sections.append(text[last_end:start])
        last_end = start
    if last_end < len(text):
        sections.append(text[last_end:])

    # Flatten sections into paragraphs (split on blank lines within each section)
    paragraphs: List[str] = []
    for section in sections:
        for para in re.split(r'\n\s*\n', section):
            para = para.strip()
            if para:
                paragraphs.append(para)

    # --- 2. Build chunks from paragraphs ---
    # The effective content budget per chunk (minus the prefix)
    budget = max(chunk_size - len(prefix), 400)

    chunks: List[dict] = []
    current_chunk = ""
    for para in paragraphs:
        # If a single paragraph exceeds the budget, hard-split it
        if len(para) > budget:
            # Flush whatever is accumulated first
            if current_chunk:
                full_content = (prefix + current_chunk.strip()) if prefix else current_chunk.strip()
                chunks.append({
                    "content": full_content,
                    "token_count": len(full_content.split()) * 4 // 3,
                })
                current_chunk = ""

            # Hard-split the oversized paragraph at sentence / word boundaries
            remaining = para
            while remaining:
                piece = remaining[:budget]
                # Try to break at a sentence boundary
                last_period = piece.rfind('. ')
                if last_period > budget * 0.5:
                    piece = piece[:last_period + 1]
                else:
                    # Fall back to word boundary
                    last_space = piece.rfind(' ')
                    if last_space > budget * 0.5:
                        piece = piece[:last_space]

                full_content = (prefix + piece.strip()) if prefix else piece.strip()
                chunks.append({
                    "content": full_content,
                    "token_count": len(full_content.split()) * 4 // 3,
                })
                remaining = remaining[len(piece):].strip()
                # Add overlap from the tail of the emitted piece
                if remaining and overlap > 0:
                    overlap_text = piece[-overlap:] if len(piece) > overlap else piece
                    remaining = overlap_text.strip() + " " + remaining
            continue

        # Normal accumulation
        if len(current_chunk) + len(para) + 2 > budget:
            if current_chunk:
                full_content = (prefix + current_chunk.strip()) if prefix else current_chunk.strip()
                chunks.append({
                    "content": full_content,
                    "token_count": len(full_content.split()) * 4 // 3,
                })
            # Start new chunk with overlap from previous
            if current_chunk and overlap > 0:
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    # Flush remaining
    if current_chunk.strip():
        full_content = (prefix + current_chunk.strip()) if prefix else current_chunk.strip()
        chunks.append({
            "content": full_content,
            "token_count": len(full_content.split()) * 4 // 3,
        })

    return chunks


# =============================================================================
# Routes
# =============================================================================


@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    active_only: bool = True,
    workflow_id: Optional[int] = None,
    user=Depends(get_user),
):
    """List knowledge base documents, optionally scoped to a workflow."""
    documents = await knowledge_base_client.get_documents_by_organization(
        organization_id=user.selected_organization_id,
        active_only=active_only,
        workflow_id=workflow_id,
    )
    return [
        DocumentResponse(
            id=doc.id,
            name=doc.name,
            description=doc.description,
            file_type=doc.file_type,
            file_size_bytes=doc.file_size_bytes,
            chunk_count=doc.chunk_count,
            is_active=doc.is_active,
            processing_status=doc.processing_status,
            processing_error=doc.processing_error,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat() if doc.updated_at else doc.created_at.isoformat(),
            workflow_id=doc.workflow_id,
        )
        for doc in documents
    ]


@router.post("/documents", response_model=DocumentResponse)
async def create_document(
    document: DocumentCreate,
    user=Depends(get_user),
):
    """Create a new knowledge base document from text content."""
    try:
        doc = await knowledge_base_client.create_document(
            organization_id=user.selected_organization_id,
            name=document.name,
            content=document.content,
            file_type=document.file_type,
            description=document.description,
            file_size_bytes=len(document.content.encode('utf-8')),
            created_by=user.id,
            workflow_id=document.workflow_id,
        )
        
        # Use retrieval-optimized chunking for large docs, basic for small
        content_len = len(document.content)
        if content_len > 15000:
            chunks = chunk_text_for_retrieval(
                document.content,
                document_name=document.name,
                chunk_size=2000,
                overlap=200,
            )
        else:
            chunks = chunk_text(document.content)
        
        if chunks:
            created_chunks = await knowledge_base_client.create_chunks(doc.id, chunks)
            await knowledge_base_client.update_document(
                doc.id,
                processing_status="completed",
                chunk_count=len(chunks),
            )
            # Pre-compute embeddings in the background (non-blocking, best-effort)
            try:
                from api.services.workflow.knowledge_base_retrieval import embed_and_store_chunks
                chunk_ids = [c.id for c in created_chunks]
                chunk_contents = [c.content for c in created_chunks]
                await embed_and_store_chunks(
                    chunk_ids, chunk_contents,
                    organization_id=user.selected_organization_id,
                    document_id=doc.id,
                    workflow_id=document.workflow_id,
                )
            except Exception as emb_err:
                logger.warning(f"Non-fatal: failed to pre-compute embeddings: {emb_err}")
        else:
            await knowledge_base_client.update_document(
                doc.id,
                processing_status="completed",
                chunk_count=0,
            )
        
        # Refresh document
        doc = await knowledge_base_client.get_document(doc.id)
        
        logger.info(f"Created KB document {doc.id} with {len(chunks)} chunks")
        
        return DocumentResponse(
            id=doc.id,
            name=doc.name,
            description=doc.description,
            file_type=doc.file_type,
            file_size_bytes=doc.file_size_bytes,
            chunk_count=doc.chunk_count,
            is_active=doc.is_active,
            processing_status=doc.processing_status,
            processing_error=doc.processing_error,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat() if doc.updated_at else doc.created_at.isoformat(),
            workflow_id=doc.workflow_id,
        )
        
    except Exception as e:
        logger.error(f"Failed to create KB document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    workflow_id: Optional[int] = Form(None),
    user=Depends(get_user),
):
    """Upload a file to the knowledge base."""
    # Validate file type - expanded list
    allowed_types = [
        "text/plain", 
        "text/markdown",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
        "application/msword",  # DOC
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # XLSX
        "application/vnd.ms-excel",  # XLS
    ]
    
    # Also check by file extension as MIME type detection can be unreliable
    allowed_extensions = [".txt", ".md", ".pdf", ".docx", ".doc", ".xlsx", ".xls"]
    file_ext = ""
    if file.filename:
        file_ext = "." + file.filename.split(".")[-1].lower() if "." in file.filename else ""
    
    if file.content_type not in allowed_types and file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File type not supported. Allowed: TXT, MD, PDF, DOCX, XLSX"
        )
    
    try:
        # Read file content
        content = await file.read()
        
        # Determine file type and extract text based on extension
        file_type = "txt"
        text_content = ""
        
        if file.filename:
            filename_lower = file.filename.lower()
            if filename_lower.endswith(".md"):
                file_type = "md"
                text_content = content.decode('utf-8')
            elif filename_lower.endswith(".pdf"):
                file_type = "pdf"
                text_content = content.decode('utf-8')  # PDF text extraction needs additional library
            elif filename_lower.endswith(".docx"):
                file_type = "docx"
                text_content = extract_text_from_docx(content)
            elif filename_lower.endswith((".xlsx", ".xls")):
                file_type = "xlsx"
                text_content = extract_text_from_xlsx(content)
            else:
                file_type = "txt"
                text_content = content.decode('utf-8')
        else:
            text_content = content.decode('utf-8')
        
        doc = await knowledge_base_client.create_document(
            organization_id=user.selected_organization_id,
            name=name or file.filename or "Uploaded Document",
            content=text_content,
            file_type=file_type,
            description=description,
            file_size_bytes=len(content),
            created_by=user.id,
            workflow_id=workflow_id,
        )
        
        # Chunk and process — use retrieval-optimized chunks for large files
        doc_name = name or file.filename or "Uploaded Document"
        content_len = len(text_content)
        if content_len > 15000:
            chunks = chunk_text_for_retrieval(
                text_content,
                document_name=doc_name,
                chunk_size=2000,
                overlap=200,
            )
        else:
            chunks = chunk_text(text_content)
        
        if chunks:
            created_chunks = await knowledge_base_client.create_chunks(doc.id, chunks)
            await knowledge_base_client.update_document(
                doc.id,
                processing_status="completed",
                chunk_count=len(chunks),
            )
            # Pre-compute embeddings (best-effort)
            try:
                from api.services.workflow.knowledge_base_retrieval import embed_and_store_chunks
                chunk_ids = [c.id for c in created_chunks]
                chunk_contents = [c.content for c in created_chunks]
                await embed_and_store_chunks(
                    chunk_ids, chunk_contents,
                    organization_id=user.selected_organization_id,
                    document_id=doc.id,
                    workflow_id=workflow_id,
                )
            except Exception as emb_err:
                logger.warning(f"Non-fatal: failed to pre-compute embeddings: {emb_err}")
        else:
            await knowledge_base_client.update_document(
                doc.id,
                processing_status="completed",
                chunk_count=0,
            )
        
        doc = await knowledge_base_client.get_document(doc.id)
        
        return DocumentResponse(
            id=doc.id,
            name=doc.name,
            description=doc.description,
            file_type=doc.file_type,
            file_size_bytes=doc.file_size_bytes,
            chunk_count=doc.chunk_count,
            is_active=doc.is_active,
            processing_status=doc.processing_status,
            processing_error=doc.processing_error,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat() if doc.updated_at else doc.created_at.isoformat(),
            workflow_id=doc.workflow_id,
        )
        
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Could not decode file as UTF-8 text")
    except Exception as e:
        logger.error(f"Failed to upload KB document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class WebsiteScrapeRequest(BaseModel):
    url: str = Field(..., min_length=1)
    name: Optional[str] = None
    description: Optional[str] = None
    workflow_id: Optional[int] = None


@router.post("/documents/website", response_model=DocumentResponse)
async def scrape_website_to_document(
    body: WebsiteScrapeRequest,
    user=Depends(get_user),
):
    """Scrape a website URL and create a knowledge base document from its content.

    Extracts text from the page (headings, paragraphs, lists, tables) and
    stores it as a chunked, embedded KB document.
    """
    import httpx
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse

    from api.services.security.ssrf import validate_public_url

    parsed = urlparse(body.url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL")

    # SSRF guard: validate the target (and each redirect hop) resolves to a
    # public address before fetching, so this endpoint can't be used to reach
    # internal services or the cloud metadata endpoint.
    try:
        current_url = body.url
        resp = None
        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            for _ in range(5):
                if not await validate_public_url(current_url):
                    raise HTTPException(status_code=400, detail="URL not allowed")
                resp = await client.get(
                    current_url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; DograhBot/1.0)"},
                )
                if resp.is_redirect and resp.headers.get("location"):
                    current_url = urljoin(current_url, resp.headers["location"])
                    continue
                break
            if resp is None:
                raise HTTPException(status_code=400, detail="Failed to fetch URL")
            resp.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: HTTP {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe", "svg"]):
        tag.decompose()

    # Extract title
    page_title = soup.title.string.strip() if soup.title and soup.title.string else parsed.netloc
    doc_name = body.name or page_title

    # Extract structured text
    text_parts = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "blockquote", "pre"]):
        text = el.get_text(separator=" ", strip=True)
        if not text or len(text) < 3:
            continue
        tag = el.name
        if tag.startswith("h"):
            level = int(tag[1])
            text_parts.append(f"\n{'#' * level} {text}\n")
        elif tag == "li":
            text_parts.append(f"- {text}")
        else:
            text_parts.append(text)

    text_content = "\n".join(text_parts).strip()
    if not text_content:
        raise HTTPException(status_code=400, detail="No extractable text content found on the page")

    # Prepend source URL
    text_content = f"Source: {body.url}\n\n{text_content}"

    try:
        doc = await knowledge_base_client.create_document(
            organization_id=user.selected_organization_id,
            name=doc_name[:255],
            content=text_content,
            file_type="html",
            description=body.description or f"Scraped from {body.url}",
            file_size_bytes=len(text_content.encode("utf-8")),
            created_by=user.id,
            workflow_id=body.workflow_id,
        )

        content_len = len(text_content)
        if content_len > 15000:
            chunks = chunk_text_for_retrieval(
                text_content, document_name=doc_name[:255], chunk_size=2000, overlap=200,
            )
        else:
            chunks = chunk_text(text_content)

        if chunks:
            created_chunks = await knowledge_base_client.create_chunks(doc.id, chunks)
            await knowledge_base_client.update_document(
                doc.id, processing_status="completed", chunk_count=len(chunks),
            )
            try:
                from api.services.workflow.knowledge_base_retrieval import embed_and_store_chunks
                chunk_ids = [c.id for c in created_chunks]
                chunk_contents = [c.content for c in created_chunks]
                await embed_and_store_chunks(
                    chunk_ids, chunk_contents,
                    organization_id=user.selected_organization_id,
                    document_id=doc.id,
                    workflow_id=body.workflow_id,
                )
            except Exception as emb_err:
                logger.warning(f"Non-fatal: failed to embed website content: {emb_err}")
        else:
            await knowledge_base_client.update_document(
                doc.id, processing_status="completed", chunk_count=0,
            )

        doc = await knowledge_base_client.get_document(doc.id)

        return DocumentResponse(
            id=doc.id,
            name=doc.name,
            description=doc.description,
            file_type=doc.file_type,
            file_size_bytes=doc.file_size_bytes,
            chunk_count=doc.chunk_count,
            is_active=doc.is_active,
            processing_status=doc.processing_status,
            processing_error=doc.processing_error,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat() if doc.updated_at else doc.created_at.isoformat(),
            workflow_id=doc.workflow_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scrape website into KB: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    user=Depends(get_user),
):
    """Get a specific document."""
    doc = await knowledge_base_client.get_document(document_id)
    
    if not doc or doc.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return DocumentResponse(
        id=doc.id,
        name=doc.name,
        description=doc.description,
        file_type=doc.file_type,
        file_size_bytes=doc.file_size_bytes,
        chunk_count=doc.chunk_count,
        is_active=doc.is_active,
        processing_status=doc.processing_status,
        processing_error=doc.processing_error,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat() if doc.updated_at else doc.created_at.isoformat(),
        workflow_id=doc.workflow_id,
    )


@router.patch("/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: int,
    updates: DocumentUpdate,
    user=Depends(get_user),
):
    """Update a document."""
    doc = await knowledge_base_client.get_document(document_id)
    
    if not doc or doc.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Document not found")
    
    update_data = updates.model_dump(exclude_unset=True)
    if update_data:
        doc = await knowledge_base_client.update_document(document_id, **update_data)
    
    return DocumentResponse(
        id=doc.id,
        name=doc.name,
        description=doc.description,
        file_type=doc.file_type,
        file_size_bytes=doc.file_size_bytes,
        chunk_count=doc.chunk_count,
        is_active=doc.is_active,
        processing_status=doc.processing_status,
        processing_error=doc.processing_error,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat() if doc.updated_at else doc.created_at.isoformat(),
        workflow_id=doc.workflow_id,
    )


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    user=Depends(get_user),
):
    """Delete a document and its chunks."""
    doc = await knowledge_base_client.get_document(document_id)
    
    if not doc or doc.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Document not found")
    
    await knowledge_base_client.delete_document(document_id)

    # Clean up vectors in Qdrant
    try:
        from api.services.vector import qdrant_service
        await qdrant_service.delete_by_document(document_id)
    except Exception as qe:
        logger.warning(f"Non-fatal: failed to delete Qdrant vectors for doc {document_id}: {qe}")

    return {"status": "deleted", "document_id": document_id}


@router.get("/documents/{document_id}/chunks", response_model=List[ChunkResponse])
async def get_document_chunks(
    document_id: int,
    user=Depends(get_user),
):
    """Get all chunks for a document."""
    doc = await knowledge_base_client.get_document(document_id)
    
    if not doc or doc.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Document not found")
    
    chunks = await knowledge_base_client.get_chunks_by_document(document_id)
    
    return [
        ChunkResponse(
            id=chunk.id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            token_count=chunk.token_count,
        )
        for chunk in chunks
    ]


@router.get("/documents/{document_id}/content", response_model=DocumentContentResponse)
async def get_document_content(
    document_id: int,
    user=Depends(get_user),
):
    """Get the full text content of a document for editing."""
    doc = await knowledge_base_client.get_document(document_id)

    if not doc or doc.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentContentResponse(
        id=doc.id,
        name=doc.name,
        content=doc.content,
        file_type=doc.file_type,
        chunk_count=doc.chunk_count,
    )


@router.put("/documents/{document_id}/content", response_model=DocumentResponse)
async def update_document_content(
    document_id: int,
    body: DocumentContentUpdate,
    user=Depends(get_user),
):
    """Update a document's text content, re-chunk it, and re-embed.

    This replaces the entire content of the document, deletes old chunks,
    creates new ones, and pre-computes embeddings.
    """
    doc = await knowledge_base_client.get_document(document_id)

    if not doc or doc.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        # 1. Update the content column and file size
        await knowledge_base_client.update_document(
            document_id,
            content=body.content,
            file_size_bytes=len(body.content.encode("utf-8")),
            processing_status="processing",
        )

        # 2. Delete old chunks (Postgres + Qdrant)
        await knowledge_base_client.delete_chunks_by_document(document_id)
        try:
            from api.services.vector import qdrant_service
            await qdrant_service.delete_by_document(document_id)
        except Exception as qe:
            logger.warning(f"Non-fatal: Qdrant cleanup on content update: {qe}")

        # 3. Re-chunk using the same strategy as the create path so behaviour
        #    is identical whether the doc was created or edited:
        #      - ≤50K chars → ONE chunk, no embeddings needed (retrieval
        #        always returns the full doc).
        #      - >50K chars → semantic chunks with title prefix + embeddings.
        SINGLE_CHUNK_MAX_CHARS = 50_000
        content_len = len(body.content)

        if content_len <= SINGLE_CHUNK_MAX_CHARS:
            chunks = [{
                "content": body.content.strip(),
                "token_count": len(body.content.split()) * 4 // 3,
            }]
            logger.info(
                f"KB edit: doc {document_id} stored as single chunk "
                f"({content_len} chars)"
            )
        else:
            chunks = chunk_text_for_retrieval(
                body.content,
                document_name=doc.name,
                chunk_size=2000,
                overlap=200,
            )
            logger.info(
                f"KB edit: doc {document_id} split into {len(chunks)} chunks "
                f"({content_len} chars)"
            )

        # 4. Create new chunks
        if chunks:
            created_chunks = await knowledge_base_client.create_chunks(document_id, chunks)
            await knowledge_base_client.update_document(
                document_id,
                processing_status="completed",
                chunk_count=len(chunks),
            )
            # 5. Re-embed for multi-chunk docs only. Single-chunk docs are
            #    returned in full on every retrieval so embeddings are
            #    unnecessary and would only waste embed-API calls.
            if content_len > SINGLE_CHUNK_MAX_CHARS:
                try:
                    from api.services.workflow.knowledge_base_retrieval import embed_and_store_chunks
                    chunk_ids = [c.id for c in created_chunks]
                    chunk_contents = [c.content for c in created_chunks]
                    await embed_and_store_chunks(
                        chunk_ids, chunk_contents,
                        organization_id=user.selected_organization_id,
                        document_id=document_id,
                        workflow_id=doc.workflow_id,
                    )
                    logger.info(
                        f"KB edit: re-embedded {len(chunk_ids)} chunk(s) for "
                        f"doc {document_id} into vector store"
                    )
                except Exception as emb_err:
                    logger.warning(f"Non-fatal: failed to re-compute embeddings: {emb_err}")
        else:
            await knowledge_base_client.update_document(
                document_id,
                processing_status="completed",
                chunk_count=0,
            )

        doc = await knowledge_base_client.get_document(document_id)
        logger.info(f"Updated KB document {document_id} content, {len(chunks)} chunks")

        return DocumentResponse(
            id=doc.id,
            name=doc.name,
            description=doc.description,
            file_type=doc.file_type,
            file_size_bytes=doc.file_size_bytes,
            chunk_count=doc.chunk_count,
            is_active=doc.is_active,
            processing_status=doc.processing_status,
            processing_error=doc.processing_error,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat() if doc.updated_at else doc.created_at.isoformat(),
            workflow_id=doc.workflow_id,
        )

    except Exception as e:
        logger.error(f"Failed to update KB document content: {e}")
        await knowledge_base_client.update_document(
            document_id,
            processing_status="error",
            processing_error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=SearchResultResponse)
async def search_knowledge_base(
    request: SearchRequest,
    user=Depends(get_user),
):
    """Search the knowledge base for relevant chunks."""
    chunks = await knowledge_base_client.search_chunks(
        organization_id=user.selected_organization_id,
        query=request.query,
        limit=request.limit,
    )
    
    return SearchResultResponse(
        chunks=[
            ChunkResponse(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
            )
            for chunk in chunks
        ],
        total=len(chunks),
    )


class ReindexResponse(BaseModel):
    total_chunks: int
    chunks_without_embeddings: int
    chunks_embedded: int
    message: str


@router.post("/reindex", response_model=ReindexResponse)
async def reindex_knowledge_base(
    user=Depends(get_user),
):
    """Backfill embeddings for all chunks that don't have them yet.

    This is safe to call multiple times — it only processes chunks with
    NULL embeddings.  Use this after upgrading to the new retrieval system
    to enable chunk-level semantic search on existing documents.
    """
    org_id = user.selected_organization_id
    logger.info(f"🔄 Reindex requested for organization {org_id}")

    try:
        # Fetch chunks that lack embeddings
        chunks_without = await knowledge_base_client.get_chunks_without_embeddings(org_id)
        total_chunks_result = await knowledge_base_client.get_chunks_with_embeddings_by_organization(org_id)
        total_count = len(total_chunks_result)
        missing_count = len(chunks_without)

        if not chunks_without:
            return ReindexResponse(
                total_chunks=total_count,
                chunks_without_embeddings=0,
                chunks_embedded=0,
                message="All chunks already have embeddings. Nothing to do.",
            )

        # Process in batches of 100 (OpenAI embeddings API limit is ~2048 inputs)
        from api.services.workflow.knowledge_base_retrieval import embed_and_store_chunks

        batch_size = 100
        total_embedded = 0
        for i in range(0, len(chunks_without), batch_size):
            batch = chunks_without[i : i + batch_size]
            chunk_ids = [c.id for c in batch]
            chunk_contents = [c.content for c in batch]
            doc_id = batch[0].document_id if batch else None
            embedded = await embed_and_store_chunks(
                chunk_ids, chunk_contents,
                organization_id=org_id,
                document_id=doc_id,
            )
            total_embedded += embedded

        logger.info(
            f"🔄 Reindex complete for org {org_id}: "
            f"{total_embedded}/{missing_count} chunks embedded"
        )

        return ReindexResponse(
            total_chunks=total_count,
            chunks_without_embeddings=missing_count,
            chunks_embedded=total_embedded,
            message=f"Successfully embedded {total_embedded} chunks out of {missing_count} that were missing embeddings.",
        )

    except Exception as e:
        logger.error(f"Reindex failed for org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Reindex failed: {str(e)}")


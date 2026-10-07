def chunk_text(pages: list[dict], chunk_size: int = 1000, chunk_overlap: int = 200) -> list[dict]:
    """
    Splits text from pages into smaller chunks with overlap.
    
    Args:
        pages (list[dict]): List of dictionaries containing page_num, text, and filename.
        chunk_size (int): The maximum size of each chunk (in characters).
        chunk_overlap (int): The number of overlapping characters between chunks.
        
    Returns:
        list[dict]: List of chunks with metadata.
    """
    chunks = []
    chunk_id_counter = 1
    
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size - 1)
    
    for page in pages:
        text = page.get("text", "")
        filename = page.get("filename", "unknown")
        page_num = page.get("page_num", 0)
        
        if not text or not text.strip():
            continue
        
        if len(text.strip()) <= chunk_size:
            chunks.append({
                "text": text.strip(),
                "metadata": {
                    "filename": filename,
                    "page": page_num,
                    "chunk_id": chunk_id_counter
                }
            })
            chunk_id_counter += 1
            continue
        
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end >= len(text):
                end = len(text)
            
            chunk_text_str = text[start:end]
            
            if end < len(text):
                last_space = chunk_text_str.rfind(" ")
                last_newline = chunk_text_str.rfind("\n")
                cut_point = max(last_space, last_newline)
                if cut_point > chunk_size // 2:
                    chunk_text_str = chunk_text_str[:cut_point]
                    end = start + cut_point + 1
            
            stripped = chunk_text_str.strip()
            if stripped and len(stripped) > 20:
                chunks.append({
                    "text": stripped,
                    "metadata": {
                        "filename": filename,
                        "page": page_num,
                        "chunk_id": chunk_id_counter
                    }
                })
                chunk_id_counter += 1
            
            new_start = end - chunk_overlap
            if new_start <= start:
                new_start = end if end > start else start + 1
            start = new_start
                 
    return chunks

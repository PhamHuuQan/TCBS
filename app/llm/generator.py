import os
import logging
import re
from app.llm.settings import normalize_model_path, DEFAULT_MODEL_PATH, DEFAULT_MODEL_TYPE

logger = logging.getLogger(__name__)

_llm = None
_backend = None

def reset_llm():
    global _llm, _backend
    _llm = None
    _backend = None
    logger.info("Local LLM model cache has been reset.")

def get_backend():
    return _backend

def get_llm():
    global _llm, _backend
    if _llm is not None:
        return _llm

    model_path = normalize_model_path(os.getenv("LOCAL_MODEL_PATH", DEFAULT_MODEL_PATH))
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Model file or directory not found at: {model_path}. "
            f"Please set LOCAL_MODEL_PATH in .env to the correct path."
        )
    
    n_ctx = int(os.getenv("MODEL_N_CTX", 2048))
    n_batch = int(os.getenv("MODEL_N_BATCH", 512))
    n_gpu_layers = int(os.getenv("MODEL_N_GPU_LAYERS", 0))
    n_threads = int(os.getenv("MODEL_N_THREADS", max(4, os.cpu_count() or 4)))
    
    logger.info(f"Loading local LLM: {model_path}")

    # 1. Try MLX-LM engine (Optimized for Apple Silicon macOS)
    if os.path.isdir(model_path):
        try:
            import mlx_lm
            logger.info("Initializing model via mlx-lm engine (Apple Silicon Metal)...")
            model, tokenizer = mlx_lm.load(model_path)
            _llm = (model, tokenizer)
            _backend = "mlx_lm"
            logger.info("Local LLM (mlx-lm) loaded successfully.")
            return _llm
        except Exception as e:
            logger.warning(f"mlx-lm loading failed: {e}. Falling back to GGUF/llama-cpp...")

    # 2. Try llama-cpp engine (Cross-platform for GGUF files)
    try:
        from llama_cpp import Llama
        logger.info("Initializing model via llama-cpp-python engine...")
        _llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_batch=n_batch,
            n_gpu_layers=n_gpu_layers,
            n_threads=n_threads,
            verbose=False,
        )
        _backend = "llama_cpp"
        logger.info("Local LLM (llama-cpp) loaded successfully.")
        return _llm
    except Exception as e:
        logger.warning(f"llama-cpp loading failed: {e}. Trying ctransformers fallback...")

    # 3. Try ctransformers fallback
    try:
        from ctransformers import AutoModelForCausalLM
        configured = os.getenv("LOCAL_MODEL_TYPE", DEFAULT_MODEL_TYPE).strip()
        candidates = [configured, "llama", "gemma", "mistral", "qwen"]
        for model_type in candidates:
            try:
                _llm = AutoModelForCausalLM.from_pretrained(
                    model_path,
                    model_type=model_type,
                    gpu_layers=n_gpu_layers,
                    context_length=n_ctx,
                    threads=n_threads,
                )
                _backend = "ctransformers"
                logger.info(f"Local LLM (ctransformers) loaded with model_type='{model_type}'.")
                return _llm
            except Exception as ce:
                logger.warning(f"ctransformers model_type='{model_type}' failed: {ce}")
    except Exception as e:
        logger.error(f"ctransformers loading failed: {e}")

    raise RuntimeError(f"Failed to load LLM model at {model_path} with available engines.")

def build_prompt(query: str, retrieved_chunks: list[dict], tokenizer=None, user_document_text: str = None, user_document_name: str = None) -> str:
    from app.rules.manager import get_business_rules
    rules = get_business_rules()
    
    system_role = rules.get("system_role", "Bạn là trợ lý AI thông minh, hỗ trợ giải đáp thắc mắc dựa trên tài liệu được quản trị viên cung cấp.")
    no_answer_msg = rules.get("no_answer_response", "Xin lỗi, thông tin bạn hỏi không có trong các tài liệu nội bộ được cung cấp. Tôi chỉ được phép trả lời dựa trên tài liệu của hệ thống.")
    policies = rules.get("business_policies", [])
    
    policy_str = ""
    if policies:
        policy_str = "\n".join([f"- {p}" for p in policies])
    else:
        policy_str = "- Chỉ trả lời dựa trên thông tin có trong tài liệu được cung cấp. Tuyệt đối không tự suy diễn ngoài tài liệu."
        
    context_blocks = []
    
    # 1. User Attached Document Context (Session / Chat scoped)
    if user_document_name and user_document_text:
        context_blocks.append(f"=== [TÀI LIỆU CỦA NGƯỜI DÙNG / USER ATTACHED FILE: {user_document_name}] ===\n{user_document_text.strip()}")
        
    # 2. System Knowledge Base Chunks (Admin permanent repository)
    if retrieved_chunks:
        docs_map = {}
        for chunk in retrieved_chunks:
            fn = chunk['metadata'].get('filename', 'Tài liệu')
            docs_map.setdefault(fn, []).append(chunk['text'].strip())
        for fn, texts in docs_map.items():
            combined = "\n".join(texts)
            context_blocks.append(f"=== [KIẾN THỨC HỆ THỐNG / SYSTEM KNOWLEDGE: {fn}] ===\n{combined}")
            
    context_text = "\n\n".join(context_blocks)
        
    system_msg = f"""{system_role}

QUY ĐỊNH NGHIỆP VỤ (BUSINESS POLICIES):
{policy_str}

QUY ĐỊNH ĐA NGÔN NGỮ & DỊCH THUẬT (BẮT BUỘC):
- TỰ ĐỘNG PHẢN HỒI BẰNG ĐÚNG NGÔN NGỮ CỦA NGƯỜI DÙNG:
  * Người dùng hỏi bằng tiếng Tây Ban Nha (Español) -> Trả lời bằng tiếng Tây Ban Nha.
  * Người dùng hỏi bằng tiếng Anh (English) -> Trả lời bằng tiếng Anh.
  * Người dùng hỏi bằng tiếng Pháp (Français) -> Trả lời bằng tiếng Pháp.
  * Người dùng hỏi bằng tiếng Việt -> Trả lời bằng tiếng Việt.
  * Tương tự với bất kỳ ngôn ngữ nào người dùng sử dụng.
- NẾU NGƯỜI DÙNG YÊU CẦU DỊCH THUẬT (Translate/Dịch):
  * Thực hiện dịch thuật chính xác nội dung tài liệu sang ngôn ngữ được yêu cầu.

QUY TẮC PHẢN HỒI:
1. VỚI CÂU HỎI THÔNG THƯỜNG / CHI TIẾT (hỏi số năm, số điện thoại, kỹ năng, điều khoản, dữ liệu cụ thể):
   - Trả lời CỰC KỲ NGẮN GỌN, TRỰC DIỆN (1-2 câu), đi thẳng vào kết quả cần tìm. Không chào hỏi thừa, không diễn giải dài dòng.
2. VỚI YÊU CẦU TÓM TẮT / TỔNG QUAN TÀI LIỆU:
   - Tóm tắt rõ ràng nội dung chính của tài liệu người dùng đính kèm hoặc từng tài liệu có trong phần tham khảo.
3. NGUYÊN TẮC DỮ LIỆU:
   - CHỈ sử dụng dữ liệu có trong phần [TÀI LIỆU THAM KHẢO & KIẾN THỨC HỆ THỐNG]. Đối chiếu chính xác giữa tài liệu người dùng và kiến thức hệ thống. Tuyệt đối không tự suy diễn hoặc bịa đặt ngoài tài liệu.
   - Nếu tài liệu KHÔNG chứa thông tin trả lời câu hỏi, trả lời chính xác câu: "{no_answer_msg}"
4. Tuyệt đối không xuất suy nghĩ nội bộ, không hiển thị thẻ <think>."""

    user_msg = f"""[TÀI LIỆU THAM KHẢO & KIẾN THỨC HỆ THỐNG]:
{context_text}

[CÂU HỎI / YÊU CẦU]:
{query}"""

    # If tokenizer has chat template, apply it
    if tokenizer is not None and hasattr(tokenizer, "apply_chat_template"):
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]
        try:
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            # Skip reasoning thinking block if Qwen/DeepSeek reasoning template
            if "</think>" not in prompt:
                prompt += "</think>\n"
            return prompt
        except Exception:
            pass

    # Default turn-based prompt format (Gemma / Llama / Generic)
    prompt = f"""<start_of_turn>user
{system_msg}

{user_msg}<end_of_turn>
<start_of_turn>model
"""
    return prompt

def clean_llm_output(text: str) -> str:
    """
    Cleans up any repeated lines, meta-instructions, think tags, or chain-of-thought hallucinated by the model.
    """
    if not text:
        return ""
        
    text = text.strip()
    
    # 1. Remove thinking / chain-of-thought blocks (<think>...</think>)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    
    # 2. Truncate at common hallucinated section headers
    cut_patterns = [
        r'\n\s*YÊU CẦU ĐIỀU CHỈNH:',
        r'\n\s*PHÂN TÍCH VÀ THỰC THI:',
        r'\n\s*BẢN ĐÁP ÁN CHÍNH THỨC:',
        r'\n\s*BẢN ĐÁP ÁN CUỐI CÙNG:',
        r'\n\s*BẢN ĐÁP ÁN ĐƯỢC YÊU CẦU:',
        r'\n\s*\(Kết luận:',
        r'<end_of_turn>',
        r'<start_of_turn>',
        r'<\|im_end\|>',
        r'<\|im_start\|>',
    ]
    for cp in cut_patterns:
        match = re.search(cp, text, flags=re.IGNORECASE)
        if match:
            text = text[:match.start()].strip()
            
    # 3. Deduplicate repeated consecutive lines
    lines = text.split("\n")
    cleaned_lines = []
    seen_consecutive = None
    for line in lines:
        stripped = line.strip()
        if stripped and stripped == seen_consecutive:
            continue
        cleaned_lines.append(line)
        seen_consecutive = stripped
        
    return "\n".join(cleaned_lines).strip()

def generate_answer(query: str, retrieved_chunks: list[dict], user_document_text: str = None, user_document_name: str = None) -> str:
    from app.rules.manager import get_business_rules
    rules = get_business_rules()
    no_answer_msg = rules.get("no_answer_response", "Xin lỗi, tôi không tìm thấy thông tin phù hợp trong tài liệu của bạn.")
    
    if not retrieved_chunks and not user_document_text:
        return no_answer_msg
        
    try:
        llm = get_llm()
        
        max_tokens = int(os.getenv("MODEL_MAX_TOKENS", 1024))
        temperature = float(os.getenv("MODEL_TEMPERATURE", 0.1))
        
        logger.info(f"Generating answer (backend={_backend}, max_tokens={max_tokens}, temp={temperature})...")
        
        if _backend == "mlx_lm":
            import mlx_lm
            from mlx_lm.sample_utils import make_sampler
            model, tokenizer = llm
            prompt = build_prompt(
                query,
                retrieved_chunks,
                tokenizer=tokenizer,
                user_document_text=user_document_text,
                user_document_name=user_document_name
            )
            sampler = make_sampler(temp=temperature if temperature > 0 else 0.2)
            raw_answer = mlx_lm.generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                verbose=False
            )
        elif _backend == "llama_cpp":
            prompt = build_prompt(
                query,
                retrieved_chunks,
                user_document_text=user_document_text,
                user_document_name=user_document_name
            )
            stop_tokens = [
                "<end_of_turn>",
                "<start_of_turn>",
                "<|im_end|>",
                "<|im_start|>",
                "[CÂU HỎI]:",
                "CÂU HỎI:",
                "YÊU CẦU ĐIỀU CHỈNH:",
                "PHÂN TÍCH:",
                "</s>",
                "<|endoftext|>"
            ]
            res = llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop_tokens,
            )
            raw_answer = res["choices"][0]["text"]
        else:
            prompt = build_prompt(
                query,
                retrieved_chunks,
                user_document_text=user_document_text,
                user_document_name=user_document_name
            )
            stop_tokens = ["<end_of_turn>", "<start_of_turn>", "</s>"]
            raw_answer = llm(prompt, max_new_tokens=max_tokens, temperature=temperature, stop=stop_tokens)
            
        answer = clean_llm_output(str(raw_answer))
        if not answer:
            return no_answer_msg
            
        return answer
            
    except Exception as e:
        logger.error(f"Error generating answer from local LLM: {e}", exc_info=True)
        return f"An error occurred while generating the answer: {str(e)}"

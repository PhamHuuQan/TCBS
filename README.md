# TDnook — Minimalist Paper Document Reader & AI Assistant

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.10%2B-0F172A?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-0F172A?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB-0F172A?style=flat-square)](https://www.trychroma.com/)
[![OCR](https://img.shields.io/badge/OCR-EasyOCR-0F172A?style=flat-square)](https://github.com/JaidedAI/EasyOCR)
[![License](https://img.shields.io/badge/License-MIT-0F172A?style=flat-square)](LICENSE)

<br/>

**[English Documentation](#english-documentation)** &nbsp;|&nbsp; **[Tài Liệu Tiếng Việt](#tai-lieu-tieng-viet)**

</div>

---

<a id="english-documentation"></a>
# English Documentation

## 1. Overview

**TDnook** is an intelligent, minimalist document reader and AI assistant powered by **Retrieval-Augmented Generation (RAG)**. 

Inspired by dedicated e-readers (Kindle, Nook) and tactile paper stationery, TDnook transforms the tedious task of reading long reports, books, and corporate dossiers into a serene, eye-friendly paper canvas experience—backed by an accurate local AI librarian ready to summarize, cross-reference, and answer questions with page-level citations.

> [!IMPORTANT]
> **In-Process Direct Model Loading (Zero External Server Needed)**
>
> TDnook **reads and loads LLM model weights directly into RAM / GPU VRAM** for in-process inference.
> - **No local API servers required**: You **do not** need to run Ollama, start the LM Studio local server (`localhost:1234`), or host an external API.
> - **In-Process Inference**: Uses native Python bindings (`mlx-lm` on macOS Apple Silicon Metal; `llama-cpp-python` on Windows/Linux).
> - **Maximum Privacy & Zero Network Latency**: Everything runs strictly within the TDnook Python process.

---

## 2. Key Highlights

- **Paper & E-Ink Aesthetic UX**: 
  - Real tactile paper textures (*Kindle Micro-Grain, Book Parchment / Giấy Dó, Woven Linen, Smooth Matte*).
  - Soothing tone palettes (*Warm Sepia, Neutral E-Ink, Dark Ink*).
  - Book-grade typography using *Literata* and *Newsreader*.
- **Universal Multi-Format Ingestion**:
  - Native & scanned **PDF** (with automatic **EasyOCR** fallback for bilingual Vietnamese & English).
  - Image files (**PNG, JPG, JPEG, BMP, WebP**).
  - Spreadsheets (**Excel `.xlsx`, `.xls`, CSV**).
  - Documents (**Word `.docx`, `.doc`, TXT, Markdown**).
- **Enterprise Guardrails & Business Rules Engine**:
  - **Strict Mode**: Restricts answers strictly to supplied documents, preventing AI hallucinations.
  - **Direct FAQ & Keyword Routing**: Instant rule-based answers for common inquiries (hotline, working hours, company policy).
  - **Security Filter**: Built-in guardrail blocking malicious prompt injections, jailbreaks, and unauthorized queries.
- **Local-First & Offline Privacy**:
  - Native support for Apple Silicon Metal acceleration (`mlx_lm`), GGUF quantizations (`llama-cpp-python`), or `ctransformers`.
  - ChromaDB vector store running 100% locally to ensure confidential documents never leave your machine.
  - Support for Google Gemini API as an optional cloud engine.
- **Dual Workspaces**:
  - **User Reading & Chat**: Full-bleed paper canvas, multi-conversation session history, live document attachment, and clickable citation cards.
  - **Admin Control Center**: Manage corporate policies, guardrails, manual knowledge injection, and document vector management.

---

## 3. Local LLM Setup Guide: macOS vs Windows

TDnook directly loads model files from your local storage. Configure `LOCAL_MODEL_PATH` in your `.env` file according to your operating system:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LOCAL_MODEL_PATH Setup                            │
├──────────────────────────────────────┬──────────────────────────────────────┤
│               macOS                  │               Windows                │
│       (Apple Silicon M1-M4)          │       (CPU or NVIDIA CUDA)           │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ Engine: mlx-lm (Metal Accelerated)   │ Engine: llama-cpp-python             │
│ Format: MLX Model Directory          │ Format: Single .gguf Binary File     │
│ Target: Folder with safetensors      │ Target: File path to *.gguf          │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

### Option A: macOS (Apple Silicon M1 / M2 / M3 / M4)

On macOS, TDnook leverages Apple's **MLX** framework (`mlx-lm`) to execute inference directly on Unified Memory / Metal GPU with high throughput and low power consumption.

1. **Model Format**: Directory containing MLX-quantized weights (e.g., `config.json`, `*.safetensors`, `tokenizer.json`).
2. **Where to get models**:
   - Download any MLX model via the **LM Studio** desktop app (or via `huggingface-cli`).
   - *Note*: You only use LM Studio as a downloader; **do not** start the LM Studio server.
3. **Configure `.env`**:
   ```env
   # Point to the downloaded MLX model directory:
   LOCAL_MODEL_PATH=/Users/<your_username>/.lmstudio/models/lmstudio-community/Qwen3.5-2B-MLX-4bit
   LOCAL_MODEL_TYPE=qwen
   ```

### Option B: Windows (and Linux / Intel Mac)

On Windows, TDnook uses **`llama-cpp-python`** to directly read and execute quantized GGUF models on CPU or NVIDIA CUDA GPU.

1. **Model Format**: A single binary file ending in `.gguf` (e.g., `Qwen2.5-3B-Instruct-Q4_K_M.gguf`, `gemma-2-2b-it-Q4_K_M.gguf`).
2. **Where to get models**:
   - Download directly from HuggingFace (TheBloke, bartowski, or official model repos).
   - Or download via LM Studio / Ollama cache.
3. **Configure `.env`**:
   ```env
   # Point to the specific .gguf file (Absolute or Relative path):
   LOCAL_MODEL_PATH=C:\models\Qwen2.5-3B-Instruct-Q4_K_M.gguf
   # Or relative path:
   # LOCAL_MODEL_PATH=./models/gemma-4-E4B-it-Q4_K_M.gguf

   LOCAL_MODEL_TYPE=qwen
   MODEL_N_GPU_LAYERS=0      # Set to 0 for CPU; set to 25-33 for NVIDIA GPU offloading
   MODEL_N_THREADS=4         # Adjust based on your CPU cores
   ```

---

## 4. System Architecture

```text
┌────────────────────────────────────────────────────────┐
│             TDnook Paper Web Interface                 │
│      (Kindle / Sepia / E-Ink Canvas + Reader)          │
└───────────────┬────────────────────────┬───────────────┘
                │                        │
       Document Ingestion          User Question
                │                        │
                ▼                        ▼
     ┌──────────────────────┐  ┌──────────────────┐
     │ Multi-Format Loader  │  │ Admin Guardrails │
     │ (PyMuPDF + EasyOCR)  │  │ & Direct FAQ     │
     └──────────┬───────────┘  └────────┬─────────┘
                │                       │
                ▼                       ▼
     ┌──────────────────────┐  ┌──────────────────┐
     │ Recursive Chunker    │  │ Query Embedding  │
     └──────────┬───────────┘  └────────┬─────────┘
                │                       │
                ▼                       │
     ┌──────────────────────┐           │
     │ Embedding Generator  │           │
     └──────────┬───────────┘           │
                │                       │
                ▼                       ▼
     ┌────────────────────────────────────────────┐
     │             ChromaDB Vector Store          │
     │          (Semantic Similarity Search)      │
     └──────────────────────┬─────────────────────┘
                            │
                            ▼
                    Top-K Context Chunks
                            │
                            ▼
     ┌────────────────────────────────────────────┐
     │          LLM Generation Engine             │
     │  (In-Process: mlx_lm Metal / llama-cpp)    │
     └──────────────────────┬─────────────────────┘
                            │
                            ▼
              Grounded Answer + Page Sources
```

---

## 5. Installation & Quick Start

### 1. Prerequisites
- Python 3.10 to 3.13.
- (Optional) C/C++ compiler (Visual Studio Build Tools on Windows, Xcode Command Line Tools on macOS) for `llama-cpp-python`.

### 2. Clone & Setup Environment

**macOS / Linux:**
```bash
git clone https://github.com/your-username/TDnook.git
cd TDnook

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Windows (PowerShell / Command Prompt):**
```powershell
git clone https://github.com/your-username/TDnook.git
cd TDnook

python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env     # On Windows: copy .env.example .env
```
Edit `.env` to verify `LOCAL_MODEL_PATH` matches your local model location.

### 4. Running the Application

**Main Paper Web Application (FastAPI + Paper Reader UI):**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open your browser at: **[http://localhost:8000](http://localhost:8000)**

**Alternative Streamlit Dashboard:**
```bash
streamlit run app/streamlit_app.py
```
Open your browser at: **[http://localhost:8501](http://localhost:8501)**

---

## 6. REST API Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/documents/upload` | Upload & ingest document (PDF, DOCX, XLSX, Image, TXT) |
| `POST` | `/documents/raw-text` | Ingest raw text snippet directly into vector store |
| `GET` | `/documents` | List all indexed documents in ChromaDB |
| `DELETE` | `/documents/{filename}` | Delete a specific document and its vector embeddings |
| `DELETE` | `/documents` | Clear all documents and reset the vector database |
| `POST` | `/query` | Ask questions with grounded citations |
| `GET` | `/rules` | Fetch business policies, guardrails, and FAQ rules |
| `POST` | `/rules` | Update business policies, forbidden keywords, and FAQs |

---

<br/>

---

<a id="tai-lieu-tieng-viet"></a>
# Tài Liệu Tiếng Việt

## 1. Giới Thiệu Tổng Quan

**TDnook** là ứng dụng đọc tài liệu thông minh và trợ lý hỏi đáp AI xây dựng trên kiến trúc **Retrieval-Augmented Generation (RAG)**.

Lấy cảm hứng từ các thiết bị đọc sách e-reader (Kindle, Nook) cùng chất liệu giấy truyền thống (giấy Dó, giấy mộc), TDnook biến trải nghiệm tra cứu hồ sơ, văn bản kỹ thuật và sách báo phức tạp thành một không gian đọc thư thái, dịu mắt—kết hợp thủ thư AI hỗ trợ tóm tắt, đối chiếu thông tin và trích dẫn chính xác đến từng trang tài liệu.

> [!IMPORTANT]
> **Cơ Chế Đọc & Nạp Trực Tiếp Mô Hình (In-Process Direct Loading)**
>
> TDnook **đọc và load trực tiếp file mô hình LLM từ ổ cứng vào RAM/GPU VRAM** để chạy suy luận nội bộ:
> - **Không cần bật API server ngoài**: Bạn **không cần** cài đặt hoặc khởi động Ollama, không cần bật LM Studio Local Server (`localhost:1234`).
> - **Inference trực tiếp trong tiến trình**: Dùng binding native Python (`mlx-lm` trên chip Apple Silicon Metal; `llama-cpp-python` trên Windows/Linux).
> - **Bảo mật tuyệt đối & Không trễ mạng**: Dữ liệu và truy vấn hoàn toàn không rời khỏi máy tính cá nhân.

---

## 2. Tính Năng Nổi Bật

- **Trải Nghiệm Đọc Phong Cách Giấy & E-Ink**:
  - Tái hiện bề mặt giấy chân thực (*Hạt vi mô Kindle, Giấy Dó / Book Parchment, Vải dệt Linen, Mịn nhung Matte*).
  - Gam màu dịu mắt (*Sepia ấm, E-Ink trung tính, Mực tối Dark Ink*).
  - Phông chữ tiêu chuẩn in ấn (*Literata*, *Newsreader*).
- **Hỗ Trợ Đa Định Dạng Toàn Diện**:
  - File **PDF** scan và digital (tích hợp **EasyOCR** nhận diện chữ tiếng Việt & tiếng Anh).
  - Tệp hình ảnh (**PNG, JPG, JPEG, BMP, WebP**).
  - Bảng tính (**Excel `.xlsx`, `.xls`, CSV**).
  - Tài liệu văn phòng (**Word `.docx`, `.doc`, TXT, Markdown**).
- **Hệ Thống Guardrails & Quy Định Nghiệp Vụ Doanh Nghiệp**:
  - **Strict Mode**: Buộc AI chỉ trả lời từ tài liệu được nạp, triệt tiêu hiện tượng ảo giác (hallucination).
  - **Direct FAQ & Keyword Routing**: Tự động phản hồi nhanh cho các câu hỏi cố định (hotline, giờ làm việc, chính sách).
  - **Bộ Lọc An Ninh**: Ngăn chặn prompt injection, jailbreak và truy vấn dữ liệu trái phép.
- **Quyền Riêng Tư & Offline Hoàn Toàn**:
  - Tối ưu Metal GPU trên Mac Apple Silicon (`mlx_lm`) hoặc CPU/CUDA trên Windows (`llama-cpp-python`).
  - ChromaDB lưu trữ vector 100% tại máy cục bộ.
  - Hỗ trợ tùy chọn kết nối Google Gemini API khi cần dùng cloud.
- **Hai Không Gian Làm Việc**:
  - **Giao diện Người dùng**: Canvas đọc sách, quản lý lịch sử hội thoại, đính kèm file tạm thời theo phiên và thẻ trích dẫn nguồn.
  - **Bảng Quản Trị (Admin)**: Cấu hình quy định phản hồi, guardrail an toàn và quản lý thư viện tài liệu.

---

## 3. Hướng Dẫn Cấu Hình Model Cho macOS và Windows

TDnook đọc file mô hình trực tiếp từ ổ cứng. Bạn chỉ cần cấu hình biến `LOCAL_MODEL_PATH` trong file `.env` theo hệ điều hành đang dùng:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Cấu Hình LOCAL_MODEL_PATH                            │
├──────────────────────────────────────┬──────────────────────────────────────┤
│               macOS                  │               Windows                │
│       (Apple Silicon M1-M4)          │       (CPU hoặc NVIDIA CUDA)         │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ Engine: mlx-lm (Tăng tốc Metal GPU) │ Engine: llama-cpp-python             │
│ Định dạng: Thư mục mô hình MLX       │ Định dạng: File đơn .gguf            │
│ Trỏ tới: Thư mục chứa safetensors    │ Trỏ tới: Đường dẫn file *.gguf       │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

### Cách A: Dành cho macOS (Chip Apple Silicon M1 / M2 / M3 / M4)

Trên máy Mac Apple Silicon, TDnook sử dụng framework **`mlx-lm`** của Apple để chạy trực tiếp trên Unified Memory (RAM hợp nhất) và Metal GPU với tốc độ rất nhanh và tiết kiệm pin.

1. **Định dạng model**: Thư mục chứa model MLX (gồm các file `config.json`, `*.safetensors`, `tokenizer.json`).
2. **Cách lấy model**:
   - Tải các model MLX thông qua ứng dụng **LM Studio** (hoặc dùng `huggingface-cli`).
   - *Chú ý*: Bạn chỉ dùng LM Studio để tải file về máy; **không cần** bật ứng dụng hay khởi chạy server LM Studio.
3. **Cấu hình trong file `.env`**:
   ```env
   # Trỏ thẳng đến thư mục chứa model MLX đã tải:
   LOCAL_MODEL_PATH=/Users/<tên_user_của_bạn>/.lmstudio/models/lmstudio-community/Qwen3.5-2B-MLX-4bit
   LOCAL_MODEL_TYPE=qwen
   ```

### Cách B: Dành cho Windows (và Linux / Intel Mac)

Trên Windows, TDnook sử dụng thư viện **`llama-cpp-python`** để nạp trực tiếp file nén lượng tử hóa GGUF vào CPU hoặc card đồ họa NVIDIA CUDA.

1. **Định dạng model**: File đơn lẻ đuôi `.gguf` (ví dụ: `Qwen2.5-3B-Instruct-Q4_K_M.gguf`, `gemma-2-2b-it-Q4_K_M.gguf`).
2. **Cách lấy model**:
   - Tải trực tiếp từ HuggingFace (từ các nguồn uy tín như TheBloke, bartowski, Qwen).
   - Hoặc tải qua LM Studio và lấy đường dẫn file `.gguf`.
3. **Cấu hình trong file `.env`**:
   ```env
   # Trỏ tới đường dẫn file .gguf (Đường dẫn tuyệt đối hoặc tương đối):
   LOCAL_MODEL_PATH=C:\models\Qwen2.5-3B-Instruct-Q4_K_M.gguf
   # Hoặc đường dẫn tương đối trong project:
   # LOCAL_MODEL_PATH=./models/gemma-4-E4B-it-Q4_K_M.gguf

   LOCAL_MODEL_TYPE=qwen
   MODEL_N_GPU_LAYERS=0      # Đặt = 0 nếu dùng CPU; đặt 25-33 nếu có card NVIDIA rời
   MODEL_N_THREADS=4         # Số luồng CPU phân bổ
   ```

---

## 4. Cài Đặt & Chạy Ứng Dụng

### 1. Chuẩn Bị
- Python phiên bản từ 3.10 đến 3.13.
- (Tùy chọn) Bộ build C/C++ (Visual Studio Build Tools trên Windows, Xcode Tools trên Mac) nếu build `llama-cpp-python`.

### 2. Khởi Tạo Môi Trường Ảo

**Trên macOS / Linux:**
```bash
git clone https://github.com/your-username/TDnook.git
cd TDnook

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Trên Windows (PowerShell / Command Prompt):**
```powershell
git clone https://github.com/your-username/TDnook.git
cd TDnook

python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Cấu Hình File Môi Trường
Sao chép template cấu hình `.env.example` thành `.env`:
```bash
cp .env.example .env     # Trên Windows: copy .env.example .env
```
Mở `.env` và kiểm tra đường dẫn `LOCAL_MODEL_PATH` đã trỏ đúng model trên máy bạn.

### 4. Khởi Chạy Hệ Thống

**1. Giao Diện Đọc Sách Chính (FastAPI Web App):**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Truy cập trình duyệt: **[http://localhost:8000](http://localhost:8000)**

**2. Giao Diện Bảng Quản Trị Streamlit (Phụ):**
```bash
streamlit run app/streamlit_app.py
```
Truy cập trình duyệt: **[http://localhost:8501](http://localhost:8501)**

---

## 5. Danh Sách REST API

| Giao thức | Đường dẫn Endpoint | Mô tả chức năng |
| :--- | :--- | :--- |
| `POST` | `/documents/upload` | Tải lên và index tài liệu (PDF, Word, Excel, Ảnh, Text) |
| `POST` | `/documents/raw-text` | Nạp đoạn văn bản/ghi chú trực tiếp vào CSDL vector |
| `GET` | `/documents` | Liệt kê danh sách tài liệu hiện có trong ChromaDB |
| `DELETE` | `/documents/{filename}` | Xóa một tài liệu cụ thể và vector tương ứng |
| `DELETE` | `/documents` | Xóa sạch toàn bộ tài liệu và làm mới CSDL vector |
| `POST` | `/query` | Đặt câu hỏi tra cứu kèm trích dẫn nguồn tài liệu |
| `GET` | `/rules` | Lấy danh sách quy định nghiệp vụ và câu hỏi FAQ |
| `POST` | `/rules` | Cập nhật quy định, từ khóa cấm và phản hồi nhanh FAQ |

---

## 6. Chính Sách Bảo Mật & An Toàn Dữ Liệu

- **Không Đẩy Dữ Liệu Riêng Tư Lên Git**: Toàn bộ trọng số mô hình (`*.gguf`), tài liệu người dùng (`data/documents/*`), cơ sở dữ liệu vector (`data/vector_db/*`), file cấu hình bí mật (`.env`) và tài liệu cá nhân (CV/Resume) đã được loại trừ triệt để trong `.gitignore`.
- **Hoạt Động Offline Độc Lập**: Mọi bước từ bóc tách văn bản, OCR, sinh vector embedding đến suy luận sinh câu trả lời đều diễn ra 100% trên phần cứng máy tính của bạn mà không gửi dữ liệu ra ngoài Internet.

---

## 7. Bản Quyền (License)

Dự án được phân phối dưới giấy phép **MIT License** — xem chi tiết tại file [LICENSE](LICENSE).

### Configure the local model in the web UI

Open **Admin Business Rules → Business Rules & Guardrails**. The first card,
**LLM Model Storage & Path Configuration**, accepts the path to an existing `.gguf`
file or an MLX folder containing `config.json` and `.safetensors` weights. Paths
refer to the machine running TDnook, not the browser's device. `~` is expanded to
the server user's home directory. Presets are examples; adjust them to your files.

Choose the model architecture and click **Save Model Settings**. TDnook validates
the location and persists it to `.env`; failed validation or writes leave the
active settings unchanged. The cached model is cleared after saving and the new
model loads on the next query that requires inference. A detected path does not
guarantee model compatibility with the installed inference engine.

Use **Browse…** next to the model path to open a local picker. It starts at the
current model location and offers Home, LM Studio, Hugging Face, and project
model folders when present. Select a GGUF file directly, or enter an MLX folder
and choose **Select this folder**. Selection fills the absolute path; it does
not upload weights or save settings until you click **Save Model Settings**.
The picker is available when accessing TDnook locally; remote clients can still
enter the server's model path manually.


---
# TCBS Quant Trading Layer

This fork keeps TDnook's local-first RAG/document workflow and adds a read-only TCBS MCP integration plus a deterministic quantitative analysis layer.

## Architecture

```
TCBS MCP ──> market/fundamental/technical data ──┐
                                                 ├─> Python Quant Engine ──> score/signal
Local documents ──> ChromaDB RAG ────────────────┘                 │
                                                                  └─> Local LLM explanation
```

The Python engine performs the scoring and numeric transformations. The LLM is not trusted to invent market numbers or replace deterministic calculations.

## TCBS connection

Official remote MCP endpoint:
`https://mcp.tcbs.com.vn/mcp/tcinvest/`

Run locally:

```powershell
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then use the application's TCBS connection flow. OAuth tokens are kept in memory; passwords and iOTP are never written to the repository.

## Quant API

After TCBS is connected:

- `GET /quant/analyze/VCB` — one-ticker analysis.
- `POST /quant/compare` with `{"tickers":["VCB","BID","CTG"]}` — side-by-side comparison.
- `POST /quant/screen` with `{"tickers":["VCB","BID","CTG", "MBB"]}` — ranked screening.

The engine currently separates valuation, quality, growth, momentum and risk, ignores unavailable fields instead of fabricating them, and reports an explicit insufficient-data state when TCBS does not expose enough inputs.

See `docs/TCBS_MCP.md` for the MCP integration details.

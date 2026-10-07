import streamlit as st
import requests
import json
import time

# API Configuration
API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="DocuRAG Enterprise",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Minimal Clean Styling
st.markdown("""
<style>
    .portal-title { font-size: 1.8rem; font-weight: 600; color: #0F172A; margin-bottom: 0.1rem; }
    .portal-desc { font-size: 0.9rem; color: #64748B; margin-bottom: 1.2rem; }
    .source-box { background-color: #F8FAFC; padding: 8px 12px; border-radius: 4px; border-left: 3px solid #0EA5E9; margin-top: 6px; font-size: 0.85rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 16px; border-bottom: 1px solid #E2E8F0; }
    .stTabs [data-baseweb="tab"] { height: 42px; font-weight: 500; font-size: 0.95rem; }
</style>
""", unsafe_allow_html=True)

# Helper API functions
def api_get_documents():
    try:
        r = requests.get(f"{API_URL}/documents", timeout=5)
        if r.status_code == 200:
            return r.json().get("documents", [])
    except Exception:
        pass
    return []

def api_get_rules():
    try:
        r = requests.get(f"{API_URL}/rules", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}

def api_save_rules(rules_dict):
    try:
        r = requests.post(f"{API_URL}/rules", json=rules_dict, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

# Initialize Session States
if "messages" not in st.session_state:
    st.session_state.messages = []
if "selected_doc" not in st.session_state:
    st.session_state.selected_doc = "All Documents"

# Top Navigation
portal_mode = st.radio(
    "Che do lam viec:",
    options=["User Portal (Tai lieu & Hoi dap)", "Admin Portal (Business Rules & Quan ly)"],
    horizontal=True
)

st.markdown("---")

# =========================================================================
# 1. USER PORTAL
# =========================================================================
if "User Portal" in portal_mode:
    st.markdown('<div class="portal-title">User Workspace</div>', unsafe_allow_html=True)
    st.markdown('<div class="portal-desc">Tai len tai lieu cua ban va dat cau hoi. He thong tra loi dua tren noi dung tai lieu va quy dinh duoc ap dung.</div>', unsafe_allow_html=True)

    col_upload, col_chat = st.columns([1, 2], gap="large")

    with col_upload:
        st.markdown("##### 1. Tai len tai lieu")
        st.caption("Dinh dang ho tro: PDF, Word (.docx), Excel (.xlsx), CSV, Anh (PNG, JPG), Text (.txt)")
        
        user_file = st.file_uploader(
            "Chon file:",
            type=["pdf", "png", "jpg", "jpeg", "docx", "xlsx", "xls", "csv", "txt", "md"],
            key="user_file_uploader",
            label_visibility="collapsed"
        )
        
        if st.button("Nap tai lieu", type="primary", use_container_width=True):
            if user_file is not None:
                with st.spinner(f"Dang xu ly {user_file.name}..."):
                    files_payload = {"file": (user_file.name, user_file.getvalue(), user_file.type or "application/octet-stream")}
                    try:
                        r = requests.post(f"{API_URL}/documents/upload", files=files_payload, timeout=60)
                        if r.status_code == 200:
                            data = r.json()
                            st.success(f"Da nap: {data['filename']} ({data['chunks']} chunks)")
                            st.session_state.selected_doc = data['filename']
                            st.session_state.messages = []
                            st.rerun()
                        else:
                            st.error(f"Loi: {r.text}")
                    except Exception as e:
                        st.error(f"Loi ket noi: {e}")
            else:
                st.warning("Vui long chon file truoc.")

        st.markdown("---")
        st.markdown("##### 2. Pham vi hoi dap")
        all_docs = api_get_documents()
        
        if all_docs:
            doc_options = ["All Documents"] + all_docs
            cur_idx = 0
            if st.session_state.selected_doc in doc_options:
                cur_idx = doc_options.index(st.session_state.selected_doc)
                
            selected = st.selectbox(
                "Chon tai lieu:",
                options=doc_options,
                index=cur_idx,
                label_visibility="collapsed"
            )
            st.session_state.selected_doc = selected
            st.caption(f"Pham vi hien tai: **{selected}**")
        else:
            st.info("Chua co tai lieu nao.")
            st.session_state.selected_doc = "All Documents"

        st.markdown("---")
        if st.button("Xoa lich su chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    with col_chat:
        st.markdown("##### Hoi dap truc tiep")
        
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sources"):
                    with st.expander("Nguon trich dan"):
                        for s in msg["sources"]:
                            st.markdown(f"- {s['filename']} (Trang/Sheet: {s['page']})")

        if user_prompt := st.chat_input("Nhap cau hoi cua ban..."):
            st.chat_message("user").markdown(user_prompt)
            st.session_state.messages.append({"role": "user", "content": user_prompt})

            with st.chat_message("assistant"):
                msg_placeholder = st.empty()
                msg_placeholder.markdown("Dang xu ly...")
                
                try:
                    payload = {"question": user_prompt}
                    if st.session_state.selected_doc != "All Documents":
                        payload["filename"] = st.session_state.selected_doc
                        
                    resp = requests.post(f"{API_URL}/query", json=payload, timeout=180)
                    
                    if resp.status_code == 200:
                        res_json = resp.json()
                        ans = res_json.get("answer", "")
                        sources = res_json.get("sources", [])
                        
                        msg_placeholder.markdown(ans)
                        
                        if sources:
                            with st.expander("Nguon trich dan"):
                                for s in sources:
                                    st.markdown(f"- {s['filename']} (Trang/Sheet: {s['page']})")
                                    
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": ans,
                            "sources": sources
                        })
                    else:
                        err_text = f"Loi: {resp.text}"
                        msg_placeholder.error(err_text)
                        st.session_state.messages.append({"role": "assistant", "content": err_text})
                        
                except requests.exceptions.Timeout:
                    err_text = "Thoi gian xu ly qua lau (Timeout). Vui long thu lai."
                    msg_placeholder.error(err_text)
                    st.session_state.messages.append({"role": "assistant", "content": err_text})
                except Exception as ex:
                    err_text = f"Loi: {str(ex)}"
                    msg_placeholder.error(err_text)
                    st.session_state.messages.append({"role": "assistant", "content": err_text})

# =========================================================================
# 2. ADMIN PORTAL
# =========================================================================
else:
    st.markdown('<div class="portal-title">Admin Portal</div>', unsafe_allow_html=True)
    st.markdown('<div class="portal-desc">Thiet lap Business Rules, Guardrails va quan ly kho tai lieu quy dinh.</div>', unsafe_allow_html=True)

    tab_rules, tab_ingest, tab_manage = st.tabs([
        "Business Rules & Guardrails",
        "Nap tai lieu quy dinh",
        "Quan ly kho du lieu"
    ])

    with tab_rules:
        st.markdown("##### Cau hinh quy tac nghiep vu")
        current_rules = api_get_rules()
        
        with st.form("admin_rules_form"):
            strict_mode_val = st.checkbox(
                "Bat che do nghiem ngat (Chi tra loi trong tai lieu duoc cung cap)",
                value=current_rules.get("strict_mode", True)
            )
            
            system_role_val = st.text_input(
                "Vai tro he thong (System Role):",
                value=current_rules.get("system_role", "Ban la tro ly AI chuyen nghiep tra loi dua tren tai lieu duoc cung cap.")
            )
            
            no_answer_val = st.text_area(
                "Cau tu choi mac dinh khi khong tim thay thong tin:",
                value=current_rules.get("no_answer_response", "Xin loi, thong tin ban hoi khong co trong tai lieu duoc cung cap."),
                height=70
            )
            
            policies_list = current_rules.get("business_policies", [])
            policies_val = st.text_area(
                "Danh sach Business Policies (Moi dong la mot quy dinh):",
                value="\n".join(policies_list),
                height=110
            )
            
            st.markdown("Direct FAQ (Dinh dang JSON):")
            faq_json_str = json.dumps(current_rules.get("direct_faq", []), ensure_ascii=False, indent=2)
            faq_val = st.text_area("JSON FAQ:", value=faq_json_str, height=120, label_visibility="collapsed")
            
            forbidden_list = current_rules.get("forbidden_keywords", [])
            forbidden_val = st.text_input(
                "Tu khoa cam (cach nhau boi dau phay):",
                value=", ".join(forbidden_list)
            )
            
            btn_save = st.form_submit_button("Luu Business Rules", type="primary")
            
            if btn_save:
                try:
                    parsed_faq = json.loads(faq_val)
                    parsed_policies = [p.strip() for p in policies_val.split("\n") if p.strip()]
                    parsed_forbidden = [f.strip() for f in forbidden_val.split(",") if f.strip()]
                    
                    new_rules = {
                        "strict_mode": strict_mode_val,
                        "system_role": system_role_val.strip(),
                        "no_answer_response": no_answer_val.strip(),
                        "business_policies": parsed_policies,
                        "direct_faq": parsed_faq,
                        "forbidden_keywords": parsed_forbidden
                    }
                    
                    if api_save_rules(new_rules):
                        st.success("Da luu cau hinh thanh cong.")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("Khong the luu cau hinh.")
                except json.JSONDecodeError:
                    st.error("Cu phap JSON o muc Direct FAQ khong hop le.")

    with tab_ingest:
        st.markdown("##### 1. Nap file quy dinh")
        admin_files = st.file_uploader(
            "Chon file quy dinh (PDF, Word, Excel, CSV, Anh OCR, TXT):",
            type=["pdf", "png", "jpg", "jpeg", "docx", "xlsx", "xls", "csv", "txt", "md"],
            accept_multiple_files=True,
            key="admin_file_uploader",
            label_visibility="collapsed"
        )
        
        if st.button("Nap file da chon", type="primary"):
            if admin_files:
                for file in admin_files:
                    with st.spinner(f"Dang nap {file.name}..."):
                        files_payload = {"file": (file.name, file.getvalue(), file.type or "application/octet-stream")}
                        try:
                            r = requests.post(f"{API_URL}/documents/upload", files=files_payload)
                            if r.status_code == 200:
                                res = r.json()
                                st.success(f"Da nap: {res['filename']} ({res['chunks']} chunks)")
                            else:
                                st.error(f"Loi: {r.text}")
                        except Exception as ex:
                            st.error(f"Loi: {ex}")
                time.sleep(0.5)
                st.rerun()
            else:
                st.warning("Vui long chon it nhat 1 file.")

        st.markdown("---")
        st.markdown("##### 2. Them quy dinh bang cach go tay")
        with st.form("admin_manual_text_form"):
            manual_title = st.text_input("Tieu de quy dinh:", placeholder="VD: Quy_dinh_bao_hanh_2026")
            manual_content = st.text_area("Noi dung chi tiet:", height=110, placeholder="VD: Thoi gian bao hanh la 12 thang...")
            btn_manual = st.form_submit_button("Luu quy dinh")
            
            if btn_manual:
                if manual_title.strip() and manual_content.strip():
                    with st.spinner("Dang xu ly..."):
                        try:
                            r = requests.post(f"{API_URL}/documents/raw-text", json={"title": manual_title, "text": manual_content})
                            if r.status_code == 200:
                                res = r.json()
                                st.success(f"Da them: {res['filename']}")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(f"Loi: {r.text}")
                        except Exception as ex:
                            st.error(f"Loi: {ex}")
                else:
                    st.warning("Vui long nhap day du tieu de va noi dung.")

    with tab_manage:
        st.markdown("##### Danh sach tai lieu hien co")
        doc_list = api_get_documents()
        
        if doc_list:
            st.caption(f"Tong so tai lieu: {len(doc_list)}")
            for doc in doc_list:
                c_name, c_btn = st.columns([5, 1])
                with c_name:
                    st.text(doc)
                with c_btn:
                    if st.button("Xoa", key=f"admin_del_{doc}", use_container_width=True):
                        try:
                            r = requests.delete(f"{API_URL}/documents/{doc}")
                            if r.status_code == 200:
                                st.success(f"Da xoa {doc}")
                                time.sleep(0.3)
                                st.rerun()
                        except Exception as ex:
                            st.error(f"Loi: {ex}")
                            
            st.markdown("---")
            if st.button("Xoa toan bo du lieu (Reset DB)", type="secondary"):
                try:
                    r = requests.delete(f"{API_URL}/documents")
                    if r.status_code == 200:
                        st.success("Da xoa toan bo kho du lieu.")
                        time.sleep(0.5)
                        st.rerun()
                except Exception as ex:
                    st.error(f"Loi: {ex}")
        else:
            st.info("Chua co tai lieu nao trong he thong.")


from __future__ import annotations


def button(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


def main_menu() -> dict:
    return {
        "inline_keyboard": [
            [button("📊 Phân tích mã", "act:analyze"), button("⚖️ So sánh", "act:compare")],
            [button("🔎 Screener", "act:screen"), button("📈 Kỹ thuật", "act:technical")],
            [button("💰 Định giá", "act:valuation"), button("🏦 Ngân hàng", "act:bank")],
            [button("📰 Tin tức", "act:news"), button("🌍 Khối ngoại", "act:foreign")],
            [button("👤 Cổ đông / Insider", "act:owners"), button("💵 Cổ tức", "act:dividend")],
            [button("📄 BCTC / Tài liệu", "act:document"), button("🧠 Hỏi AI", "act:ai")],
            [button("⭐ Watchlist", "act:watch"), button("🚨 Cảnh báo", "act:alerts")],
            [button("🔐 Kết nối TCBS", "act:tcbs"), button("⚙️ Trạng thái", "act:status")],
        ]
    }


def after_ticker(ticker: str) -> dict:
    t = ticker.upper()
    return {
        "inline_keyboard": [
            [button("📈 Kỹ thuật", f"tech:{t}"), button("💰 Định giá", f"val:{t}")],
            [button("🏦 Ngân hàng", f"bank:{t}"), button("📰 Tin tức", f"news:{t}")],
            [button("🌍 Khối ngoại", f"foreign:{t}"), button("📄 Dữ liệu TCBS", f"raw:{t}")],
            [button("⭐ Thêm Watchlist", f"watchadd:{t}"), button("⬅️ Menu", "menu")],
        ]
    }


def watch_menu() -> dict:
    return {
        "inline_keyboard": [
            [button("📋 Xem danh sách", "watch:list"), button("➕ Thêm mã", "act:watch_add")],
            [button("➖ Xóa mã", "act:watch_del"), button("⬅️ Menu", "menu")],
        ]
    }


def alerts_menu() -> dict:
    return {
        "inline_keyboard": [
            [button("📋 Xem cảnh báo", "alerts:list"), button("➕ Tạo cảnh báo", "act:alert_add")],
            [button("🧹 Tắt cảnh báo", "act:alert_del"), button("⬅️ Menu", "menu")],
        ]
    }

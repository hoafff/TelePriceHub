# TelePriceHub 🚀

> Hệ thống tự động thu thập báo giá đa tầng từ các Bot Telegram nhà cung cấp, chuẩn hóa thông số (spec-preserving), lưu trữ SQLite và tra cứu giá rẻ nhất.

---

## 📌 Tính năng cốt lõi

1. **MTProto Userbot Crawler (`teleprice/crawler.py`)**:
   - Vượt qua giới hạn "Bot không thể nhắn tin/bấm nút Bot khác" bằng Telethon MTProto user account.
   - Duyệt menu inline buttons đa cấp theo thuật toán DFS.
   - Xử lý mượt mà cả 2 cơ chế: `editMessage` (sửa tin nhắn tại chỗ) và gửi tin nhắn mới.
   - Cơ chế phát hiện chu kỳ (Cycle Detection) bằng băm trạng thái SHA-256 `(btn_text + btn_data + context_hash)` và danh sách đen nút điều hướng (`Quay lại`, `Trang chủ`, `Mua ngay`).
   - Tự động bóp nghẹt tần số (Throttling / Jitter: 1.5s - 3.0s) và đón bắt `FloodWaitError` để bảo vệ tài khoản Telegram.

2. **Bộ bóc tách không tốn chi phí (`teleprice/parser.py`)**:
   - Sử dụng regex chuyên sâu trích xuất: giá (`đ`, `k`, `VND`, `$`, `USDT`), tình trạng tồn kho, thời hạn (`1 tháng`, `3 tháng`, `1 năm`), thông số phần cứng (`CPU`, `RAM`, `SSD/NVMe`, `Độ phân giải 4K`).
   - Tự động sinh `spec_key` (Ví dụ: `duration:1m|plan:premium|quality:4k` hoặc `cpu:2core|ram:4gb|storage:64gb`).

3. **Bộ khử trùng lặp sản phẩm & Gemini Fallback (`teleprice/matcher.py`)**:
   - **Tầng 1 (0 VNĐ)**: Chuẩn hóa slug và từ khóa thương hiệu (Netflix, Spotify, Canva, Jetbrains, VPS...).
   - **Tầng 2 (Gemini API Free Tier)**: Chỉ gọi khi gặp sản phẩm lạ chưa từng thấy. Có guardrail cấm gộp sản phẩm khác thông số (RAM khác, dung lượng khác, thời hạn khác). Caching SQLite vĩnh viễn.

4. **Bảng so sánh & Xếp hạng nhà cung cấp (`teleprice/comparator.py`)**:
   - Tìm giá thấp nhất, tính chênh lệch tuyệt đối và phần trăm so với bên rẻ nhất.
   - Xếp hạng Top 1, Top 2, Top 3...
   - Xuất Markdown table trực quan.

5. **Bot tra cứu cá nhân (`teleprice/bot.py`)**:
   - Tra cứu qua lệnh `/search <tên>`, xem bảng so sánh `/compare <tên>`, xem thống kê `/status`.
   - Phân quyền theo Whitelist `ALLOWED_USER_IDS`.

6. **Môi trường giả lập Mock Bot (`teleprice/mock.py`)**:
   - Chạy kiểm thử toàn bộ đường ống thu thập và thuật toán mà không cần tài khoản Telegram thật hay API key.

---

## 📂 Cấu trúc thư mục

```text
TelePriceHub/
├── .github/
│   └── workflows/
│       └── crawl.yml           # GitHub Actions chạy cron định kỳ
├── teleprice/
│   ├── __init__.py
│   ├── config.py              # Đọc cấu hình từ .env và biến môi trường
│   ├── db.py                  # Schema SQLite, Indexing, CRUD
│   ├── parser.py              # Bóc tách Regex giá, thông số, trạng thái kho
│   ├── matcher.py             # Chuẩn hóa tên sản phẩm & Gemini fallback
│   ├── comparator.py          # Tính chênh lệch giá & sinh bảng xếp hạng
│   ├── crawler.py             # Telethon MTProto crawler duyệt cây menu
│   ├── bot.py                 # Telegram Bot tra cứu cá nhân
│   └── mock.py                # Mock Telegram Client & Supplier Bot Simulator
├── tests/
│   └── test_core.py           # Unit tests & Integration tests
├── .env.example               # Mẫu cấu hình môi trường
├── generate_session.py        # Tiện ích tạo StringSession cho GitHub Actions
├── main.py                    # CLI điều khiển trung tâm
├── requirements.txt           # Thư viện phụ thuộc
└── README.md
```

---

## 🛠 Hướng dẫn cài đặt trên Windows 11 (VS Code)

### Bước 1: Mở dự án trong VS Code
Mở VS Code, chọn **File > Open Folder** và chọn thư mục `TelePriceHub`.
Mở Terminal tích hợp trong VS Code (`Ctrl + ~`).

### Bước 2: Tạo Virtual Environment và cài đặt
Khuyến nghị sử dụng Python 3.11:

```powershell
# Sử dụng uv (cực nhanh) hoặc python chuẩn:
uv venv --python 3.11 .venv
.\.venv\Scripts\activate

# Cài đặt dependencies:
uv pip install -r requirements.txt
# hoặc: pip install -r requirements.txt
```

### Bước 3: Chạy thử nghiệm ngay với chế độ Mock (Không cần API key)

```powershell
# 1. Chạy toàn bộ Unit & Integration Tests:
python main.py test

# 2. Chạy crawler với Bot nhà cung cấp giả lập:
python main.py crawl --mock

# 3. Xem bảng so sánh giá ngay trong terminal:
python main.py report
```

### Bước 4: Cấu hình tài khoản Telegram thật (Khi sẵn sàng)

1. Sao chép `.env.example` thành `.env`:
   ```powershell
   copy .env.example .env
   ```
2. Lấy `TELEGRAM_API_ID` và `TELEGRAM_API_HASH` từ [my.telegram.org](https://my.telegram.org/apps).
3. Lấy `BOT_TOKEN` cho Bot tra cứu từ `@BotFather`.
4. Điền danh sách bot nhà cung cấp vào `SUPPLIER_BOTS` (ví dụ `@bot1,@bot2`).
5. (Tùy chọn) Điền `GEMINI_API_KEY` từ [Google AI Studio](https://aistudio.google.com/app/apikey).
6. Chạy crawler thật:
   ```powershell
   python main.py crawl
   ```
   *(Lần đầu chạy, Telethon sẽ hỏi số điện thoại và mã OTP gửi về Telegram của bạn để tạo file session)*.
7. Chạy Bot tra cứu:
   ```powershell
   python main.py bot
   ```

---

## ☁️ Đánh giá triển khai: GitHub Actions vs VPS vs Local PC

| Tiêu chí | GitHub Actions (Cron) | VPS Giá rẻ / Oracle Free Tier | Local PC (Windows 11) |
| :--- | :--- | :--- | :--- |
| **Chi phí** | 0 VNĐ (2000 phút/tháng free) | 0 VNĐ (Oracle) hoặc ~70-100k/tháng | 0 VNĐ |
| **Bảo vệ Session Telegram** | ⚠️ **Rủi ro cao**: IP của GitHub Actions thuộc dải Azure Datacenter, đăng nhập userbot thường xuyên bị Telegram gắn cờ spam, bắt OTP lại hoặc revoke session. | 🟢 **An toàn cao**: IP tĩnh cố định, ít bị kiểm tra bảo mật bất thường. | 🟢 **An toàn nhất**: IP mạng gia đình là IP đáng tin cậy nhất đối với hệ thống chống gian lận của Telegram. |
| **Lưu trữ trạng thái (DB)** | Tạm thời (Phải upload Artifact hoặc Commit DB vào repo hoặc dùng Cloud DB). | SQLite lưu trực tiếp trên ổ đĩa SSD vĩnh viễn. | SQLite lưu trực tiếp ổ E:\ hoặc C:\. |
| **Thời gian chạy tối đa** | 6 tiếng / job (dư dả cho 1 lần crawl). | 24/7 không giới hạn. | Phụ thuộc vào thời gian bật máy. |
| **Bot tra cứu người dùng** | ❌ Không chạy được bot tra cứu liên tục (chỉ chạy dạng webhook nếu kết hợp serverless). | 🟢 Chạy bot tra cứu 24/7 liên tục bằng long-polling. | 🟡 Chỉ tra cứu khi mở máy. |

**Khuyến nghị tối ưu:**
- **Giải pháp 0đ bền vững nhất:** Chạy định kỳ trên PC Windows 11 bằng Windows Task Scheduler khi bật máy, hoặc dùng 1 máy tính mini/Raspberry Pi/Oracle Cloud Always Free (IP cố định).
- **Nếu dùng GitHub Actions:** Bắt buộc dùng `StringSession` (chạy `python generate_session.py` trên máy cá nhân trước để lấy chuỗi session và lưu vào GitHub Secret), tuyệt đối không để lộ file `.session`.

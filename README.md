# YTSub PC — tải hàng loạt video & phụ đề YouTube trên Windows

Bản PC của [Apk-YT-download](https://github.com/tuantranmarinainter-ops/Apk-YT-download): yt-dlp + FFmpeg,
giao diện web chạy trên máy (http://127.0.0.1:8765), kèm extension Chrome/Edge để lấy link video của kênh.

## Tải về
Vào **[Releases mới nhất](../../releases/latest)** → tải `YTSub-PC-…-win64.zip` → giải nén.
Mỗi lần push lên `main`, GitHub Actions tự build và tạo Release mới (`.github/workflows/build.yml`).

## Chạy
- Bản đóng gói: mở `YTSub-PC.exe` (giữ cửa sổ đen mở trong lúc tải; đóng nó là thoát app).
- Từ mã nguồn: `run.bat` (cần Python 3.10+ và ffmpeg trong PATH hoặc `bin\ffmpeg.exe`).

## Lấy phụ đề cho 100 video
1. Lấy link: dán thẳng vào ô **Thêm link** (mỗi dòng 1 link), **hoặc** dán link kênh/playlist → **Quét** → tick chọn,
   **hoặc** dùng extension (bên dưới).
2. Chọn **Tải: Chỉ phụ đề** · **Phụ đề: Gốc (theo ngôn ngữ video)** · định dạng SRT hoặc TXT.
3. Bấm **Tải**. Mỗi video ra 1 file `Tên video [id].<ngôn ngữ>.srt` trong thư mục lưu (mặc định `Downloads\YTSub\<kênh>`).
   Video nào YouTube không có phụ đề sẽ báo lỗi riêng; bấm **Thử lại lỗi** nếu lỗi do mạng.

Tuỳ chọn khác: Video MP4 / MP3, chất lượng, phụ đề ngôn ngữ 1/2/song ngữ (đổi mã ngôn ngữ trong Cài đặt),
gắn phụ đề dạng file riêng / nhúng MP4 / in cứng (dòng thứ 2 màu vàng), số video tải cùng lúc, bỏ qua video đã tải.

## Extension lấy link kênh
1. Trong app: **Cài extension → Mở thư mục extension**.
2. Chrome `chrome://extensions` (Edge `edge://extensions`) → bật **Developer mode** → **Load unpacked** → chọn thư mục `extension`.
3. Mở trang kênh (tab Videos hoặc Shorts) → bấm biểu tượng YTSub → **Tự cuộn lấy hết** (ô *Tối đa* = 100 để dừng ở 100 link)
   → chọn → **Gửi vào YTSub** (vào mục “Từ extension” của app) hoặc **Gửi & tải ngay** (dùng cài đặt hiện tại của app).
   Chuột phải vào 1 link video → “Gửi link này vào YTSub”.

## Khi YouTube chặn ("Sign in to confirm…" / HTTP 429)
Giảm **Tải cùng lúc** xuống 1–2, tăng **Nghỉ giữa video**, hoặc bật **Lấy cookie trình duyệt**. Bấm chữ `yt-dlp …`
trên đầu trang để cập nhật yt-dlp.

## Build exe
`build.bat` → `dist\YTSub-PC\` (gồm `YTSub-PC.exe`, `bin\yt-dlp.exe`, `bin\ffmpeg.exe`, `extension\`).
Test: `python -m unittest discover -s tests`.

Chỉ tải nội dung bạn có quyền sử dụng.

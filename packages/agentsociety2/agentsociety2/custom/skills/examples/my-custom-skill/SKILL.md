---
name: my-custom-skill
description: "Mẫu kỹ năng tùy chỉnh (Custom Agent Skill Template) — dùng để tham khảo khi tạo kỹ năng mới cho agent."
---

# Kỹ năng Tùy chỉnh Mẫu (My Custom Skill)

Đây là tệp mẫu để khởi tạo một kỹ năng tùy chỉnh (custom agent skill) cho AgentSociety 2.

## Cơ chế hoạt động của Kỹ năng (Skills)

Kiến trúc hiện tại hỗ trợ **hai mẫu kỹ năng hợp lệ**:

### Mẫu A: Chỉ dùng Prompt (Khuyến nghị)

Không khai báo trường `script` ở phần đầu YAML. Nội dung tệp `SKILL.md` này sẽ được đưa trực tiếp vào ngữ cảnh của LLM khi gọi `activate_skill`. Sau đó LLM sử dụng các công cụ nguyên tử tích hợp sẵn (`read`, `write`, `append`, `list`, `grep`, `ask_env`) để hoàn thành nhiệm vụ.

Đây là **cơ chế mở rộng chính** — tương tự các lệnh slash command.

### Mẫu B: Kèm Script xử lý

Thêm `script: scripts/my-script.py` vào phần đầu YAML. Script sẽ chạy trong tiến trình con cô lập `skill_worker.py` qua hàm `entrypoint(argv, ctx)` khi có sẵn (hoặc chạy như tiến trình Python độc lập). Script trao đổi kết quả qua chuỗi stdout và đọc/ghi tệp trong `ctx.workspace_root`. Script **không** gọi trực tiếp LLM hay bộ định tuyến môi trường — chỉ dùng cho các phép tính tất định (deterministic computation).

## Hướng dẫn hành vi (Chỉnh sửa theo kỹ năng của bạn)

Khi kỹ năng này được kích hoạt, agent nên:

1. Dùng `ask_env` để truy vấn thông tin cần thiết từ môi trường mô phỏng.
2. Dùng `read` / `write` / `append` để lưu trạng thái bền vững.
3. Dùng `execute_skill_script` để chạy tính toán nếu kỹ năng có đi kèm script.
4. Gọi `finish` kèm bản tóm tắt khi hoàn tất lượt.

## Ví dụ: Kỹ năng "Nhật ký hàng ngày" (Daily Journal)

Khi được kích hoạt, agent thực hiện:
1. Gọi `ask_env` với chỉ dẫn: `"Gần đây có sự kiện gì diễn ra? Hãy tóm tắt các sự kiện mới nhất."`
2. Gọi `read` đường dẫn `journal.jsonl` để nạp các dòng nhật ký trước đó (nếu tệp tồn tại).
3. Gọi `append` đường dẫn `journal.jsonl` để ghi thêm mục nhật ký hôm nay.
4. Gọi `finish` kèm tóm tắt những gì đã ghi vào nhật ký.

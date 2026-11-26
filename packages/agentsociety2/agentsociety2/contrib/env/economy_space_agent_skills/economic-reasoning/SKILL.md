---
name: economic-reasoning
description: "Tư duy ra quyết định kinh tế trong EconomySpace: kích hoạt khi agent quan sát thấy tiền tệ, giá cả, thu nhập, thuế hoặc cơ hội giao dịch tài chính."
script: scripts/economic_reasoning.py
requires:
  - observation
---

# Suy luận Kinh tế (Economic Reasoning)

Cung cấp năng lực phân tích và ra quyết định kinh tế cho agent khi vận hành trong môi trường `EconomySpace`.

## Chức năng chính

1. Phân tích trạng thái tài chính cá nhân của agent (tiền mặt/tiền tệ, thu nhập, mức tiêu dùng).
2. Đánh giá cơ hội mua bán hàng hóa và tìm việc làm dựa trên phân tích chi phí – lợi ích.
3. Lưu lại quyết định kinh tế cùng lập luận vào bộ nhớ nhận thức (cognition memory).

## Khi nào cần kích hoạt

- Dữ liệu quan sát có chứa thông tin tài chính (tiền tệ, giá bán, thu nhập).
- Agent cần ra quyết định kinh tế (mua, bán, đi làm, đầu tư).
- Các thay đổi về thuế hoặc chính sách tác động đến tình hình tài chính của agent.

## Dữ liệu và công cụ từ môi trường EconomySpace

Môi trường `EconomySpace` cung cấp các công cụ sau qua `ask_env`:
- `get_person(agent_id)` — xem trạng thái tài chính hiện tại
- `get_all_products()` — xem danh sách hàng hóa và giá niêm yết
- `buy_product(agent_id, product_name, quantity)` — thực hiện mua hàng
- `find_job(agent_id)` — tìm kiếm cơ hội việc làm

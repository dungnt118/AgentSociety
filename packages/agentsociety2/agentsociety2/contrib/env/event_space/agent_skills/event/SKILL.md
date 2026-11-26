---
name: event
description: "Quản lý sự kiện hành vi: khởi tạo, tra cứu và kết thúc hoạt động cho agent thông qua ask_env gọi công cụ EventSpace."
---

# Event — Quản lý Sự kiện Hành vi

`EventSpace` quản lý trạng thái các sự kiện hoạt động của từng agent. Mỗi agent tại một thời điểm chỉ có tối đa một sự kiện đang diễn ra. **Toàn bộ thao tác bắt buộc thực hiện bằng chỉ dẫn ngôn ngữ tự nhiên thông qua `ask_env`**.

## Khái niệm môi trường

### Mô hình sự kiện

Mỗi sự kiện gồm các thuộc tính:
- `event_type`: loại sự kiện
- `event_name`: tên/mô tả chi tiết sự kiện (văn bản tự do)
- `expected_duration_seconds`: thời lượng dự kiến (tính bằng giây)
- `start_time`: thời điểm bắt đầu
- `expected_end_time`: thời điểm dự kiến kết thúc

Sự kiện tự động tiến triển theo thời gian mô phỏng. Công cụ `get_current_event` trả về `elapsed_seconds` (đã trôi qua), `remaining_seconds` (còn lại) và `progress_percentage` (tỷ lệ phần trăm hoàn thành).

### Các loại sự kiện mặc định (`event_type`)

| Giá trị | Ý nghĩa |
|------|------|
| `sleep` | Ngủ / nghỉ ngơi |
| `work` | Làm việc |
| `eating out` | Ăn ngoài |
| `home activity` | Sinh hoạt tại nhà |
| `shopping` | Mua sắm |
| `leisure and entertainment` | Giải trí / thư giãn |
| `other` | Hoạt động khác (ngoài các nhóm trên) |

`event_name` là văn bản tự do mô tả cụ thể việc đang làm, agent tự đặt theo ngữ cảnh (ví dụ `"lunch at restaurant"`, `"morning coding session"`).

## Công cụ khả dụng

Mọi thao tác gọi qua `ask_env`:

```
ask_env(instruction="<chỉ dẫn>", ctx={"id": <your_id>})
```

### get_current_event (chỉ đọc, quan sát)

Tra cứu sự kiện đang diễn ra của agent: loại sự kiện, tên, trạng thái, thời gian đã chạy, thời gian còn lại, tiến độ %. Trả về `None` nếu chưa có sự kiện nào.

### start_event (ghi dữ liệu)

Khởi tạo một sự kiện mới. Mỗi agent tại một thời điểm chỉ có 1 sự kiện nên cần kiểm tra sự kiện hiện tại trước khi gọi.
Nếu sự kiện hiện tại đã có `event_type` trùng với loại bạn định thực hiện và vẫn đang chạy, **không** gọi `stop_event` và **không** gọi lại `start_event` — điều đó nghĩa là hoạt động đang tiếp diễn bình thường, chỉ cần duy trì trạng thái hoặc ghi nhận tiến độ.

Tham số:
- `person_id`: ID của agent
- `event_type`: loại sự kiện
- `event_name`: tên/mô tả tự do (ví dụ `"lunch at Italian restaurant"`, `"afternoon nap"`)
- `expected_duration_seconds`: thời lượng dự kiến (đơn vị **giây**)

Chỉ sử dụng đơn vị giây; không dùng tên tham số sai như `duration_min`, `duration_minutes`, `duration`, `location_id`, `location_policy`, `home_aoi`.
Quy đổi tham khảo: 30 phút = `1800`, 45 phút = `2700`, 1 giờ = `3600`, 4 giờ = `14400`, 7 giờ = `25200`, 8 giờ = `28800`.

### stop_event (ghi dữ liệu)

Kết thúc sự kiện hiện tại. Tham số: `person_id`, `status` (`"completed"` khi hoàn tất bình thường hoặc `"cancelled"` khi bị gián đoạn/hủy).

## Ví dụ sử dụng

### Kiểm tra sự kiện hiện tại

```
ask_env(instruction="Check current event for person 0", ctx={"id": 0})
→ Không có sự kiện (None)
```

### Bắt đầu sự kiện mới

```
ask_env(instruction="Start a 'work' event for person 0, event name 'morning coding session', expected duration 14400 seconds", ctx={"id": 0})
→ Sự kiện đã bắt đầu
```

### Giữ nguyên sự kiện cùng loại đang chạy

```
ask_env(instruction="Check current event for person 0", ctx={"id": 0})
→ Đã có sẵn sự kiện sleep đang chạy: không tạo lại sleep mà tiếp tục duy trì trạng thái ngủ.
```

### Dừng sự kiện

```
ask_env(instruction="Stop current event for person 0 with status completed", ctx={"id": 0})
→ Sự kiện đã kết thúc
```

### Chuyển sang sự kiện khác

```
ask_env(instruction="Stop current event for person 0, then start a 'leisure and entertainment' event, event name 'watching movie', expected duration 7200 seconds", ctx={"id": 0})
```

## Ràng buộc bắt buộc

1. **Mọi thao tác đi qua `ask_env`**. Không được gọi trực tiếp hàm `start_event`, `get_current_event`.
2. **Tối đa 1 sự kiện tại một thời điểm**. Muốn chuyển sang hoạt động khác loại phải dừng sự kiện cũ trước.
3. **Sự kiện đang chạy cùng loại là trạng thái liên tục**. Ví dụ đang có `sleep` và kịch bản hiện tại vẫn là ngủ thì giữ nguyên, không hủy rồi bật lại; chỉ dừng khi thực sự đổi sang hoạt động khác.
4. **Không cắt nhỏ sự kiện dài theo từng bước**. Ví dụ giấc ngủ từ `00:00-07:00` là một sự kiện kéo dài liên tục, không tạo mới sau mỗi 15/30 phút.

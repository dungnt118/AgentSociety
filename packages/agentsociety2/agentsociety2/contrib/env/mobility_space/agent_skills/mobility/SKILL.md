---
name: mobility
description: "Điều hướng di chuyển đô thị: đưa agent tới AOI/POI trên mạng lưới giao thông, tìm địa điểm lân cận và gợi ý điểm đến theo mô hình trọng lực qua ask_env (MobilitySpace)."
---

# Mobility — Điều hướng Di chuyển Đô thị

`MobilitySpace` là môi trường mô phỏng di chuyển trên mạng lưới đường giao thông đô thị thực tế. **Toàn bộ thao tác phải gọi qua `ask_env`** để bộ định tuyến môi trường chuyển thành lời gọi công cụ của MobilitySpace.

## Khái niệm môi trường

### AOI (Area of Interest)

Khu chức năng đô thị (khu dân cư, thương mại, văn phòng...). ID bắt đầu từ `500000000`. Mỗi agent có `home_aoi` (nhà) và `work_aoi` (nơi làm việc).

### POI (Point of Interest)

Địa điểm cụ thể (nhà hàng, quán cà phê, bệnh viện, công viên...). ID bắt đầu từ `700000000`. Mỗi POI thuộc về một AOI.

### Trạng thái di chuyển

| Trạng thái | Ý nghĩa |
|------|------|
| `idle` | Đang dừng/rảnh, có thể bắt đầu chuyến đi mới |
| `moving` | Đang di chuyển trên mạng lưới đường |

Khi đang ở trạng thái `moving`, gọi lại `move_to` sẽ ngắt hành trình hiện tại — chỉ thực hiện nếu thực sự cần đổi điểm đến.

### Thông tin vị trí

`position` trả về từ `get_person` gồm: `aoi_id`, `poi_id`, tọa độ `xy`, kinh vĩ độ `lnglat`, và `kind` (`"aoi"` hoặc `"lane"`).

### Phương thức di chuyển

| Phương thức | Ngữ cảnh phổ biến |
|------|----------|
| `walking` | Quãng đường ngắn (< 1000m) |
| `driving` | Quãng đường dài (≥ 1000m) |

Thời gian di chuyển thực tế lấy theo `eta` (giây mô phỏng) do `move_to` trả về vì khớp trực tiếp với vận tốc của môi trường; không tự ước lượng bằng tốc độ cố định.

### Danh mục loại POI (`category`)

Các nhóm loại địa điểm hỗ trợ khi tìm kiếm POI:

| Nhóm cấp 1 | Ví dụ loại chi tiết (cấp 2) |
|----------|-------------|
| `restaurant` | `bar`, `cafe`, `fast_food`, `restaurant`, `pub`, `food_court` |
| `outdoor_activity` | `park`, `playground`, `garden`, `beach_resort`, `fishing` |
| `indoor_entertainment` | `cinema`, `fitness_centre`, `bowling_alley`, `theatre`, `bar` |
| `sports_facility` | `sports_centre`, `swimming_pool`, `stadium`, `ice_rink` |
| `cultural_and_artistic` | `arts_centre`, `museum`, `cinema`, `nightclub` |
| `education_institution` | `school`, `university`, `library`, `kindergarten` |
| `medical_care` | `hospital`, `clinic`, `pharmacy`, `dentist` |
| `financial_service` | `bank`, `atm` |
| `public_service` | `police`, `post_office`, `townhall` |
| `transportation_facility` | `parking`, `bus_station`, `fuel` |
| `children_playground` | `playground`, `summer_camp` |
| `nature_and_wildlife_observation` | `nature_reserve`, `bird_hide` |
| `water_activity` | `swimming_area`, `marina` |
| `other_special_purpose` | `marketplace`, `place_of_worship` |

Có thể truyền tên nhóm cấp 1 (như `restaurant`) để khớp tất cả loại con, hoặc truyền loại chi tiết (như `cafe`) để lọc chính xác.

## Công cụ khả dụng

Mọi thao tác gọi qua `ask_env`:

```
ask_env(instruction="<chỉ dẫn>", ctx={"id": <your_id>})
```

### get_person (chỉ đọc, quan sát)

Lấy trạng thái hiện tại: vị trí, trạng thái (`idle`/`moving`), đích đến, tổng quan POI lân cận (gom theo nhóm cấp 1 kèm POI gần nhất và khoảng cách), `home_aoi`, `work_aoi`.

```
ask_env(instruction="<observe>", ctx={"id": <your_id>})
```

### recommend_poi_by_gravity (chỉ đọc)

Dùng mô hình trọng lực để gợi ý POI phù hợp dựa trên khoảng cách và mật độ POI cùng loại xung quanh (tự nhiên hơn tìm kiếm thủ công).

Tham số: `person_id`, `category` (tên loại POI hoặc `None` nếu không giới hạn), `radius` (bán kính tìm kiếm theo mét), `exclude_home_work` (có loại trừ khu vực nhà/cơ quan hay không).

Trả về: `id`, `name`, `category`, `distance`, `aoi_id` của POI được gợi ý cùng `recommended_mode` (phương thức di chuyển khuyến nghị).

### find_nearby_pois (chỉ đọc)

Tìm danh sách POI lân cận. Tham số: `x, y` (tọa độ tâm), `category` (loại hoặc `None`), `radius` (bán kính tính theo mét). Trả về `id`, `name`, `category`, `distance`, `aoi_id`.

### get_poi (chỉ đọc)

Tra cứu chi tiết một POI. Tham số: `poi_id`. Trả về `id`, `name`, `category`, `position`, `aoi_id`.

### move_to (ghi dữ liệu)

Bắt đầu di chuyển. Tham số: `person_id`, `aoi_id_or_poi_id` (ID AOI hoặc ID POI; giá trị ≥ `700000000` là POI), `mode` (`"walking"` hoặc `"driving"`).

Sau khi gọi, trạng thái chuyển thành `moving`, tự động di chuyển trên đường ở các bước sau và trở về `idle` khi tới nơi.

## Ví dụ sử dụng

### Quan sát vị trí

```
ask_env(instruction="<observe>", ctx={"id": 0})
→ home_aoi=500000007, work_aoi=500000123, status=idle, aoi_id=500000007
```

### Đi đến nơi làm việc

```
ask_env(instruction="Move person 0 to AOI 500000123 using driving", ctx={"id": 0})
→ status=moving
```

### Tìm quán ăn/cà phê và di chuyển tới đó

```
ask_env(instruction="Use recommend_poi_by_gravity for person 0, category restaurant, radius 1200, excluding home/work AOIs. Then move to the recommended POI.", ctx={"id": 0})
→ Gợi ý cafe (800m), di chuyển bằng walking
```

### Quay về nhà

```
ask_env(instruction="Move person 0 to AOI 500000007 using driving", ctx={"id": 0})
```

## Ràng buộc bắt buộc

1. **Mọi thao tác đi qua `ask_env`**. Không được gọi trực tiếp hàm `move_to`, `get_person`.
2. **Đang ở trạng thái `moving` không nên gọi lại `move_to`** trừ khi bạn thực sự muốn hủy điểm đến hiện tại để chuyển hướng khác.

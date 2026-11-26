---
name: daily-guidance
description: "Bắt buộc cho mô phỏng theo giờ trở xuống: sử dụng kỹ năng này để lập, đánh giá, thực thi và điều chỉnh kế hoạch sinh hoạt trong ngày (Daily Story)."
script: scripts/daily_guidance.py
hooks:
  pre_step: scripts/daily_guidance.py
---

# Daily Guidance — Định hướng Hành vi Hàng ngày

Daily Guidance giúp agent hình thành trước một kịch bản sinh hoạt trọn ngày (`Story`), sau đó bám theo Story đó để hành xử ở từng bước mô phỏng.
**Mọi thao tác có cấu trúc đều thực hiện qua lệnh CLI của `scripts/daily_guidance.py` — bạn gửi nội dung JSON, script sẽ kiểm tra hợp lệ, lưu thành YAML và tự suy diễn trạng thái thực thi theo đồng hồ mô phỏng.**

Mỗi ngày tương ứng một tệp: `state/daily_guidance/YYYY-MM-DD/story.yaml` (do script tạo và duy trì).

## Nguyên tắc cốt lõi

1. **Dùng `plan --json` để nộp kế hoạch cả ngày.** Gửi đối tượng JSON, script xác thực rồi ghi vào `story.yaml`.
2. **Trạng thái thực thi suy ra từ đồng hồ mô phỏng.** `completed_segments` / `current_segment_id` là hàm theo `(segments, thời gian mô phỏng hiện tại)`, được script tính mỗi lần đọc. Hết khung giờ là tự động hoàn tất chặng đó.
3. **Hook `pre_step` tự xuất `segment` hiện tại ở mỗi bước.** Đầu mỗi step, hook sẽ bơm vào ngữ cảnh `active_segment` (gồm `activity` và `location_policy`) để bạn di chuyển và trả lời khảo sát theo đúng ngữ cảnh.

## Quy trình mỗi bước (step)

Đầu mỗi bước mô phỏng, hook `pre_step` tự động trả về trạng thái hiện tại theo một trong hai trường hợp:

**Trường hợp A: Chưa có Story hợp lệ (`ok: false`)**

Kết quả hook sẽ có gợi ý `next`. Hãy nộp ngay Story cho cả ngày:

```bash
python scripts/daily_guidance.py plan --date YYYY-MM-DD --json '<JSON object>'
```

**Trường hợp B: Đã có Story hợp lệ (`ok: true`)**

Hook trả về `active_segment` và `guidance`, ví dụ:

```yaml
active_segment:
  id: sleep_night
  activity: sleep
  location_policy: home_aoi
  start: "00:00"
  end: "07:00"
guidance: Your intended activity now is 'sleep' at location policy 'home_aoi'. ...
```

Hãy hành động và trả lời bảng hỏi khảo sát đúng theo `active_segment.activity` và `location_policy`. Khi trả lời khảo sát ý định hiện tại, lấy `active_segment.activity` làm hoạt động chủ đạo.

## Các lệnh CLI hỗ trợ

Mọi lệnh được gọi qua `execute_skill_script` và trả về khối YAML chuẩn `{ok, ...}`:

| Lệnh | Mục đích sử dụng |
| --- | --- |
| `plan --date D --json '<obj>'` | Nộp Story trọn ngày (JSON). Đạt kiểm tra mới ghi file, nếu sai sẽ trả lỗi chi tiết từng trường để sửa. |
| `current --date D` | Trả về tóm tắt `segment` đang diễn ra tại thời điểm hiện tại. |
| `show --date D [--format summary\|full]` | Xem ảnh chụp trạng thái thực thi (`completed`/`current` tính theo đồng hồ). |
| `record --date D --activity A --location L [--note N]` | Ghi nhận hoạt động thực tế của bước này vào `actual_timeline`. |
| `deviate --date D --type T --reason R` | Ghi nhận sai lệch so với kế hoạch vào `change_log`. |
| `revise --date D --from SEG_ID --json '<list>'` | Thay thế `SEG_ID` và toàn bộ các chặng phía sau bằng danh sách chặng mới. |
| `check --date D` | Kiểm tra tính hợp lệ của tệp `story.yaml` hiện có. |

## Định dạng JSON cho lệnh `plan`

Tham số `--json` nhận một đối tượng JSON gồm 3 trường bắt buộc: `story_id`, `date`, `segments` (`self_check` là tùy chọn).

```json
{
  "story_id": "agent_0007:2018-06-13",
  "date": "2018-06-13",
  "segments": [
    {
      "id": "sleep_night",
      "start": "00:00",
      "end": "07:00",
      "activity": "sleep",
      "location_policy": "home_aoi",
      "maslow_reason": {
        "need": "physiological.rest",
        "reason": "night sleep keeps the day physically plausible",
        "risk": "starting the day without rest",
        "required": "required"
      },
      "tpb_reason": {
        "want": {"reason": "sleep supports recovery", "status": "supported"},
        "norm": {"reason": "sleeping at night is normal", "status": "supported"},
        "can": {"reason": "the agent is at home", "status": "supported"},
        "proof": "night time at home supports sleeping",
        "choice": "commit"
      }
    }
  ]
}
```

## Quy tắc sinh Story

- Đọc `AGENT.json` trước để nắm thời gian hiện tại, nghề nghiệp, địa điểm nhà/cơ quan và nghĩa vụ vai trò.
- Nếu hồ sơ có nghĩa vụ đi làm/đi học, phải bố trí các chặng `work`/`study` hợp lý, trừ khi `tpb_reason.can.status` chỉ ra không đủ điều kiện thực hiện.
- Phải bao phủ đủ: ngủ/nghỉ, ăn uống, nghĩa vụ chính theo vai trò, quay về nơi ở an toàn vào buổi tối.
- Ngày làm việc nên thể hiện nhịp sinh hoạt thật gồm di chuyển, ăn trưa/tối, về nhà, giải trí nhẹ, phân bổ đều trong ngày.
- Mỗi chặng bắt buộc có đủ: `id/start/end/activity/location_policy/maslow_reason/tpb_reason`.
- `start`/`end` dùng định dạng `HH:MM`, **nối tiếp liên tục không đứt quãng** (`end` chặng trước bằng `start` chặng sau); chặng cuối có thể kết thúc ở `24:00`. Tổng thời lượng phải phủ kín `00:00`–`24:00`.

## Các giá trị `location_policy`

| Giá trị | Ý nghĩa |
| --- | --- |
| `home_aoi` | Tại nhà |
| `work_aoi` | Tại nơi làm việc |
| `near_home_aoi` | Gần nhà (tìm POI lân cận) |
| `near_work_aoi` | Gần nơi làm việc (tìm POI lân cận) |
| `transit` | Đang di chuyển / đi lại |
| `city` | Tự do di chuyển trong khu vực đô thị |

## Lý giải theo Tháp nhu cầu Maslow (`maslow_reason`)

Dùng Tháp nhu cầu Maslow để giải thích tính hợp lý của lịch trình trong ngày (`maslow_reason.need` là chuỗi ký tự, dùng các giá trị chuẩn dưới đây hoặc mở rộng theo bối cảnh):

| Giá trị | Ý nghĩa |
| --- | --- |
| `physiological.food` | Ăn uống, nạp năng lượng, duy trì bữa ăn |
| `physiological.rest` | Ngủ, nghỉ ngơi, hồi phục thể lực |
| `safety.home_shelter` | Nơi ở ổn định, chỗ nghỉ ban đêm, quay về nhà |
| `safety.income_stability` | Duy trì cuộc sống qua công việc, học tập hoặc trách nhiệm |
| `belonging.social_connection` | Gắn kết gia đình, bạn bè, đồng nghiệp, cộng đồng |
| `esteem.role_obligation` | Trách nhiệm nghề nghiệp, học tập, gia đình hoặc xã hội |
| `esteem.competence` | Hoàn thành công việc, năng lực bản thân, được ghi nhận |
| `self_actualization.growth` | Học hỏi, sáng tạo, khám phá |
| `recovery.leisure` | Giải trí, dạo bộ, thư giãn nhẹ |

`maslow_reason.required` nhận một trong các giá trị: `required`, `soft_required` hoặc `optional`.

## Lý giải theo Lý thuyết Hành vi Hoạch định TPB (`tpb_reason`)

Lý thuyết Hành vi Hoạch định (TPB) xem ý định hành vi hình thành từ 3 yếu tố:

- `want`: vì sao agent muốn thực hiện hoặc chấp nhận hành động này.
- `norm`: vì sao hành động phù hợp vai trò, chuẩn mực xã hội hoặc kỳ vọng xung quanh.
- `can`: vì sao hiện tại có đủ thời gian, địa điểm, phương tiện, nguồn lực để làm.

Mỗi yếu tố gồm `reason` (câu ngắn) và `status` (`supported`/`weak`/`missing`/`contradicted`).
`proof` là một câu ngắn nêu căn cứ. `choice` chọn một trong: `commit`/`revise`/`delay`/`skip`/`observe`.
Khi `can.status: contradicted`, trường `choice` không được phép chọn `commit`.

## Xử lý sai lệch thực tế

Khi diễn biến thực tế khác với Story dự kiến, dùng CLI để cập nhật:

- `record --activity ... --location ...`: ghi nhận hoạt động thực tế của bước hiện tại vào `actual_timeline`.
- `deviate --type record_only --reason ...`: sai lệch nhẹ, chỉ ghi thêm vào `change_log`.
- `deviate --type local_patch --reason ...`: cần điều chỉnh chặng hiện tại hoặc chặng kế tiếp (sau đó gọi `revise`).
- `revise --from SEG_ID --json '<danh sách chặng mới>'`: viết lại phần đuôi Story còn lại trong ngày.
- `deviate --type carryover --reason ...`: chưa thể bù trong ngày, lưu lại để tham khảo cho ngày hôm sau.

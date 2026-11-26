---
name: social-media
description: "Tương tác mạng xã hội: đăng bài, chia sẻ lại, bình luận, thích, theo dõi, làm mới bảng tin Feed và tìm kiếm bài viết theo chủ đề qua ask_env (SocialMediaSpace)."
---

# Social Media — Tương tác Mạng xã hội

`SocialMediaSpace` là môi trường mô phỏng mạng xã hội kiểu bảng tin/diễn đàn (tương tự Weibo / Twitter / Facebook). **Mọi thao tác gọi qua `ask_env`**, bộ định tuyến môi trường sẽ chuyển đổi thành lời gọi công cụ SocialMediaSpace tương ứng.

## Khái niệm môi trường

### Danh tính người dùng

Mặc định `agent_id === user_id`: mã người dùng trên mạng xã hội trùng với ID agent của bạn. Tham số `ctx={"id": <your_id>}` cung cấp danh tính; các trường `author_id` / `user_id` / `follower_id` điền ID của chính bạn, chỉ trường đối tượng nhận hành động như `followee_id` mới điền ID người khác.

### Bài viết (Post)

Mỗi bài viết có `post_id`, `author_id`, `content`, `tags` (danh sách thẻ chủ đề), `post_type` (`original` / `repost` / `comment`), cùng các bộ đếm `likes_count`, `comments_count`, `reposts_count`, `view_count`.

### Bảng tin Feed

`refresh_feed` trả về danh sách bài viết sắp xếp theo thuật toán: `chronological` (mới nhất trước, mặc định), `reddit_hot` (độ nóng), `twitter_ranking` (tổng hợp quan hệ & tương tác), `random`, hoặc `mf` (mô hình gợi ý). Đây là luồng bài đăng (Timeline), không phải gợi ý sản phẩm thương mại.

## Công cụ khả dụng

Mọi thao tác gọi qua `ask_env`, sử dụng mẫu câu lệnh + `variables` để giữ cấu trúc nhất quán (biến động đặt vào `variables`):

```
ask_env(instruction="<mẫu câu lệnh>", variables={...}, ctx={"id": <your_id>}, readonly=<bool>)
```

### observe_user (chỉ đọc, quan sát)

Quan sát hồ sơ và hoạt động gần nhất: số người theo dõi / đang theo dõi / số bài đăng, 5 bài gần nhất trên Feed, tương tác nhận được, lịch sử hoạt động, biến động kết nối và danh sách hành động khả dụng. Nên gọi đầu mỗi bước.

```
ask_env(instruction="<observe>", ctx={"id": <your_id>})
```

### create_post (ghi dữ liệu)

Đăng bài viết gốc mới. `tags` là danh sách từ khóa chủ đề.

```
ask_env(
    instruction="create_post author_id={user_id} content={content} tags={tags}",
    variables={"user_id": 0, "content": "Support stricter background checks", "tags": ["guncontrol", "policy"]},
    ctx={"id": 0},
    readonly=False
)
```

### repost (ghi dữ liệu)

Chia sẻ lại một bài viết, có thể đính kèm `comment` (để trống sẽ mặc định nội dung `repost <post_id>`).

```
ask_env(
    instruction="repost user_id={user_id} post_id={post_id} comment={comment}",
    variables={"user_id": 0, "post_id": 3, "comment": ""},
    ctx={"id": 0},
    readonly=False
)
```

### comment_on_post (ghi dữ liệu)

Bình luận vào một bài viết.

```
ask_env(
    instruction="comment_on_post user_id={user_id} post_id={post_id} content={content}",
    variables={"user_id": 0, "post_id": 3, "content": "Agree with this perspective"},
    ctx={"id": 0},
    readonly=False
)
```

### like_post / unlike_post (ghi dữ liệu)

Thích / bỏ thích bài viết. Tham số: `user_id`, `post_id`. Khi muốn bỏ thích chỉ cần đổi `like_post` thành `unlike_post`.

```
ask_env(
    instruction="like_post user_id={user_id} post_id={post_id}",
    variables={"user_id": 0, "post_id": 3},
    ctx={"id": 0},
    readonly=False
)
```

### follow_user / unfollow_user (ghi dữ liệu)

Theo dõi / hủy theo dõi người khác. `follower_id` là ID của bạn, `followee_id` là ID đối phương.

```
ask_env(
    instruction="follow_user follower_id={user_id} followee_id={followee_id}",
    variables={"user_id": 0, "followee_id": 7},
    ctx={"id": 0},
    readonly=False
)
```

### view_post (ghi dữ liệu)

Xem chi tiết bài viết (tăng lượt xem `view_count`) để hiểu nội dung và quan điểm trước khi bình luận/thích.

```
ask_env(
    instruction="view_post user_id={user_id} post_id={post_id}",
    variables={"user_id": 0, "post_id": 3},
    ctx={"id": 0},
    readonly=False
)
```

### refresh_feed (chỉ đọc)

Làm mới bảng tin đề xuất để đọc nội dung và tìm bài viết cần tương tác.

```
ask_env(
    instruction="refresh_feed user_id={user_id} algorithm={algorithm} limit={limit}",
    variables={"user_id": 0, "algorithm": "twitter_ranking", "limit": 10},
    ctx={"id": 0},
    readonly=True
)
```

### search_posts (chỉ đọc)

Tìm kiếm bài viết. `keyword` khớp theo nội dung `content` và `tags`; `sort_by` nhận `time` (mặc định), `relevance`, hoặc `popularity`.

```
ask_env(
    instruction="search_posts keyword={keyword} tags={tags} limit={limit} sort_by={sort_by}",
    variables={"keyword": "guncontrol", "tags": [], "limit": 20, "sort_by": "popularity"},
    ctx={"id": 0},
    readonly=True
)
```

## Ví dụ quy trình

### Quan sát và làm mới bảng tin

```
ask_env(instruction="<observe>", ctx={"id": 0})
ask_env(
    instruction="refresh_feed user_id={user_id} algorithm={algorithm} limit={limit}",
    variables={"user_id": 0, "algorithm": "twitter_ranking", "limit": 10},
    ctx={"id": 0},
    readonly=True
)
```

### Đăng bài mới rồi thích bài viết nổi bật

```
ask_env(
    instruction="create_post author_id={user_id} content={content} tags={tags}",
    variables={"user_id": 0, "content": "Support stricter background checks", "tags": ["guncontrol"]},
    ctx={"id": 0},
    readonly=False
)
ask_env(
    instruction="search_posts keyword={keyword} tags={tags} limit={limit} sort_by={sort_by}",
    variables={"keyword": "guncontrol", "tags": [], "limit": 5, "sort_by": "popularity"},
    ctx={"id": 0},
    readonly=True
)
ask_env(
    instruction="like_post user_id={user_id} post_id={post_id}",
    variables={"user_id": 0, "post_id": 7},
    ctx={"id": 0},
    readonly=False
)
```

## Ràng buộc bắt buộc

1. **Mọi thao tác đi qua `ask_env`**. Không được gọi trực tiếp hàm `create_post`, `refresh_feed`.
2. **Luôn truyền đúng ID của mình vào `user_id`** (`ctx["id"]`); chỉ dùng ID người khác cho `followee_id`.
3. Thích trùng bài, theo dõi trùng hoặc tự theo dõi chính mình sẽ báo lỗi; nếu chưa chắc trạng thái hãy `view_post` kiểm tra trước.

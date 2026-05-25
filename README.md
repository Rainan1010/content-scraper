# Content scraper

Script Python cào tin tức tự động từ các trang tin tức và lưu trữ trên Firebase Firestore & Storage.

## Tính năng
- Tự động lấy bài viết mới.
- Tự động bắt ảnh thumbnail và ảnh bài viết, sau đó upload lên Firebase Storage.
- Lưu dữ liệu bài viết (title, content, author, reading time...) vào Firestore theo đúng schema.
- Dùng Github Actions chạy định kì 3 tiếng / lần.

## Cài đặt trên Github
Để Github Action hoạt động, thêm 2 Secret sau vào mục Settings > Secrets and variables > Actions:
1. `FIREBASE_CREDENTIALS`: Nội dung file `firebase-key.json` của bạn.
2. `FIREBASE_STORAGE_BUCKET`: `newsapp-4b2e0.appspot.com` (Tên bucket của bạn).
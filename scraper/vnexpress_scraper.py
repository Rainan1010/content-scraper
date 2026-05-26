import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore, storage
import uuid
import os
from datetime import datetime, timezone
import math
import random
from dotenv import load_dotenv

# Tự động load biến môi trường từ file .env
load_dotenv()

# Headers giả lập trình duyệt
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def init_firebase():
    if not firebase_admin._apps:
        # Nếu chạy trên Github Actions, load từ biến môi trường
        firebase_cred_json = os.environ.get('FIREBASE_CREDENTIALS')
        if firebase_cred_json:
            import json
            cred_dict = json.loads(firebase_cred_json)
            cred = credentials.Certificate(cred_dict)
        else:
            # Fallback chạy local
            key_path = os.environ.get('FIREBASE_KEY_PATH', 'firebase-key.json')
            if os.path.exists(key_path):
                cred = credentials.Certificate(key_path)
            else:
                raise ValueError("Không tìm thấy Firebase Credentials!")

        firebase_admin.initialize_app(cred, {
            'storageBucket': os.environ.get('FIREBASE_STORAGE_BUCKET', 'newsapp-4b2e0.firebasestorage.app') # Thay bằng bucket thực tế
        })
    return firestore.client(), storage.bucket()

try:
    db, bucket = init_firebase()
except Exception as e:
    print(f"Lỗi khởi tạo Firebase: {e}")
    db, bucket = None, None

def is_duplicate(url):
    if not db: return False
    try:
        docs = db.collection('articles').where('sourceUrl', '==', url).limit(1).get(timeout=10)
        return len(docs) > 0
    except Exception as e:
        print(f"Lỗi kiểm tra trùng lặp cho {url}: {e}")
        return False

def upload_img(url, folder_name, default_ext='jpg'):
    if not bucket or not url.startswith('http'): return url
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            ext = url.split('.')[-1].split('?')[0]
            if not ext or len(ext) > 4: ext = default_ext
            path = f"articles/{folder_name}/{uuid.uuid4().hex}.{ext}"
            blob = bucket.blob(path)
            blob.upload_from_string(res.content, content_type=res.headers.get('Content-Type', f'image/{ext}'))
            blob.make_public()
            return blob.public_url
    except Exception as e:
        print(f"Lỗi upload ảnh {url}: {e}")
    return url

def save_category(category_id, category_name):
    if not db: return
    try:
        doc_ref = db.collection('categories').document(category_id)
        doc_ref.set({
            'id': category_id,
            'name': category_name,
            'updatedAt': firestore.SERVER_TIMESTAMP
        }, merge=True)
    except Exception as e:
        print(f"Lỗi lưu category {category_name}: {e}")


def get_vnexpress_links():
    url = "https://vnexpress.net/tin-tuc-24h"
    try:
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, 'html.parser')
        links = []
        for item in soup.select('h3.title-news a'):
            href = item.get('href')
            if href and href.startswith('https://vnexpress.net') and '.html' in href:
                links.append(href)
        return list(set(links))
    except Exception as e:
        print(f"Lỗi lấy danh sách bài viết VNExpress: {e}")
        return []

def scrape_article(url):
    if is_duplicate(url):
        print(f"[-] Bỏ qua (Đã tồn tại): {url}")
        return

    doc_id = url.split('/')[-1].replace('.html', '')
    print(f"[*] Đang cào: {url}")
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title_tag = soup.select_one('h1.title-detail')
        desc_tag = soup.select_one('p.description')
        content_tag = soup.select_one('article.fck_detail')
        
        if not content_tag or not title_tag:
            print(f"[!] Bỏ qua do không đúng cấu trúc bài viết: {url}")
            return

        title = title_tag.get_text(strip=True)
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # Lấy Category từ Breadcrumb
        category_name = "Tin tức"
        category_id = "tin-tuc"
        breadcrumb = soup.select_one('ul.breadcrumb li a')
        if breadcrumb:
            category_name = breadcrumb.get_text(strip=True)
            href = breadcrumb.get('href', '')
            category_id = href.strip('/').split('/')[-1] if href else "tin-tuc"
            
        # Tự động lưu/cập nhật category vào collection categories
        save_category(category_id, category_name)

        # Tác giả
        author_name = ""
        author_tag = soup.select_one('p.author_mail strong, article.fck_detail p[style*="text-align:right"] strong')
        if author_tag:
            author_name = author_tag.get_text(strip=True)

        # Lấy Thumbnail từ thẻ meta og:image
        meta_img = soup.select_one('meta[property="og:image"]')
        thumbnail_url = meta_img.get('content') if meta_img else ""
        if thumbnail_url:
            thumbnail_url = upload_img(thumbnail_url, doc_id)

        # Dọn dẹp HTML rác
        for trash in content_tag.find_all(['video', 'iframe', 'script', 'style', 'div.box_tinlienquan']):
            trash.decompose()

        # Xử lý nội dung ảnh
        image_urls = []
        for img in content_tag.find_all('img'):
            original_src = img.get('data-src') or img.get('src')
            if original_src and original_src.startswith('http'):
                new_url = upload_img(original_src, doc_id)
                img['src'] = new_url
                image_urls.append(new_url)
                for attr in ['data-src', 'srcset', 'class', 'sizes']:
                    if img.has_attr(attr): del img[attr]
        
        # Tính readingTime ước lượng (trung bình 200 từ/phút)
        text_content = content_tag.get_text()
        word_count = len(text_content.split())
        reading_time = max(1, math.ceil(word_count / 200))

        # Build Document
        now = datetime.now(timezone.utc)
        
        data = {
            "title": title,
            "description": description,
            "content": str(content_tag),
            "source": "VnExpress",
            "sourceUrl": url,
            "categoryId": category_id,
            "categoryName": category_name,
            "author": author_name,
            "thumbnailUrl": thumbnail_url,
            "imageUrls": image_urls,
            "readingTime": reading_time,
            "publishedAt": now,
            "createdAt": now,
            "viewCount": random.randint(10, 999),
            "bookmarkCount": 0,
            "isFeatured": False,
            "isTrending": False
        }
        
        if db:
            db.collection('articles').document(doc_id).set(data)
            print(f"[+] Thành công: {title[:50]}... -> Category: {category_name}")
        else:
            print(f"[!] Database lỗi, data: {title[:50]}")

    except Exception as e:
        print(f"[!] Lỗi khi cào {url}: {e}")

if __name__ == "__main__":
    print("=== BẮT ĐẦU CÀO VNEXPRESS 24H ===")
    links = get_vnexpress_links()
    print(f"Tìm thấy {len(links)} link bài viết.")
    
    # Cào tối đa 10 bài mới nhất mỗi lần chạy để tránh quá tải
    for link in links[:10]:
        scrape_article(link)
    
    print("=== HOÀN TẤT ===")

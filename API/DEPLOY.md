# Deploy

## Kiến trúc

```
[Internet] → Caddy (HTTPS) ─┬→ /api/*  → backend :8080 (FastAPI)
                            └→ /*      → frontend :3000 (Next.js)
backend → db :5432 (PostgreSQL: users + sessions)
backend → chat2api :5005 (LLM, ChatGPT token)
Dữ liệu jobs/banks: file trong ./runs và ./data (mount volume)
```

- Đăng nhập: tài khoản `ADMIN_USERNAME`/`ADMIN_PASSWORD` trong `.env`, backend
  tự seed khi khởi động. Đổi `ADMIN_PASSWORD` rồi restart backend = đổi mật khẩu
  (mọi phiên đăng nhập cũ bị hủy).
- Hai file compose:
  - `docker-compose.yml` — chạy local (backend :8082 + db; frontend chạy `npm run dev`,
    chat2api là container có sẵn trên máy).
  - `docker-compose.prod.yml` — chạy VPS (đủ stack: Caddy + frontend + backend + db + chat2api).

## Deploy lên VPS

1. VPS Linux (≥2GB RAM) đã cài Docker + Docker Compose; trỏ DNS A record của
   domain về IP VPS.
2. Copy thư mục `API/` lên VPS, **kèm file `.env`** (không nằm trong git).
   Trong `.env` đặt `ADMIN_PASSWORD`, `POSTGRES_PASSWORD` mạnh.
3. Sửa domain trong `Caddyfile` (thay `aqg.example.com`). Chưa có domain thì
   dùng `:80` để chạy HTTP qua IP (không có HTTPS).
4. Chạy:

   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

5. Nạp token chat2api (bắt buộc trước lần sinh câu hỏi đầu tiên, và **renew
   ~10 ngày/lần** vì token ChatGPT hết hạn):

   ```bash
   # từ máy cá nhân
   ssh -L 5005:127.0.0.1:5005 user@vps
   # rồi mở http://127.0.0.1:5005/tokens và dán access token ChatGPT
   ```

   Backend báo lỗi 401 từ LLM = token hết hạn.

## Vận hành

- Log: `docker compose -f docker-compose.prod.yml logs -f backend`
- Cập nhật code: pull/copy code mới rồi `up -d --build` lại.
- **Backup**: chỉ cần 2 thư mục `runs/` (jobs) và `data/` (ngân hàng câu hỏi).
  DB chỉ chứa tài khoản/phiên — mất cũng chỉ cần đăng nhập lại.
- Frontend nướng `NEXT_PUBLIC_API_URL=/api` lúc build image; nếu tách frontend
  sang domain khác thì build lại với `--build-arg NEXT_PUBLIC_API_URL=https://api.…`
  và đặt `CORS_ORIGINS=https://frontend-domain` cho backend.

## Chuyển sang OpenAI thật (khuyên dùng khi chạy lâu dài)

chat2api dùng token ChatGPT cá nhân — chỉ hợp demo/đồ án. Muốn ổn định:
trong `.env` đổi

```
OPENAI_COMPATIBLE_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...   # key thật
```

xoá override `OPENAI_COMPATIBLE_BASE_URL` trong compose (service backend),
bỏ service `chat2api`, rồi `up -d` lại.

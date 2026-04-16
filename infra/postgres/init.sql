-- Chạy 1 lần khi khởi tạo database lần đầu

-- Extension UUID (dùng cho gen task_id nếu cần server-side)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Extension pg_trgm (full-text search sau này nếu cần)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- SQL скрипт для создания базы данных и таблицы подарков

-- Создание базы данных (если не существует)
CREATE DATABASE IF NOT EXISTS portals_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Использование базы данных
USE portals_bot;

-- Создание таблицы подарков (будет создана автоматически ботом, но можно создать вручную)
CREATE TABLE IF NOT EXISTS gifts (
    name VARCHAR(255) NOT NULL,
    model VARCHAR(255),
    price FLOAT DEFAULT 0,
    floor_price FLOAT DEFAULT 0,
    photo_url TEXT,
    model_rarity VARCHAR(50),
    user_id BIGINT NOT NULL,
    PRIMARY KEY (user_id, name(255), model(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


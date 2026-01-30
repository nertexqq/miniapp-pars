# Multi-stage build
FROM python:3.11-slim as builder

WORKDIR /app

# Установка зависимостей для сборки
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Копируем установленные пакеты
COPY --from=builder /root/.local /root/.local

# Копируем код
COPY src/ ./src/
COPY .env* ./

# Устанавливаем PATH
ENV PATH=/root/.local/bin:$PATH

# Запуск
CMD ["python", "-m", "src.bot.main"]



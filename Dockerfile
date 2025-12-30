# Используем стабильную версию Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Чтобы Python не создавал .pyc файлы и выводил логи сразу
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# !!! ВОТ ОНО, ИСПРАВЛЕНИЕ !!!
# Добавляем корневую директорию проекта в путь поиска модулей Python
ENV PYTHONPATH /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install -r requirements.txt

# Копируем все файлы проекта в контейнер
COPY . .

# Команда для запуска нашего приложения
CMD ["python", "main.py"]
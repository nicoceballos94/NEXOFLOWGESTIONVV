FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

# En prod se reemplaza por gunicorn (ver README); en dev docker-compose pisa el comando.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]

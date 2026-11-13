FROM python:3.12-slim
WORKDIR /app
COPY plataforma/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY comun /app/comun
COPY plataforma/granja_iot /app/plataforma/granja_iot
COPY plataforma/web /app/plataforma/web
WORKDIR /app/plataforma
EXPOSE 8000
CMD ["uvicorn", "granja_iot.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

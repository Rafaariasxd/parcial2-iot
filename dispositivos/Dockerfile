FROM python:3.12-slim
WORKDIR /app
COPY dispositivos/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY comun /app/comun
COPY datos /app/datos
COPY dispositivos/granja_dispositivos /app/dispositivos/granja_dispositivos
WORKDIR /app/dispositivos
ENV CARPETA_ESTADO=/app/estado PYTHONUNBUFFERED=1
CMD ["python", "-m", "granja_dispositivos.principal"]

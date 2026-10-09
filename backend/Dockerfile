FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 YOLO_CONFIG_DIR=/service/runtime/ultralytics
WORKDIR /service
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /service/backend/requirements.txt
RUN pip install torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu && pip install -r /service/backend/requirements.txt
RUN useradd --create-home --uid 10001 ember && mkdir -p /service/runtime/spread-jobs && chown -R ember:ember /service/runtime
COPY --chown=ember:ember backend /service/backend
COPY --chown=ember:ember models/fire_policy_v1.json /service/models/fire_policy_v1.json
COPY --chown=ember:ember samples /service/samples
USER ember
WORKDIR /service/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --start-period=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready')"
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1","--no-access-log"]

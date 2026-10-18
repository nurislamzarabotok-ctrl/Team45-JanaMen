FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server.py platform_service.py assistant_service.py ai_config.py ai_transport.py ai_knowledge.py gemini_transport.py /app/
COPY scripts /app/scripts
COPY static /app/static
ENV JANA_BIND=0.0.0.0
EXPOSE 8000
CMD ["python", "server.py", "--no-browser"]

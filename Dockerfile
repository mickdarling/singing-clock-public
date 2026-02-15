FROM python:3.12-slim

WORKDIR /app
COPY *.py *.html *.json ./

RUN useradd -m -u 1000 clockuser && \
    chown -R clockuser:clockuser /app
USER clockuser

EXPOSE 8080
CMD ["python3", "server.py", "--bind-all"]

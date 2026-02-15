FROM python:3.12-slim

WORKDIR /app
COPY scan.py server.py index.html config.example.json ./

EXPOSE 8080
CMD ["python3", "server.py", "--bind-all"]

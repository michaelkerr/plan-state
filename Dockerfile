FROM python:3.13-slim

WORKDIR /app

COPY mcp-server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY plansync/ ./plansync/
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY mcp-server/ ./mcp-server/
COPY sync/ ./sync/
COPY init-db.py ./

EXPOSE 8082

CMD ["python3", "mcp-server/server.py"]

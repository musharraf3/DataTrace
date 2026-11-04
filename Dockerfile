FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml requirements.txt README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir .
COPY app.py ./
COPY examples ./examples
COPY results ./results
COPY .streamlit/config.toml ./.streamlit/config.toml
ENV DATATRACE_PUBLIC_DEMO=1
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.headless=true"]

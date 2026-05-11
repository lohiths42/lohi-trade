# LOHI-TRADE Setup Guide

## Virtual Environment Setup

### Environment Details
- **Virtual Environment Name**: `lohi_trade_venv`
- **Python Version**: 3.14.2
- **Location**: `./lohi_trade_venv/`

### Activation Commands

**Activate the virtual environment:**
```bash
source lohi_trade_venv/bin/activate
```

**Deactivate when done:**
```bash
deactivate
```

## Installed Packages

All dependencies from `requirements.txt` have been successfully installed, including:

### Core Trading & Data
- pandas 2.3.3
- numpy 2.3.5
- ta-lib 0.6.8 (for technical indicators)
- vectorbt 0.28.4 (for backtesting)
- yfinance 1.1.0 (for historical data)

### Database & Caching
- redis 7.1.0
- hiredis 3.3.0
- duckdb 1.4.4

### Web Framework
- streamlit 1.54.0
- fastapi 0.128.6
- uvicorn 0.40.0
- websockets 16.0

### AI/ML Libraries
- torch 2.10.0
- transformers 5.1.0
- onnxruntime 1.24.1
- sentencepiece 0.2.1

### NLP (Note: spaCy has compatibility issues with Python 3.14)
- spacy 3.8.11 (installed but not fully functional)

### Utilities
- python-telegram-bot 22.6
- feedparser 6.0.12
- beautifulsoup4 4.14.3
- lxml 6.0.2
- requests 2.32.5
- rapidfuzz 3.14.3

### Testing
- pytest 9.0.2
- pytest-asyncio 1.3.0
- pytest-mock 3.15.1
- pytest-cov 7.0.0
- hypothesis 6.151.5

### Development Tools
- mypy 1.19.1
- black 26.1.0
- ruff 0.15.0

## Known Issues

### 1. pandas-ta Compatibility
**Issue**: `pandas-ta` requires `numba` which doesn't support Python 3.14 yet.

**Workaround**: Using `ta-lib` instead for technical indicators.

**Alternative**: You can implement indicators manually or wait for numba to support Python 3.14.

### 2. spaCy Compatibility
**Issue**: spaCy has Pydantic v1 compatibility issues with Python 3.14.

**Error**: `pydantic.v1.errors.ConfigError: unable to infer type for attribute "REGEX"`

**Workarounds**:
1. Use alternative NER libraries (e.g., `transformers` with NER models)
2. Downgrade to Python 3.11 or 3.12 for full spaCy support
3. Wait for spaCy to release Python 3.14 compatible version

### 3. Broker APIs
**Note**: Shoonya and Angel One broker APIs may need manual installation as they might not be available on PyPI.

## Next Steps

1. **spaCy model**: `lohi setup` will try to download `en_core_web_sm` automatically and will warn if it cannot.

2. **Install broker APIs** (if available):
   ```bash
   pip install shoonya-api
   pip install angelone-api
   ```

3. **Set up environment variables**:
   Create a `.env` file with:
   ```
   SHOONYA_API_KEY=your_key
   SHOONYA_CLIENT_ID=your_client_id
   SHOONYA_PASSWORD=your_password
   
   ANGELONE_API_KEY=your_key
   ANGELONE_CLIENT_ID=your_client_id
   ANGELONE_PASSWORD=your_password
   
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

4. **Start Redis** (required for event bus):
   ```bash
   docker-compose up -d redis
   ```

5. **Create project structure**:
   ```bash
   mkdir -p src/{ingestion,processing,execution,state}
   mkdir -p tests data/{logs,backups} config scripts notebooks
   ```

## Verification

Test your installation:
```bash
source lohi_trade_venv/bin/activate
python -c "import pandas, numpy, redis, streamlit, torch; print('All core packages imported successfully!')"
```

## Alternative: Use Python 3.11 or 3.12

If you need full compatibility with all libraries (especially spaCy and pandas-ta), consider using Python 3.11 or 3.12:

```bash
# Create new venv with Python 3.11/3.12
python3.11 -m venv lohi_trade_venv_py311
source lohi_trade_venv_py311/bin/activate
pip install lohi-trade
lohi setup
```

## Support

For issues or questions:
- Check the project documentation in `.kiro/specs/lohi-trade/`
- Review the design document for architecture details
- Consult the requirements document for feature specifications

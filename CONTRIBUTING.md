# Contributing to Archmorph

Thank you for your interest in contributing to Archmorph!

## Development Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in your Azure OpenAI credentials
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env  # Set VITE_API_BASE
npm run dev
```

### Running Tests

```bash
# Backend
cd backend && python -m pytest -v

# Frontend
cd frontend && npm test
```

## Code Quality

- **Python**: We use [ruff](https://docs.astral.sh/ruff/) for linting and [bandit](https://bandit.readthedocs.io/) for security scanning.
- **JavaScript/React**: Standard ESLint configuration via Vite.

Run linters before submitting:
```bash
cd backend && ruff check . && bandit -r . -x ./tests --skip B101
```

## Pull Request Process

1. Fork the repository and create a feature branch from `main`.
2. Make your changes with clear, descriptive commits.
3. Ensure all tests pass (`pytest` and `npm run build`).
4. Update documentation if you change APIs or add features.
5. Submit a PR against `main` with a clear description.

## Architecture

- **Backend**: FastAPI (Python 3.11), Azure OpenAI GPT-4o for vision/chat
- **Frontend**: React 18, Vite 5, TailwindCSS 3.4
- **Infrastructure**: Azure Container Apps, Azure Static Web Apps, ACR
- **CI/CD**: GitHub Actions → ACR → Container Apps

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/services/catalog` | List all cloud services |
| POST | `/api/projects/{id}/diagrams` | Upload architecture diagram |
| POST | `/api/diagrams/{id}/analyze` | Analyze with GPT-4o vision |
| POST | `/api/diagrams/{id}/questions` | Get guided migration questions |
| POST | `/api/diagrams/{id}/answers` | Submit answers |
| POST | `/api/diagrams/{id}/iac/generate` | Generate Terraform/Bicep |
| POST | `/api/diagrams/{id}/iac/chat` | IaC chat assistant |
| POST | `/api/diagrams/{id}/hld` | Generate HLD document |
| GET | `/api/diagrams/{id}/cost-estimate` | Azure cost estimation |
| POST | `/api/diagrams/{id}/export-diagram` | Export to Excalidraw/Draw.io |
| POST | `/api/chatbot/message` | General chatbot |
| GET | `/api/admin/metrics` | Admin analytics (requires X-Admin-Key header) |
| POST | `/api/service-updates/run-now` | Trigger service catalog update |
| GET | `/api/contact` | Contact info |

## License

This project is proprietary. See the repository for details.

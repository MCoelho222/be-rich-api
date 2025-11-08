# Be Rich API

A professional FastAPI backend for user and financial entry management.

## Features

- User CRUD endpoints
- Financial entry CRUD endpoints
- SQLModel ORM with UUID primary keys
- Alembic migrations
- Pytest test suite (uses SQLite in-memory for isolation)
- CORS support for frontend integration

## Project Structure

```text
be-rich-api/
├── app/
│   ├── models/
│   ├── routes/
│   ├── connection_db.py
│   └── ...
├── tests/
│   ├── test_users.py
│   ├── test_entries.py
│   └── conftest.py
├── main.py
├── alembic/
├── requirements.txt
└── README.md
```

## Setup

### 🐳 Docker Development (Recommended)

1. Configure environment variables in `.env` file:

   ```bash
   cp .env.example .env  # Create your .env file
   ```

2. Start the development environment:

   ```bash
   docker-compose up --build
   ```

   This will automatically:

   - Start PostgreSQL database
   - Wait for database to be ready
   - Run Alembic migrations (`alembic upgrade head`)
   - Start FastAPI with hot reload

### 🐍 Local Development

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables as needed.

3. Run Alembic migrations:

   ```bash
   alembic upgrade head
   ```

4. Start the API server:

   ```bash
   uvicorn main:app --reload
   ```

## Testing

Run all tests:

```bash
pytest
```

## API Endpoints

- `/users/` : User management
- `/entries/` : Financial entry management

## License

MIT License

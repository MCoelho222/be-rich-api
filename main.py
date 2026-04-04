from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.users import router as users_router
from app.routes.incomes import router as incomes_router
from app.routes.expenses import router as expenses_router

app = FastAPI()

# Configure CORS
origins = [
    "http://localhost:3000",  # Next.js frontend URL
    # Add other origins if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,            # Allow specific origins
    allow_credentials=True,           # Allow cookies, authorization headers
    allow_methods=["*"],              # Allow all HTTP methods
    allow_headers=["*"],              # Allow all headers
)

app.include_router(users_router, prefix="/users")
app.include_router(incomes_router, prefix="/incomes")
app.include_router(expenses_router, prefix="/expenses")
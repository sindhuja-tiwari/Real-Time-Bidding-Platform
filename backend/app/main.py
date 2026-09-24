import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import RTBException, rtb_exception_handler, unhandled_exception_handler
from app.core.kafka_client import stop_producer
from app.core.logging import configure_logging, get_logger, request_id_var

settings = get_settings()
configure_logging(settings.ENV)
logger = get_logger(__name__)

app = FastAPI(
    title="RTB Platform",
    description="Simplified real-time bidding / programmatic advertising auction platform.",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for real deployments; see docs/architecture.md
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Attaches a request_id to every request for structured-log correlation
    (Section 17 of the spec) even for endpoints that don't set one themselves."""
    incoming = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_var.set(incoming)
    response = await call_next(request)
    response.headers["X-Request-ID"] = incoming
    return response


app.add_exception_handler(RTBException, rtb_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": settings.APP_NAME, "env": settings.ENV}


@app.on_event("shutdown")
async def shutdown_event():
    await stop_producer()
    logger.info("app_shutdown")

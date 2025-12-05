"""
Database Module for Inference Service

Provides database connection and model definitions for server and model tracking.
"""
import os
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

# Configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "inference_db")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

Base = declarative_base()


class ServerRecord(Base):
    """
    Server status and tracking table.
    Stores information about each model server instance.
    """
    __tablename__ = "server_records"
    
    # Primary identifier
    uuid = Column(String(255), primary_key=True, index=True)
    
    # Model reference
    model_uuid = Column(String(255), index=True)  # Reference to model_records
    model_name = Column(String(255), nullable=False)
    
    # Runtime parameters
    runtime_params = Column(JSON, default={})
    
    # Status tracking
    status = Column(String(50), default="starting")  # starting, running, stopped, error
    
    # Resource usage
    memory_usage_mb = Column(Integer, default=0)
    memory_max_mb = Column(Integer, default=0)
    cpu_usage_percent = Column(Float, default=0.0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Kubernetes identifiers
    pod_name = Column(String(255))
    service_name = Column(String(255))
    namespace = Column(String(255), default="default")
    
    # Gateway URL
    endpoint = Column(String(512))
    gateway_url = Column(String(512))


class ModelRecord(Base):
    """
    Model metadata and tracking table.
    Stores information about each model available for serving.
    """
    __tablename__ = "model_records"
    
    # Primary identifier (UUID from quant service)
    uuid = Column(String(255), primary_key=True, index=True)
    
    # Model information
    model_name = Column(String(255), nullable=False, index=True)
    hf_name = Column(String(255))  # Original HuggingFace model name
    
    # Storage paths
    minio_path = Column(String(512))  # Internal MinIO path
    external_source_id = Column(Integer)  # ID from Quant service
    
    # Quantization metadata
    quant_level = Column(String(50))
    file_size_bytes = Column(Integer)
    
    # Additional metadata (renamed from 'metadata' which is reserved in SQLAlchemy)
    model_metadata = Column(JSON, default={})
    
    # Status
    status = Column(String(50), default="downloading")  # downloading, ready, error
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    downloaded_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# Engine and session
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    """Get a database session."""
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    print("Database tables initialized")


def get_server_by_uuid(db, uuid: str) -> Optional[ServerRecord]:
    """Get a server record by UUID."""
    return db.query(ServerRecord).filter(ServerRecord.uuid == uuid).first()


def get_model_by_uuid(db, uuid: str) -> Optional[ModelRecord]:
    """Get a model record by UUID."""
    return db.query(ModelRecord).filter(ModelRecord.uuid == uuid).first()


def get_model_by_name(db, model_name: str) -> Optional[ModelRecord]:
    """Get the latest ready model by name."""
    return db.query(ModelRecord).filter(
        ModelRecord.model_name == model_name,
        ModelRecord.status == "ready"
    ).order_by(ModelRecord.created_at.desc()).first()


def create_server_record(
    db,
    uuid: str,
    model_uuid: str,
    model_name: str,
    runtime_params: dict = None,
    namespace: str = "default"
) -> ServerRecord:
    """Create a new server record."""
    server = ServerRecord(
        uuid=uuid,
        model_uuid=model_uuid,
        model_name=model_name,
        runtime_params=runtime_params or {},
        namespace=namespace,
        status="starting"
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return server


def create_model_record(
    db,
    uuid: str,
    model_name: str,
    minio_path: str,
    external_source_id: int = None,
    hf_name: str = None,
    quant_level: str = None,
    file_size_bytes: int = None,
    model_metadata: dict = None
) -> ModelRecord:
    """Create a new model record."""
    model = ModelRecord(
        uuid=uuid,
        model_name=model_name,
        hf_name=hf_name,
        minio_path=minio_path,
        external_source_id=external_source_id,
        quant_level=quant_level,
        file_size_bytes=file_size_bytes,
        model_metadata=model_metadata or {},
        status="downloading"
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def update_server_status(
    db,
    uuid: str,
    status: str,
    memory_usage_mb: int = None,
    cpu_usage_percent: float = None,
    pod_name: str = None,
    service_name: str = None,
    endpoint: str = None,
    gateway_url: str = None
):
    """Update server status and metrics."""
    server = db.query(ServerRecord).filter(ServerRecord.uuid == uuid).first()
    if server:
        server.status = status
        if memory_usage_mb is not None:
            server.memory_usage_mb = memory_usage_mb
            if memory_usage_mb > server.memory_max_mb:
                server.memory_max_mb = memory_usage_mb
        if cpu_usage_percent is not None:
            server.cpu_usage_percent = cpu_usage_percent
        if pod_name:
            server.pod_name = pod_name
        if service_name:
            server.service_name = service_name
        if endpoint:
            server.endpoint = endpoint
        if gateway_url:
            server.gateway_url = gateway_url
        if status == "running" and not server.started_at:
            server.started_at = datetime.utcnow()
        db.commit()


def update_model_status(
    db,
    uuid: str,
    status: str,
    minio_path: str = None
):
    """Update model status."""
    model = db.query(ModelRecord).filter(ModelRecord.uuid == uuid).first()
    if model:
        model.status = status
        if minio_path:
            model.minio_path = minio_path
        if status == "ready":
            model.downloaded_at = datetime.utcnow()
        db.commit()

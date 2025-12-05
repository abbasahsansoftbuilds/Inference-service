"""
MinIO Client Module for Inference Service

Provides MinIO operations for model storage and retrieval.
"""
import os
from datetime import timedelta
from typing import Optional
from minio import Minio
from minio.error import S3Error


# Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
BUCKET_NAME = os.getenv("BUCKET_NAME", "inference-models")


def get_minio_client() -> Minio:
    """Get a configured MinIO client."""
    return Minio(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE
    )


def init_bucket(client: Optional[Minio] = None, bucket_name: Optional[str] = None):
    """
    Initialize the bucket if it doesn't exist.
    
    Args:
        client: MinIO client instance (uses default if None)
        bucket_name: Bucket name (uses default if None)
    """
    if client is None:
        client = get_minio_client()
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    try:
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
            print(f"Created bucket: {bucket_name}")
    except S3Error as e:
        print(f"Error initializing bucket: {e}")
        raise


def upload_file(
    file_path: str, 
    object_name: str,
    client: Optional[Minio] = None,
    bucket_name: Optional[str] = None
):
    """
    Upload a file to MinIO.
    
    Args:
        file_path: Local path to the file
        object_name: Name of the object in MinIO
        client: MinIO client instance
        bucket_name: Target bucket name
    """
    if client is None:
        client = get_minio_client()
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    client.fput_object(bucket_name, object_name, file_path)


def download_file(
    object_name: str,
    file_path: str,
    client: Optional[Minio] = None,
    bucket_name: Optional[str] = None
):
    """
    Download a file from MinIO.
    
    Args:
        object_name: Name of the object in MinIO
        file_path: Local path to save the file
        client: MinIO client instance
        bucket_name: Source bucket name
    """
    if client is None:
        client = get_minio_client()
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    client.fget_object(bucket_name, object_name, file_path)


def get_presigned_url(
    object_name: str,
    expires_seconds: int = 3600,
    client: Optional[Minio] = None,
    bucket_name: Optional[str] = None
) -> str:
    """
    Generate a presigned URL for downloading an object.
    
    Args:
        object_name: Name of the object in MinIO
        expires_seconds: URL expiry time in seconds
        client: MinIO client instance
        bucket_name: Source bucket name
    
    Returns:
        Presigned URL string
    """
    if client is None:
        client = get_minio_client()
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    return client.presigned_get_object(
        bucket_name,
        object_name,
        expires=timedelta(seconds=expires_seconds)
    )


def file_exists(
    object_name: str,
    client: Optional[Minio] = None,
    bucket_name: Optional[str] = None
) -> bool:
    """
    Check if a file exists in MinIO.
    
    Args:
        object_name: Name of the object in MinIO
        client: MinIO client instance
        bucket_name: Source bucket name
    
    Returns:
        True if file exists, False otherwise
    """
    if client is None:
        client = get_minio_client()
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    try:
        client.stat_object(bucket_name, object_name)
        return True
    except S3Error:
        return False


def get_file_size(
    object_name: str,
    client: Optional[Minio] = None,
    bucket_name: Optional[str] = None
) -> Optional[int]:
    """
    Get the size of a file in MinIO.
    
    Args:
        object_name: Name of the object in MinIO
        client: MinIO client instance
        bucket_name: Source bucket name
    
    Returns:
        File size in bytes, or None if file doesn't exist
    """
    if client is None:
        client = get_minio_client()
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    try:
        stat = client.stat_object(bucket_name, object_name)
        return stat.size
    except S3Error:
        return None


def list_files(
    prefix: str = "",
    client: Optional[Minio] = None,
    bucket_name: Optional[str] = None
) -> list:
    """
    List files in MinIO bucket.
    
    Args:
        prefix: Filter files by prefix
        client: MinIO client instance
        bucket_name: Source bucket name
    
    Returns:
        List of object names
    """
    if client is None:
        client = get_minio_client()
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    objects = client.list_objects(bucket_name, prefix=prefix, recursive=True)
    return [obj.object_name for obj in objects]


def delete_file(
    object_name: str,
    client: Optional[Minio] = None,
    bucket_name: Optional[str] = None
):
    """
    Delete a file from MinIO.
    
    Args:
        object_name: Name of the object in MinIO
        client: MinIO client instance
        bucket_name: Source bucket name
    """
    if client is None:
        client = get_minio_client()
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    client.remove_object(bucket_name, object_name)

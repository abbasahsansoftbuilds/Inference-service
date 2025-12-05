"""
JWT Authentication Module for Inference Service

Provides token generation and verification for service-to-service
and user-to-service authentication.
"""
import os
from datetime import datetime, timedelta
from typing import Optional
import jwt
from fastapi import HTTPException, Header


# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "inference-service-jwt-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))


def create_access_token(
    subject: str,
    token_type: str = "access",
    additional_claims: Optional[dict] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.
    
    Args:
        subject: The subject of the token (user_id or service_id)
        token_type: Type of token ('access', 'service', 'refresh')
        additional_claims: Additional claims to include in the token
        expires_delta: Custom expiration time
    
    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRY_HOURS)
    
    expire = datetime.utcnow() + expires_delta
    
    payload = {
        "sub": subject,
        "iss": "inference-service",
        "iat": datetime.utcnow(),
        "exp": expire,
        "type": token_type
    }
    
    if additional_claims:
        payload.update(additional_claims)
    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(authorization: str = Header(...)) -> dict:
    """
    Verify JWT token from Authorization header.
    
    Args:
        authorization: Authorization header value (Bearer <token>)
    
    Returns:
        Decoded token payload
    
    Raises:
        HTTPException: If token is invalid or expired
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, 
            detail="Invalid authorization header format. Expected 'Bearer <token>'"
        )
    
    token = authorization.split(" ")[1]
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


def create_service_token(service_id: str, target_service: str) -> str:
    """
    Create a token for service-to-service communication.
    
    Args:
        service_id: ID of the calling service
        target_service: ID of the target service
    
    Returns:
        Service token string
    """
    return create_access_token(
        subject=service_id,
        token_type="service",
        additional_claims={"target": target_service},
        expires_delta=timedelta(hours=1)  # Short-lived for security
    )


def verify_service_token(authorization: str = Header(...)) -> dict:
    """
    Verify a service-to-service token.
    
    Args:
        authorization: Authorization header value
    
    Returns:
        Decoded token payload
    
    Raises:
        HTTPException: If token is invalid or not a service token
    """
    payload = verify_token(authorization)
    
    if payload.get("type") != "service":
        raise HTTPException(
            status_code=403, 
            detail="This endpoint requires a service token"
        )
    
    return payload

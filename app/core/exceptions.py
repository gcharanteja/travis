from typing import Any, Dict, List, Optional, Union
from fastapi import HTTPException, status
from pydantic import BaseModel

class ErrorResponse(BaseModel):
    """Standard error response model"""
    detail: str
    code: str = "error"
    fields: Optional[Dict[str, str]] = None

class BaseAPIException(HTTPException):
    """Base API exception class"""
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str = "error",
        fields: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={"detail": detail, "code": code, "fields": fields},
            headers=headers,
        )

class NotFoundException(BaseAPIException):
    """Exception raised when a resource is not found"""
    def __init__(
        self,
        detail: str = "Resource not found",
        code: str = "not_found",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
            code=code,
            fields=fields,
        )

class BadRequestException(BaseAPIException):
    """Exception raised for invalid request parameters"""
    def __init__(
        self,
        detail: str = "Invalid request parameters",
        code: str = "bad_request",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            code=code,
            fields=fields,
        )

class ValidationException(BaseAPIException):
    """Exception raised for validation errors"""
    def __init__(
        self,
        detail: str = "Validation error",
        code: str = "validation_error",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
            code=code,
            fields=fields,
        )

class UnauthorizedException(BaseAPIException):
    """Exception raised for authentication failures"""
    def __init__(
        self,
        detail: str = "Authentication required",
        code: str = "unauthorized",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            code=code,
            fields=fields,
            headers={"WWW-Authenticate": "Bearer"},
        )

class ForbiddenException(BaseAPIException):
    """Exception raised for authorization failures"""
    def __init__(
        self,
        detail: str = "Insufficient permissions",
        code: str = "forbidden",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            code=code,
            fields=fields,
        )

class InternalServerErrorException(BaseAPIException):
    """Exception raised for server errors"""
    def __init__(
        self,
        detail: str = "Internal server error",
        code: str = "server_error",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            code=code,
            fields=fields,
        )

class RateLimitException(BaseAPIException):
    """Exception raised when rate limit is exceeded"""
    def __init__(
        self,
        detail: str = "Rate limit exceeded",
        code: str = "rate_limit_exceeded",
        fields: Optional[Dict[str, str]] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        headers = {}
        if retry_after:
            headers["Retry-After"] = str(retry_after)
        
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            code=code,
            fields=fields,
            headers=headers,
        )

class DatabaseException(BaseAPIException):
    """Exception raised for database errors"""
    def __init__(
        self,
        detail: str = "Database error",
        code: str = "database_error",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            code=code,
            fields=fields,
        )

class ExternalAPIException(BaseAPIException):
    """Exception raised for errors in external API calls"""
    def __init__(
        self,
        detail: str = "External API error",
        code: str = "external_api_error",
        fields: Optional[Dict[str, str]] = None,
        status_code: int = status.HTTP_502_BAD_GATEWAY,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=detail,
            code=code,
            fields=fields,
        )

# Specific domain exceptions
class FinancialDataException(BadRequestException):
    """Exception for financial data errors"""
    def __init__(
        self,
        detail: str = "Invalid financial data",
        code: str = "financial_data_error",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(detail=detail, code=code, fields=fields)

class InvestmentException(BadRequestException):
    """Exception for investment operation errors"""
    def __init__(
        self,
        detail: str = "Investment operation failed",
        code: str = "investment_error",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(detail=detail, code=code, fields=fields)

class AIModelException(InternalServerErrorException):
    """Exception for AI/ML model errors"""
    def __init__(
        self,
        detail: str = "AI model processing failed",
        code: str = "ai_model_error",
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(detail=detail, code=code, fields=fields)
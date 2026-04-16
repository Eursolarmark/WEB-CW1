from __future__ import annotations

import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def _message_for_status(status_code: int) -> str:
    mapping = {
        status.HTTP_400_BAD_REQUEST: "Request validation failed.",
        status.HTTP_401_UNAUTHORIZED: "Authentication credentials are missing or invalid.",
        status.HTTP_403_FORBIDDEN: "You do not have permission to perform this action.",
        status.HTTP_404_NOT_FOUND: "Requested resource was not found.",
        status.HTTP_405_METHOD_NOT_ALLOWED: "HTTP method is not allowed for this endpoint.",
        status.HTTP_429_TOO_MANY_REQUESTS: "Rate limit exceeded. Please retry later.",
    }
    return mapping.get(status_code, "An unexpected error occurred.")


def _code_for_status(status_code: int) -> str:
    mapping = {
        status.HTTP_400_BAD_REQUEST: "validation_error",
        status.HTTP_401_UNAUTHORIZED: "authentication_failed",
        status.HTTP_403_FORBIDDEN: "permission_denied",
        status.HTTP_404_NOT_FOUND: "resource_not_found",
        status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    }
    return mapping.get(status_code, "internal_error")


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    request = context.get("request")
    request_id = getattr(request, "request_id", None) or uuid.uuid4().hex
    timestamp = timezone.now().isoformat()

    if response is None:
        return Response(
            {
                "code": "internal_error",
                "message": _message_for_status(status.HTTP_500_INTERNAL_SERVER_ERROR),
                "details": {"detail": "Internal server error."},
                "request_id": request_id,
                "timestamp": timestamp,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    payload = {
        "code": _code_for_status(response.status_code),
        "message": _message_for_status(response.status_code),
        "details": response.data,
        "request_id": request_id,
        "timestamp": timestamp,
    }
    response.data = payload
    return response

# OpenRepo is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License
# version 3 as published by the Free Software Foundation
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""
Custom DRF exception handler.

Wraps all DRF exceptions in the standard error envelope::

    {"code": "<ApiErrorCode>", "detail": "<message>", "status": <http_status_int>}

so that API clients can branch on ``code`` rather than parsing error strings
or inspecting HTTP status codes alone.
"""

from rest_framework import exceptions as drf_exceptions
from rest_framework.views import exception_handler as drf_exception_handler

from .errors import ApiErrorCode


# Map DRF exception types to (error_code, http_status) pairs.
# The http_status here is the *default* for that exception type; the actual
# status_code on the exception instance takes precedence.
_EXCEPTION_CODE_MAP = {
    drf_exceptions.ValidationError: ApiErrorCode.VALIDATION_ERROR,
    drf_exceptions.ParseError: ApiErrorCode.VALIDATION_ERROR,
    drf_exceptions.NotFound: ApiErrorCode.NOT_FOUND,
    drf_exceptions.AuthenticationFailed: ApiErrorCode.AUTHENTICATION_FAILED,
    drf_exceptions.NotAuthenticated: ApiErrorCode.AUTHENTICATION_FAILED,
    drf_exceptions.PermissionDenied: ApiErrorCode.PERMISSION_DENIED,
    drf_exceptions.MethodNotAllowed: ApiErrorCode.VALIDATION_ERROR,
    drf_exceptions.UnsupportedMediaType: ApiErrorCode.VALIDATION_ERROR,
    drf_exceptions.Throttled: ApiErrorCode.VALIDATION_ERROR,
}


def openrepo_exception_handler(exc, context):
    """
    Replace DRF's default exception handler with one that always returns the
    structured error envelope.
    """
    # Let DRF build the base response (handles non-API exceptions → None).
    response = drf_exception_handler(exc, context)

    if response is None:
        # Non-DRF exception — not our responsibility here.
        return None

    # Determine the error code.
    code = _EXCEPTION_CODE_MAP.get(type(exc), ApiErrorCode.SERVER_ERROR)

    # Extract a flat detail string from whatever DRF put in response.data.
    detail = _flatten_detail(response.data)

    response.data = {
        "code": code,
        "detail": detail,
        "status": response.status_code,
    }
    return response


def _flatten_detail(data):
    """
    Convert DRF's varied error data shapes into a single string.

    DRF can return:
    - ``{"detail": ErrorDetail(...)}``
    - ``{"field": [ErrorDetail(...)]}``  (ValidationError)
    - ``[ErrorDetail(...)]``
    - ``ErrorDetail(...)``
    """
    if isinstance(data, dict):
        if "detail" in data:
            return str(data["detail"])
        # Field-level validation errors — join them all.
        parts = []
        for field, errors in data.items():
            if isinstance(errors, list):
                parts.append(f"{field}: {'; '.join(str(e) for e in errors)}")
            else:
                parts.append(f"{field}: {errors}")
        return " | ".join(parts) if parts else str(data)
    if isinstance(data, list):
        return "; ".join(str(e) for e in data)
    return str(data)

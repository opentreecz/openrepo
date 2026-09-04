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
Structured API error codes and response helper.

All API error responses use the envelope::

    {"code": "<ApiErrorCode>", "detail": "<human-readable message>", "status": <http_status_int>}

This allows clients to branch on ``code`` rather than parsing error strings.
"""

from rest_framework.response import Response


class ApiErrorCode:
    PACKAGE_EXISTS = "PACKAGE_EXISTS"
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    INVALID_REPO_TYPE = "INVALID_REPO_TYPE"
    KEY_IN_USE = "KEY_IN_USE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    SERVER_ERROR = "SERVER_ERROR"


def api_error(code, detail, http_status_code):
    """Return a DRF Response with the standard error envelope."""
    return Response(
        {"code": code, "detail": detail, "status": http_status_code},
        status=http_status_code,
    )

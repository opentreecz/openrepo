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
Middleware that adds an ``X-OpenRepo-Version`` header to all API responses.

This lets clients discover the server version without parsing HTML or
fetching a dedicated endpoint.
"""

OPENREPO_API_VERSION = "2.5.0"


class VersionHeaderMiddleware:
    """Add ``X-OpenRepo-Version`` to every ``/api/`` response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["X-OpenRepo-Version"] = OPENREPO_API_VERSION
        return response

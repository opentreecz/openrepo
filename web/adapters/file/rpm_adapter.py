from datetime import datetime, timezone

import rpmfile
from dateutil import parser
from django.conf import settings

from .base_adapter import RepoFileAdapter


class RpmFileAdapter(RepoFileAdapter):

    def __init__(self, filepath, original_filename=None):
        super().__init__(filepath, original_filename)

        with rpmfile.open(self.filepath) as rpm:
            self.fields = {}
            for header in ("name", "version", "release", "arch", "group",
                           "size", "copyright", "signature", "sourcerpm",
                           "buildtime", "buildhost", "url", "summary",
                           "description"):
                value = rpm.headers.get(header)
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                if header == "buildtime":
                    value = datetime.fromtimestamp(value, tz=timezone.utc).strftime("%c")
                if header == "description":
                    value = "\n" + value
                self.fields[header] = value

    def get_name(self):
        return self.fields["name"]

    def get_architecture(self):
        return self.fields["arch"]

    def get_version(self):
        if settings.RPM_VERSION_IGNORE_BUILD_NUM:
            return self.fields["version"]
        else:
            return self.fields["version"] + "." + self.fields["release"]

    def get_description(self):
        return self.fields["description"]

    def get_builddate(self):
        return parser.parse(self.fields["buildtime"])

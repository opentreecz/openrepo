# Copyright 2022 by Open Kilt LLC. All rights reserved.
# This file is part of the OpenRepo Repository Management Software (OpenRepo)
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


from django_filters import rest_framework as df_filters

from repo.models import Build, BuildLogLine


class BuildFilter(df_filters.FilterSet):
    min_build = df_filters.NumberFilter(
        field_name="build_number", lookup_expr="gte",
        help_text="Minimum build number (inclusive).",
    )
    max_build = df_filters.NumberFilter(
        field_name="build_number", lookup_expr="lte",
        help_text="Maximum build number (inclusive).",
    )
    repo = df_filters.CharFilter(
        field_name="repo__repo_uid", lookup_expr="exact",
        help_text="Filter by repository UID.",
    )
    min_time = df_filters.DateTimeFilter(
        field_name="timestamp", lookup_expr="gte",
        help_text="Earliest build timestamp (ISO 8601).",
    )
    max_time = df_filters.DateTimeFilter(
        field_name="timestamp", lookup_expr="lte",
        help_text="Latest build timestamp (ISO 8601).",
    )

    class Meta:
        model = Build
        fields = ["build_number", "completion_status"]


class BuildLogFilter(df_filters.FilterSet):
    min_line = df_filters.NumberFilter(
        field_name="line_number", lookup_expr="gte",
        help_text="Minimum line number (inclusive).",
    )
    max_line = df_filters.NumberFilter(
        field_name="line_number", lookup_expr="lte",
        help_text="Maximum line number (inclusive).",
    )
    repo = df_filters.CharFilter(
        field_name="build__repo__repo_uid", lookup_expr="exact",
        help_text="Filter by repository UID.",
    )
    build = df_filters.NumberFilter(
        field_name="build__build_number", lookup_expr="exact",
        help_text="Filter by build number.",
    )
    min_time = df_filters.DateTimeFilter(
        field_name="timestamp", lookup_expr="gte",
        help_text="Earliest log line timestamp (ISO 8601).",
    )
    max_time = df_filters.DateTimeFilter(
        field_name="timestamp", lookup_expr="lte",
        help_text="Latest log line timestamp (ISO 8601).",
    )

    class Meta:
        model = BuildLogLine
        fields = ["loglevel"]

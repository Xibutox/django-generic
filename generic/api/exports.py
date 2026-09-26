"""Exports of the whole filtered dataset.

Pagination is deliberately ignored: an export contains every row the
current filters return, streamed chunk by chunk so a large table does not
have to fit in memory.
"""

from __future__ import annotations

import csv
import datetime
import decimal
import tempfile
from typing import Any, Iterable, Iterator

from django.db.models import Model, QuerySet
from django.http import FileResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.fields import SkipField

from generic.conf import generic_settings


class Echo:
    """File-like object whose ``write`` returns the line it was given.

    That is what lets ``csv.writer`` feed a streaming response without
    ever building the whole file.
    """

    def write(self, value: str) -> str:
        return value


#: What a cell of a spreadsheet can hold as itself. Everything else is
#: written as its text - which is what the table showed anyway.
CELL_TYPES = (
    str,
    bool,
    int,
    float,
    decimal.Decimal,
    datetime.datetime,
    datetime.date,
    datetime.time,
    datetime.timedelta,
)


def localize_for_export(value: Any) -> Any:
    """Make a value safe to hand to a spreadsheet writer."""
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)

        # Spreadsheets have no notion of a timezone.
        return value.replace(tzinfo=None)

    if value is None or isinstance(value, CELL_TYPES):
        return value

    # A field type the writer has never heard of - a time zone, an enum
    # of a library's own. One of those refused the whole file.
    return force_str(value)


class ExportMixin:
    """Add ``export`` and ``export-csv`` actions to a table endpoint.

    Both stream the filtered queryset. Column selection is honoured but
    validated against the declared columns, so the request cannot widen
    the export beyond what the serializer exposes.
    """

    export_file_name = "export"

    @property
    def export_chunk_size(self) -> int:
        return generic_settings.EXPORT_CHUNK_SIZE

    @property
    def export_max_rows(self) -> int:
        return generic_settings.EXPORT_MAX_ROWS

    # -- shared -------------------------------------------------------

    def get_export_queryset(self) -> QuerySet:
        """The rows to export: filtered, but never paginated."""
        return self.filter_queryset(self.get_queryset())

    def get_export_columns(self, request: Any) -> list[dict[str, Any]]:
        serializer_class = self.get_serializer_class()
        columns = serializer_class.get_export_columns()
        requested = request.query_params.get("columns")

        if not requested:
            return columns

        wanted = {
            name.strip() for name in requested.split(",") if name.strip()
        }

        # Unknown names are dropped rather than rejected: the client may
        # legitimately hold a stale column list after a deployment.
        selected = [column for column in columns if column["data"] in wanted]

        return selected or columns

    def get_export_file_name(self, extension: str) -> str:
        return (
            f"{self.export_file_name}-"
            f"{timezone.localdate():%Y%m%d}.{extension}"
        )

    def check_export_size(self, queryset: QuerySet) -> None:
        limit = self.export_max_rows

        if limit is None:
            return

        # ``exists`` on a sliced queryset is far cheaper than a full
        # count on a large table.
        if queryset[limit:].exists():
            raise ValidationError(
                {
                    "export": [
                        _(
                            "The export exceeds the %(limit)s row limit. "
                            "Narrow the filters and try again."
                        )
                        % {"limit": limit}
                    ]
                }
            )

    def iter_export_rows(
        self,
        queryset: QuerySet,
        columns: list[dict[str, Any]],
    ) -> Iterator[list[Any]]:
        """Yield native Python values, row by row.

        Values are read through the serializer fields rather than through
        ``to_representation`` so dates stay dates: a spreadsheet wants a
        real date, not the string a JSON payload would carry.
        """
        serializer = self.get_serializer_class()()
        fields = [
            serializer.fields[column["data"]]
            for column in columns
            if column["data"] in serializer.fields
        ]

        for row in queryset.iterator(chunk_size=self.export_chunk_size):
            values = []

            for field in fields:
                try:
                    value = field.get_attribute(row)
                except SkipField:
                    value = None

                exporter = getattr(field, "to_export", None)

                # A column with its own flat form - tags, as their
                # labels - says what a cell holds.
                if value is not None and callable(exporter):
                    value = exporter(value)
                # A field reading the whole row - a method column, for
                # instance - only produces its value through
                # to_representation, and so does one whose attribute is
                # not a plain value: a related manager, or the related
                # record of a foreign key, which no spreadsheet can hold.
                elif value is not None and (
                    field.source == "*"
                    or getattr(field, "export_representation", False)
                    or isinstance(value, Model)
                ):
                    value = field.to_representation(value)

                values.append(localize_for_export(value))

            yield values

    # -- Excel --------------------------------------------------------

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            from openpyxl import Workbook
            from openpyxl.cell import WriteOnlyCell
        except ImportError as error:  # pragma: no cover
            raise ImportError(
                "The Excel export needs openpyxl. Install the "
                "'export' extra: pip install django-generic[export]."
            ) from error

        columns = self.get_export_columns(request)
        queryset = self.get_export_queryset()
        self.check_export_size(queryset)

        workbook = Workbook(write_only=True)
        # Excel refuses sheet names longer than 31 characters.
        sheet = workbook.create_sheet(title=self.export_file_name[:31])
        sheet.append([column["title"] for column in columns])

        date_format = generic_settings.EXPORT_DATE_FORMAT
        datetime_format = generic_settings.EXPORT_DATETIME_FORMAT

        for values in self.iter_export_rows(queryset, columns):
            cells = []

            for value in values:
                if isinstance(value, datetime.datetime):
                    cell = WriteOnlyCell(sheet, value=value)
                    cell.number_format = datetime_format
                    cells.append(cell)
                elif isinstance(value, datetime.date):
                    cell = WriteOnlyCell(sheet, value=value)
                    cell.number_format = date_format
                    cells.append(cell)
                else:
                    cells.append(value)

            sheet.append(cells)

        # Written through the open handle rather than by name: on
        # Windows a NamedTemporaryFile cannot be reopened while it is
        # still open. FileResponse closes the handle, which removes the
        # file.
        stream = tempfile.NamedTemporaryFile(suffix=".xlsx")
        workbook.save(stream)
        stream.seek(0)

        return FileResponse(
            stream,
            as_attachment=True,
            filename=self.get_export_file_name("xlsx"),
        )

    # -- CSV ----------------------------------------------------------

    @action(detail=False, methods=["get"], url_path="export-csv")
    def export_csv(
        self,
        request: Any,
        *args: Any,
        **kwargs: Any,
    ) -> StreamingHttpResponse:
        columns = self.get_export_columns(request)
        queryset = self.get_export_queryset()
        self.check_export_size(queryset)

        writer = csv.writer(Echo(), delimiter=";")

        def rows() -> Iterable[str]:
            # A BOM is what makes Excel open a UTF-8 CSV correctly.
            yield "\ufeff"
            yield writer.writerow([column["title"] for column in columns])

            for values in self.iter_export_rows(queryset, columns):
                yield writer.writerow(
                    [self.format_csv_value(value) for value in values]
                )

        response = StreamingHttpResponse(
            rows(),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{self.get_export_file_name("csv")}"'
        )

        return response

    @staticmethod
    def format_csv_value(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, bool):
            return "1" if value else "0"

        if isinstance(value, datetime.datetime):
            return value.strftime("%Y-%m-%d %H:%M")

        if isinstance(value, datetime.date):
            return value.strftime("%Y-%m-%d")

        if isinstance(value, decimal.Decimal):
            return str(value)

        return str(value)


#: Kept as an alias: the previous name only covered the Excel export.
ExcelExportMixin = ExportMixin

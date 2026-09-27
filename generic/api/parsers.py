"""A form's JSON, with files beside it.

A form carrying a new file cannot be sent as JSON, and a multipart body
flattens everything else into text: a many-to-many into repeated keys,
a JSON field and the inline rows into strings to parse again. So the
generated forms send both at once::

    _payload   the JSON body a form without files would have sent
    <field>    one part per chosen file, named by its field

and :class:`MultiPartJSONParser` puts them back together: the request's
data is the payload, a plain dict, with each file under its field - the
same thing the serializer would have read from JSON, plus the uploads.

A request without ``_payload`` is ordinary multipart, parsed exactly as
DRF's ``MultiPartParser`` parses it: a script posting classic form
fields and files keeps working.
"""

from __future__ import annotations

import json
from typing import Any

from django.utils.datastructures import MultiValueDict
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ParseError
from rest_framework.parsers import DataAndFiles, MultiPartParser

#: The part holding the JSON body.
PAYLOAD_PART = "_payload"


class UploadedParts(MultiValueDict):
    """The request's files, merged into its data one value per field.

    DRF adds ``request.FILES`` to ``request.data`` with ``dict.update``,
    which reads a ``MultiValueDict`` - a dict subclass - by its raw
    lists: every file would arrive as ``[file]``. Defining ``__iter__``
    is what makes ``dict.update`` go through ``keys()`` and
    ``__getitem__`` instead, which give the last file of each field.
    """

    def __iter__(self) -> Any:
        return super().__iter__()


class MultiPartJSONParser(MultiPartParser):
    """``_payload`` (JSON) and one part per file, or plain multipart."""

    payload_part = PAYLOAD_PART

    def parse(
        self,
        stream: Any,
        media_type: str | None = None,
        parser_context: dict[str, Any] | None = None,
    ) -> DataAndFiles:
        parsed = super().parse(stream, media_type, parser_context)
        raw = parsed.data.get(self.payload_part)

        if raw is None:
            return parsed

        try:
            data = json.loads(raw)
        except ValueError as error:
            raise ParseError(
                _("The %(part)s part is not valid JSON.")
                % {"part": self.payload_part}
            ) from error

        if not isinstance(data, dict):
            raise ParseError(
                _("The %(part)s part must be a JSON object.")
                % {"part": self.payload_part}
            )

        files = UploadedParts()

        for name, uploads in parsed.files.lists():
            files.setlist(name, list(uploads))
            data[name] = uploads[-1]

        return DataAndFiles(data, files)

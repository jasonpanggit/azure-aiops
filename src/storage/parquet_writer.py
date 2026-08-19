from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .onelake_writer import OneLakeWriter


class ParquetWriter:
    def __init__(self, onelake: OneLakeWriter) -> None:
        self.onelake = onelake

    def write(self, relative_path: str, rows: Sequence[Mapping[str, Any]]) -> int:
        table = pa.Table.from_pylist([dict(row) for row in rows])
        buffer = io.BytesIO()
        pq.write_table(table, buffer, compression="zstd")
        self.onelake.write_bytes(relative_path, buffer.getvalue())
        return table.num_rows

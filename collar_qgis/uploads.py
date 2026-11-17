"""Existing Collar multipart upload contract; no new file storage service."""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FilePart:
    path: str
    offset: int
    length: int
    size: int
    modified_ns: int

    def read(self):
        source = Path(self.path)
        stat = source.stat()
        if stat.st_size != self.size or stat.st_mtime_ns != self.modified_ns:
            raise ValueError('The source file changed during upload. Start a new upload.')
        with source.open('rb') as stream:
            stream.seek(self.offset)
            result = stream.read(self.length)
        if len(result) != self.length:
            raise ValueError('Could not read the entire upload part')
        return result

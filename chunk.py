from io import BytesIO
import json
import gzip
from sqlitedict import SqliteDict
from typing import Optional


CHUNK_SIZE = 512 * 1024


class Chunker:
    def __init__(self):
        self.compressed_file = BytesIO()
        self.gzipper = gzip.GzipFile(mode="w", fileobj=self.compressed_file)
        self.gzipper.write(b"{")
        self.is_empty = True
        self.chunk_id = 0

    def add(self, key: str, value) -> Optional[bytes]:
        if not self.is_empty:
            self.gzipper.write(b",")
        self.is_empty = False
        self.gzipper.write((json.dumps(key) + ":" + json.dumps(value)).encode())
        if len(self.compressed_file.getbuffer()) >= CHUNK_SIZE:
            self.gzipper.write(b"}")
            self.gzipper.close()
            return self.compressed_file.getvalue()

    def end(self) -> Optional[bytes]:
        if self.is_empty:
            return None
        self.gzipper.write(b"}")
        self.gzipper.close()
        return self.compressed_file.getvalue()


def into_chunks(dictionary):
    chunker = Chunker()
    chunk_id = 0
    key_to_chunk_id = {}
    for key, value in dictionary.items():
        key_to_chunk_id[key] = chunk_id
        chunk = chunker.add(key, value)
        if chunk is not None:
            yield chunk_id, chunk
            chunker = Chunker()
            chunk_id += 1
    chunk = chunker.end()
    if chunk is not None:
        yield chunk_id, chunk
    return key_to_chunk_id


db = SqliteDict("Goodman.sqlite", encode=json.dumps, decode=json.loads)
it = into_chunks(db)
try:
    while True:
        chunk_id, chunk = next(it)
        with open(f"docs/chunks/{chunk_id}.json.gz", "wb") as f:
            f.write(chunk)
except StopIteration as e:
    index = e.value
    with open("docs/chunks/index.json", "w") as f:
        json.dump(index, f)

"""
Resume Monitor Agent
Watches the Resume directory for file changes using watchdog.
When the resume is updated, triggers the full pipeline.
"""
import time
import hashlib
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from utils.logger import get_logger

logger = get_logger(__name__)


def _file_hash(path: Path) -> str:
    """Return MD5 hash of a file to detect real content changes."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class ResumeChangeHandler(FileSystemEventHandler):
    """Handles file-system events in the Resume directory."""

    SUPPORTED_EXTS = {".docx", ".pdf"}

    def __init__(self, resume_path: Path, on_change: Callable[[Path], None]):
        super().__init__()
        self.resume_path = resume_path
        self.on_change = on_change
        self._last_hash: str | None = None
        if resume_path.exists():
            self._last_hash = _file_hash(resume_path)

    def _handle(self, event_path: str):
        path = Path(event_path)
        if path.suffix.lower() not in self.SUPPORTED_EXTS:
            return
        # Accept either the specific file or any resume in the folder
        if not path.exists():
            return
        new_hash = _file_hash(path)
        if new_hash == self._last_hash:
            return  # Same content — ignore duplicate events
        self._last_hash = new_hash
        logger.info(f"Resume change detected: {path.name}")
        self.on_change(path)

    def on_modified(self, event):
        if not isinstance(event, FileModifiedEvent):
            return
        self._handle(event.src_path)

    def on_created(self, event):
        if not isinstance(event, FileCreatedEvent):
            return
        self._handle(event.src_path)


class ResumeMonitor:
    """Starts a background watchdog observer for the Resume folder."""

    def __init__(self, resume_dir: Path, on_change: Callable[[Path], None]):
        self.resume_dir = resume_dir
        self.on_change = on_change
        self._observer: Observer | None = None

    def start(self):
        handler = ResumeChangeHandler(
            resume_path=self.resume_dir,
            on_change=self.on_change,
        )
        self._observer = Observer()
        self._observer.schedule(handler, str(self.resume_dir), recursive=False)
        self._observer.start()
        logger.info(f"Monitoring resume folder: {self.resume_dir}")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Resume monitor stopped.")

    def run_forever(self):
        """Block and keep monitoring until KeyboardInterrupt."""
        self.start()
        try:
            while True:
                time.sleep(2)
        except KeyboardInterrupt:
            self.stop()

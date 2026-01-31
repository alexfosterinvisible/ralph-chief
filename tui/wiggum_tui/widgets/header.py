"""Header widget for Wiggum TUI."""

from pathlib import Path
from datetime import datetime
from textual.widgets import Static


class WiggumHeader(Static):
    """Custom header showing project info and live stats."""

    def __init__(self, ralph_dir: Path, worker_count: int = 0) -> None:
        super().__init__()
        self.ralph_dir = ralph_dir
        self.project_dir = ralph_dir.parent
        self.worker_count = worker_count

    def render(self) -> str:
        """Render header content."""
        time_str = datetime.now().strftime("%H:%M:%S")
        project_name = self.project_dir.name
        workers_str = f"Workers: {self.worker_count}" if self.worker_count else ""

        parts = [" WIGGUM MONITOR", project_name, time_str]
        if workers_str:
            parts.append(workers_str)

        return " │ ".join(parts)

    def update_stats(self, worker_count: int) -> None:
        """Update displayed statistics."""
        self.worker_count = worker_count
        self.refresh()

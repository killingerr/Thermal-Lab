from __future__ import annotations

from pathlib import Path
import json
import shutil
from typing import Optional

from thermal_lab.models import Session, Settings


def default_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "thermal-lab"


class Store:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.sessions_dir = self.data_dir / "sessions"
        self.photos_dir = self.data_dir / "photos"
        self.settings_path = self.data_dir / "settings.json"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)

    def load_settings(self) -> Settings:
        if not self.settings_path.is_file():
            return Settings()
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return Settings()
        return Settings.from_dict(data)

    def save_settings(self, settings: Settings) -> None:
        self.settings_path.write_text(
            json.dumps(settings.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def save_session(self, session: Session) -> None:
        session.touch()
        path = self.session_path(session.id)
        path.write_text(json.dumps(session.to_dict(), indent=2) + "\n", encoding="utf-8")

    def load_session(self, session_id: str) -> Session:
        data = json.loads(self.session_path(session_id).read_text(encoding="utf-8"))
        return Session.from_dict(data)

    def list_sessions(self) -> list[Session]:
        sessions: list[Session] = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                sessions.append(Session.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def latest_in_progress(self) -> Optional[Session]:
        for session in self.list_sessions():
            if session.status == "in_progress":
                return session
        return None

    def attach_photo(self, session_id: str, kind: str, source: str | Path) -> str:
        src = Path(source)
        if not src.is_file():
            raise FileNotFoundError(src)
        dest_dir = self.photos_dir / session_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        suffix = src.suffix.lower() or ".png"
        dest = dest_dir / f"{kind}{suffix}"
        shutil.copy2(src, dest)
        return str(dest)

    def suite_log_path(self) -> Path:
        return self.data_dir / "suite.log"

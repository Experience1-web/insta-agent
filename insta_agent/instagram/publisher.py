"""Vom Entwurf zum veröffentlichten Beitrag.

Zwei Betriebsarten:
  - Trockenlauf (Standard): Bild und Text landen als Datei im Entwurfsordner.
    Nichts geht nach außen. So prüfst du, was der Agent vorhat.
  - Live: der Beitrag geht über die Graph API tatsächlich online.

Der Trockenlauf ist bewusst der Standard. Ein Agent, der ungeprüft im Namen
eines Menschen veröffentlicht, ist ein Risiko, kein Werkzeug.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..models import PostDraft
from .client import GraphAPIError, InstagramClient

log = logging.getLogger(__name__)


@dataclass(slots=True)
class PublishResult:
    published: bool
    ig_media_id: str | None = None
    draft_path: Path | None = None
    reason: str | None = None


class Publisher:
    def __init__(
        self,
        *,
        client: InstagramClient | None,
        media_dir: Path,
        draft_dir: Path,
        public_base_url: str | None,
        live: bool,
    ) -> None:
        self.client = client
        self.media_dir = Path(media_dir)
        self.draft_dir = Path(draft_dir)
        self.public_base_url = (public_base_url or "").rstrip("/") or None
        self.live = live

    def _public_url(self, image_path: Path) -> str | None:
        """Die Graph API lädt keine Dateien hoch - sie holt sie von einer URL."""
        if not self.public_base_url:
            return None
        try:
            relative = image_path.resolve().relative_to(self.media_dir.resolve())
        except ValueError:
            # Bild liegt außerhalb des veröffentlichten Ordners.
            return None
        return f"{self.public_base_url}/{relative.as_posix()}"

    def publish(self, draft: PostDraft, image_path: Path) -> PublishResult:
        caption = self.full_caption(draft)

        if not self.live:
            path = self._write_draft(draft, image_path, caption)
            return PublishResult(published=False, draft_path=path, reason="Trockenlauf")

        if self.client is None:
            path = self._write_draft(draft, image_path, caption)
            return PublishResult(
                published=False, draft_path=path, reason="Keine Instagram-Zugangsdaten hinterlegt"
            )

        image_url = self._public_url(image_path)
        if not image_url:
            path = self._write_draft(draft, image_path, caption)
            return PublishResult(
                published=False,
                draft_path=path,
                reason=(
                    "Keine öffentliche Bild-URL. Setze PUBLIC_MEDIA_BASE_URL und "
                    "spiegle PUBLIC_MEDIA_DIR dorthin - Instagram holt das Bild "
                    "selbst von dieser Adresse."
                ),
            )

        try:
            container = self.client.create_container(image_url, caption)
            self.client.wait_until_ready(container)
            media_id = self.client.publish_container(container)
        except GraphAPIError as exc:
            path = self._write_draft(draft, image_path, caption)
            log.error("Veröffentlichen fehlgeschlagen: %s", exc)
            return PublishResult(published=False, draft_path=path, reason=str(exc))

        log.info("Veröffentlicht als %s", media_id)
        return PublishResult(published=True, ig_media_id=media_id)

    @staticmethod
    def full_caption(draft: PostDraft) -> str:
        """Caption, Handlungsaufruf und Hashtags zu einem Text zusammensetzen."""
        parts = [draft.caption.strip()]
        cta = draft.call_to_action.strip()
        if cta and cta.lower() not in draft.caption.lower():
            parts.append(cta)
        if draft.hashtags:
            parts.append(" ".join(f"#{tag}" for tag in draft.hashtags))
        return "\n\n".join(parts)

    def _write_draft(self, draft: PostDraft, image_path: Path, caption: str) -> Path:
        self.draft_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = self.draft_dir / f"{stamp}-{draft.pillar[:24].replace(' ', '_')}.md"
        path.write_text(
            f"""# Entwurf vom {stamp}

**Themensäule:** {draft.pillar}
**Bild:** `{image_path}`
**Bester Zeitpunkt:** {draft.best_time_hint}
**Erwartung des Agenten:** {draft.expected_outcome}

---

{caption}

---

<details><summary>Rohdaten</summary>

```json
{json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, indent=2)}
```

</details>
""",
            encoding="utf-8",
        )
        log.info("Entwurf geschrieben: %s", path)
        return path

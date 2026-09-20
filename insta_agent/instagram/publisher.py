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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..models import PostDraft
from .aufbereiten import fuer_instagram
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
        ablage: object | None = None,
        ablagen: Sequence[object] | None = None,
    ) -> None:
        self.client = client
        self.media_dir = Path(media_dir)
        self.draft_dir = Path(draft_dir)
        self.public_base_url = (public_base_url or "").rstrip("/") or None
        self.live = live
        # Zweiter Weg zur oeffentlichen Adresse: das Bild kurz hochladen.
        # Mehrere, weil Meta manche Bildspeicher nicht abholt - siehe
        # ablage.py. Wird eine Adresse abgelehnt, kommt die naechste dran.
        self.ablagen: list[object] = list(ablagen) if ablagen else []
        if ablage is not None and ablage not in self.ablagen:
            self.ablagen.insert(0, ablage)

    def _adressen(self, image_path: Path) -> Iterator[str]:
        """Alle öffentlichen Adressen, unter denen das Bild erreichbar wäre.

        Die Graph API lädt keine Dateien hoch - sie holt sie von einer URL.
        Zwei Wege führen dorthin: ein fester öffentlicher Ordner, den der
        Betreiber selbst betreibt, oder ein Bildspeicher, in den wir das
        Bild kurz vor dem Veröffentlichen hochladen. Der feste Ordner hat
        Vorrang - wer ihn eingerichtet hat, will ihn auch benutzen.

        Erzeugt wird eine nach der anderen: Solange die erste Adresse
        angenommen wird, wird nirgends sonst etwas hochgeladen.
        """
        eigener = self._ordner_url(image_path)
        if eigener:
            yield eigener
        for ablage in self.ablagen:
            try:
                yield ablage.lade_hoch(image_path)
            except Exception as exc:  # noqa: BLE001 - der Grund gehört ins Protokoll
                log.warning(
                    "Bild konnte nicht bei %s abgelegt werden: %s",
                    getattr(ablage, "name", ablage),
                    exc,
                )

    def _public_url(self, image_path: Path) -> str | None:
        """Die erste brauchbare Adresse - für alles, was nur eine braucht."""
        return next(self._adressen(image_path), None)

    def _ordner_url(self, image_path: Path) -> str | None:
        if not self.public_base_url:
            return None
        try:
            relative = image_path.resolve().relative_to(self.media_dir.resolve())
        except ValueError:
            # Bild liegt außerhalb des veröffentlichten Ordners.
            return None
        # Auch aus dem eigenen Ordner muss ein JPEG kommen, sonst lehnt
        # Instagram es ab. Neben das Bild wird die Fassung dafür gelegt.
        try:
            relative = self._lege_jpeg_bereit(image_path, relative)
        except Exception as exc:  # noqa: BLE001 - der Grund gehört ins Protokoll
            log.warning("Bild konnte nicht aufbereitet werden: %s", exc)
            return None
        return f"{self.public_base_url}/{relative.as_posix()}"

    def _lege_jpeg_bereit(self, image_path: Path, relative: Path) -> Path:
        """Schreibt die Instagram-Fassung neben das Bild und gibt ihren Pfad zurück.

        Immer eine eigene Datei: das Original bleibt unberührt, auch wenn es
        selbst schon ein JPEG ist - das Seitenverhältnis kann trotzdem
        ausserhalb liegen.
        """
        name = f"{image_path.stem}-ig.jpg"
        image_path.with_name(name).write_bytes(fuer_instagram(image_path))
        return relative.with_name(name)

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

        gruende: list[str] = []
        for image_url in self._adressen(image_path):
            try:
                container = self.client.create_container(image_url, caption)
                self.client.wait_until_ready(container)
                media_id = self.client.publish_container(container)
            except GraphAPIError as exc:
                log.error("Veröffentlichen fehlgeschlagen: %s (Bild: %s)", exc, image_url)
                # Die Adresse gehört in den Grund: Fast jede Absage von
                # Instagram betrifft das Bild, und an der Adresse sieht man
                # sofort, welche Fassung wirklich hinausging.
                gruende.append(f"{exc}\n    Bild: {image_url}")
                if _liegt_an_der_adresse(exc):
                    # Nicht das Bild ist das Problem, sondern wo es liegt.
                    # Also woanders ablegen und noch einmal versuchen.
                    continue
                break

            log.info("Veröffentlicht als %s", media_id)
            return PublishResult(published=True, ig_media_id=media_id)

        path = self._write_draft(draft, image_path, caption)
        if not gruende:
            return PublishResult(
                published=False,
                draft_path=path,
                reason=(
                    "Keine öffentliche Bild-URL. Richte den Bildspeicher ein "
                    "mit `insta-agent ablage` - Instagram holt das Bild selbst "
                    "von dieser Adresse."
                ),
            )
        return PublishResult(published=False, draft_path=path, reason="\n  ".join(gruende))

    @staticmethod
    def full_caption(draft: PostDraft) -> str:
        """Caption, Handlungsaufruf und Hashtags zu einem Text zusammensetzen."""
        parts = [draft.caption.strip()]
        cta = draft.call_to_action.strip()
        if cta and not _schon_gesagt(draft.caption, cta):
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


# Meldungen, mit denen Instagram sagt: "Ich komme an diese Datei nicht ran."
# Die Meldung zeigt auf das Bild, gemeint ist die Adresse - deshalb ist ein
# anderer Bildspeicher die richtige Antwort und nicht ein anderes Bild.
_ADRESSFEHLER = (
    "9004",  # Only photo or video can be accepted as media type
    "2207052",  # The media could not be fetched from this URI
    "could not be fetched",
    "not be downloaded",
)


def _liegt_an_der_adresse(exc: GraphAPIError) -> bool:
    text = str(exc).lower()
    return any(marke in text for marke in _ADRESSFEHLER)


# Kürzeste Länge, ab der ein Satzanfang als Wiedererkennung taugt. Darunter
# ist "Folge mir" zu gewöhnlich, um daraus etwas zu schließen.
_GENUG_ZEICHEN = 25


def _entkleidet(text: str) -> str:
    """Kleinschreibung, einfache Zeichen, ein Leerzeichen - zum Vergleichen."""
    text = text.lower()
    for hin, her in (("\u2013", "-"), ("\u2014", "-"), ("\u2019", "'"), ("\u201e", ""), ("\u201c", "")):
        text = text.replace(hin, her)
    return " ".join(text.split())


def _schon_gesagt(caption: str, cta: str) -> bool:
    """Steht der Handlungsaufruf schon im Text?

    Nicht nur wörtlich: Der Agent schreibt den Aufruf gern ans Ende des
    Textes und noch einmal ins eigene Feld, beim zweiten Mal leicht
    erweitert. Angehängt stünde derselbe Satz dann zweimal untereinander -
    was wie ein Fehler aussieht, weil es einer ist. Verglichen wird
    deshalb der Satzanfang.
    """
    text, ruf = _entkleidet(caption), _entkleidet(cta)
    if not ruf:
        return True
    if ruf in text:
        return True
    return len(ruf) >= _GENUG_ZEICHEN and ruf[:_GENUG_ZEICHEN] in text

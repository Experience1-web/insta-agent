# Übergabe an die Claude-Code-Sitzung auf dem Laptop

Diese Datei ist für dich, Claude, in der lokalen Sitzung im Ordner „MeinAgent“.
Die bisherige Arbeit lief in einer Cloud-Sitzung ohne API-Schlüssel – dort
gab es nur Testdaten. Hier liegt der echte Schlüssel in der `.env`. Jetzt
sollen echte Beiträge entstehen und besser werden.

## Der Auftrag

Wörtlich vom Betreiber: „Verbrauche ruhig Kontingent und mache Posts so viel
wie nötig erstmal, oder sagen wir mal mindestens 10, 20 € kannst du
verbrauchen, um alles zu verbessern, dass die Posts wirklich richtig cool
werden und richtig professionell und gut.“

Also:

1. Mindestens 10 echte Beiträge erzeugen lassen. Budget: **höchstens 20 €**
   (rund 21 USD) für alles zusammen – Beiträge und Verbesserungsrunden.
   Den Stand vor dem ersten Lauf notieren (`py -m insta_agent.cli kasse`
   oder das Dashboard) und nach jedem Lauf nachrechnen.
2. Jeden Beitrag kritisch ansehen wie ein Redakteur eines großen
   Wissens-Accounts: Bilder ansehen (die PNG/JPG in `out/media`
   öffnen), Texte, Karten, Bildunterschrift, Hashtags, Fakten und Prüfbericht.
3. Schwächen am Code und an den Prompts beheben – nicht am einzelnen
   Beitrag von Hand. Dann wieder Beiträge erzeugen und vergleichen.
4. Am Ende kurz auf Deutsch berichten: was besser wurde, mit Beispielen,
   und was es gekostet hat.

Die Beiträge sind Entwürfe. **Nichts veröffentlichen, nichts freigeben.**
Der Betreiber gibt jeden Beitrag selbst frei. Den Sparmodus für diese
Läufe ausschalten, damit die volle Qualität zu sehen ist.

## So lässt du ihn arbeiten

- Vorher das Dashboard beenden: `windows\8 - Dashboard beenden.bat`, sonst
  greifen zwei Programme auf dieselbe Datenbank zu.
- Ein Zyklus = ein Beitrag: `py -m insta_agent.cli run --cycles 1 -v`
  (ohne `--live`; dann wird nichts veröffentlicht).
- Lieber einzeln oder zu zweit laufen lassen, dazwischen ansehen und
  verbessern, statt zehn am Stück.
- Die Zyklusgrenze steht in `config/agent.yaml` (`max_cost_per_cycle_usd`).
  Wenn sie greift, ist das eine Notbremse, kein Fehler.
- Tests: `py -m pytest -q`, Stil: `ruff check .` – beides muss sauber sein,
  bevor du etwas hochlädst.

## Wichtig: Änderungen sichern

`windows\6 - Neue Version holen.bat` setzt den Ordner **hart** auf den Stand
von GitHub zurück. Alles, was nicht gepusht ist, geht dabei verloren.
Deshalb jede Verbesserung committen und pushen:

- Zweig: `claude/instagram-agent-autonomous-lt87e7`
- `git push -u origin claude/instagram-agent-autonomous-lt87e7`
- Keinen Pull Request anlegen, wenn er nicht ausdrücklich gewünscht ist.
- `.env`, `state/` und `out/` gehören nicht ins Repository (sind ausgenommen).

## Regeln des Betreibers

- Er ist Anfänger unter Windows. Antworten auf **Deutsch**, kurz und klar,
  ein Schritt nach dem anderen.
- **Immer echte Umlaute schreiben** („für“, nicht „fuer“) – in Antworten,
  Texten, Beiträgen und Dashboard.
- Er gibt jeden Beitrag selbst frei.
- Möglichst viel selbst testen, damit kein Geld unnötig verbraucht wird.
- Fakten müssen stimmen. Beispiel aus einem früheren Beitrag: Das Gold
  wurde nicht „vergraben“, sondern versteckt und später verschüttet –
  Deutung ist keine Tatsache, genaue Wörter zählen.
- Der Account heißt **@erstfund.de**: Funde, Entdeckungen, Dinge, die es
  vorher nicht gab – kein Alltag.

## Wo was liegt

- `insta_agent/runner.py` – der Zyklus: Stoffsuche → Text → Bild →
  Karussell → Endprüfung → Nachbessern → Reel.
- `insta_agent/brain/` – die Aufträge an das Modell:
  `stoff.py` (Fund suchen), `content.py` (Beitrag schreiben),
  `pruefung.py` (Endprüfung), `ueberarbeitung.py` (Nachbessern),
  `gestaltung.py` (Bildsprache), `vorbilder.py` (Machart guter Accounts).
- `insta_agent/imaging/` – Fotosuche (`echtbild.py`, `quellbild.py`),
  Schrift aufs Bild (`overlay.py`, `renderer.py`), Reel (`reel.py`).
- `insta_agent/economy/` – Kasse, Preise, Sparmodus.
- `insta_agent/web.py` + `web_page.html` – das Dashboard.
- Die Mannschaft (Rollen und Modelle): `insta_agent/mannschaft.py`.
  Voreinstellung: Chef auf Opus 5, Stoffsuche, Bildsprache und Prüfung
  auf Sonnet 5. Im Dashboard umstellbar.

## Woran „richtig cool und professionell“ zu messen ist

- Ein Fund, bei dem man im Feed anhält – echt, belegt, kaum bekannt.
- Ein echtes Foto, das die Sache selbst zeigt; Schrift gut lesbar.
- Ein erster Satz auf dem Bild, der neugierig macht, ohne zu übertreiben.
- Karten, die eine Geschichte erzählen und zum Weiterwischen ziehen.
- Eine Bildunterschrift mit Fakten, Quelle und einer Frage am Ende,
  dazu 3 bis 5 genau passende Hashtags.
- Keine Fehler in Zahlen, Daten, Namen oder Wörtern.

Viel Erfolg – und erst einen Beitrag machen und ansehen, bevor viele folgen.

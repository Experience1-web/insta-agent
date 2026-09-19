# insta-agent

Ein Agent, der sich **selbst einen Namen gibt** und einen
Instagram-Account **erfindet, führt und zu finanzieren versucht**. Er sucht sich seine Nische, denkt sich sein Motto
aus, recherchiert seinen Markt, schreibt und gestaltet seine Beiträge,
liest seine eigenen Zahlen, zieht daraus Konsequenzen — und rechnet dabei
mit, was sein eigenes Denken kostet.

Was er entscheidet, entscheidet er allein. Du gibst ihm kein Thema vor
(du *darfst*, musst aber nicht).

---

## Was der Agent tut

| Schritt | Was passiert |
|---|---|
| **Geburt** | Einmalig: Er gibt sich selbst einen Namen, recherchiert im Web und erfindet dann Handle, Motto, Nische, Zielgruppe, Tonfall, Bildsprache und Themensäulen. |
| **Messen** | Holt Follower, Reichweite und Beitragskennzahlen über die Graph API. |
| **Lernen** | Liest seine eigenen Zahlen und trennt dabei, was er *weiß*, von dem, was er nur *vermutet*. |
| **Recherchieren** | Alle 7 Zyklen (oder wenn der Kurs wackelt): Websuche nach Trends, Wettbewerb und Lücken. |
| **Planen** | Setzt ein einziges messbares Ziel für sieben Tage und begründet jede Änderung. |
| **Produzieren** | Schreibt Caption, Hook, Hashtags und einen Bauplan fürs Bild; rendert das Bild lokal. |
| **Veröffentlichen** | Standard: Entwurf als Datei. Mit `--live`: echter Beitrag über die offizielle API. |
| **Nachrechnen** | Alle 5 Zyklen: Lohnt sich der Kurs noch? Erwartungswert des jetzigen Wegs gegen Alternativen, abzüglich Wechselkosten. |
| **Verdienen** | Alle 14 Zyklen (oder bei knapper Kasse): Geschäftsideen mit nüchterner Umsatzschätzung. |

Alles liegt zwischen den Läufen in einer SQLite-Datei. Der Agent kann
jederzeit gestoppt und Wochen später fortgesetzt werden, ohne sein
Gedächtnis zu verlieren.

---

## Ohne Terminal: Doppelklick genügt

Im Ordner `windows/` liegen Startdateien. Der Reihe nach durchnummeriert,
du brauchst nur zu klicken:

| Datei | Wofür |
|---|---|
| `1 - Einrichten.bat` | Installiert alles und fragt nach dem API-Schlüssel |
| `2 - Dashboard starten.bat` | Öffnet das Dashboard im Browser |
| `3 - Dashboard auch fuer das Handy.bat` | Macht es zusätzlich im WLAN erreichbar |
| `4 - Beim Hochfahren mitstarten.bat` | Dashboard startet künftig beim Anmelden |
| `5 - Nicht mehr mitstarten.bat` | Hebt das wieder auf |
| `6 - Neue Version holen.bat` | Holt Änderungen und installiert sie |
| `7 - Taeglich arbeiten und mitstarten.bat` | Alles zusammen: startet mit, ist im WLAN erreichbar, arbeitet täglich |
| `8 - Dashboard beenden.bat` | Beendet ein hängendes Dashboard, dessen Fenster nicht auffindbar ist |

Ein schwarzes Fenster erscheint dabei trotzdem — es ist der laufende
Server. Schließen beendet das Dashboard, das ist der Ausknopf.

## Schnellstart

```bash
pip install -e .
insta-agent setup             # fragt nach deinem API-Schlüssel und legt die .env an
insta-agent run
```

`insta-agent setup` ist der einfache Weg: Du musst keine Datei suchen und
keinen Editor öffnen. Der Befehl legt die `.env` an, trägt den Schlüssel
ein und prüft anschließend selbst, ob der Agent ihn findet.

Weißt du nicht mehr, wo etwas liegt? `insta-agent where` zeigt dir alle
Pfade und sagt, was schon existiert.

## Oberfläche im Browser

Wer nicht im Terminal arbeiten mag:

```bash
insta-agent web
```

Der Browser öffnet sich von selbst. Dort siehst du Kasse, Profil, Kurs,
alle Entwürfe samt fertigen Bildern und den Geschäftsplan — und startest
den Agenten per Knopfdruck. Während er arbeitet, läuft sein Protokoll live
mit.

Gebaut ohne Zusatzbibliotheken, nur mit Bordmitteln von Python.

### Vom Handy aus

```bash
insta-agent web --host 0.0.0.0 --read-only
```

Beim Start erscheint ein **QR-Code** — im Terminal und im Dashboard.
Einmal mit der Handykamera scannen, fertig. Der Browser merkt sich den
Zugang, danach genügt die nackte Adresse; am besten legst du sie dir auf
den Startbildschirm.

Wer lieber tippt: Die vollständige Adresse steht daneben. Sie enthält ein
**Zugangswort**, behandle sie wie ein Passwort.

`--read-only` blendet die Steuerung aus: Von unterwegs siehst du Kasse,
Kurs und Beiträge, aber niemand kann einen Zyklus starten. Lass es weg,
wenn du auch von unterwegs starten können willst.

**Zwei Dinge dazu, ehrlich gesagt:**

Ohne `--host` lauscht der Server nur auf `127.0.0.1` und ist vom Handy
nicht erreichbar — das ist Absicht. Wer die Seite öffnen kann, kann Geld
ausgeben, deshalb verlangt jeder Zugriff von außen das Zugangswort. Es
steht in der `.env` als `WEB_TOKEN` und wird beim ersten Mal selbst
erzeugt.

Und: Das Ganze läuft auf deinem Rechner. Ist er aus oder im Ruhezustand,
ist auch die Seite weg. Für echten Zugriff von überall bräuchte es einen
durchlaufenden Server oder einen privaten Tunnel (etwa Tailscale).

Ohne Instagram-Zugangsdaten läuft der Agent vollständig im Trockenlauf: Er
erfindet sich, plant, schreibt und rendert Bilder — er veröffentlicht nur
nichts. Ergebnisse liegen in `out/drafts/` und `out/media/`.

```bash
insta-agent identity     # wer er zu sein beschlossen hat
insta-agent strategy     # sein Kurs für diese Woche
insta-agent drafts       # was er geschrieben hat
insta-agent money        # Kasse und Geschäftsideen
insta-agent journal      # sein Arbeitsprotokoll
insta-agent where        # wo seine Dateien auf deinem Rechner liegen
insta-agent check        # prüft, ob die Zugangsdaten richtig eingetragen sind
insta-agent earn 12.50 --category digital_product --note "2 Vorlagen verkauft"
insta-agent run --cycles 7 --interval 3600   # eine Woche am Stück
```

Erst wenn dir gefällt, was in den Entwürfen steht:

```bash
insta-agent run --live
```

---

## Von selbst arbeiten

```bash
insta-agent web --auto-hours 24
```

Damit arbeitet der Agent einmal täglich, ohne dass jemand auf *Starten*
drückt. In Verbindung mit dem Autostart heißt das: Rechner hochfahren
genügt.

Der Abstand zählt **ab seinem letzten Zyklus**, nicht ab dem Start des
Programms. Wer seinen Laptop dreimal am Tag hochfährt, löst damit nicht
dreimal einen bezahlten Zyklus aus — er arbeitet trotzdem nur einmal.

Die Budgetbremse gilt weiter: Ist die Kasse leer, hält er an, statt
weiterzulaufen.

## Gewinnorientiert: wann er den Kurs wechselt

Der Agent ist an keine Nische gebunden. Alle fünf Zyklen rechnet er nach,
ob sich sein Weg noch lohnt — und zwar im **Erwartungswert**: was eine
Sache einbringt, *wenn* sie aufgeht, mal der Wahrscheinlichkeit, dass sie
aufgeht. Eine Idee mit 5 % Chance auf 10.000 USD ist 500 USD wert, nicht
10.000. Wer das verwechselt, jagt Luftschlösser.

Gewechselt wird nur, wenn **alle** Bedingungen erfüllt sind:

| Bedingung | Warum |
|---|---|
| Er empfiehlt selbst „wechseln" | „Ergänzen" ist oft besser: Publikum behalten, trotzdem mehr verdienen |
| Die Alternative schlägt den jetzigen Weg um Faktor 2 | Knapp besser rechtfertigt keine verlorene Reichweite |
| Seine Einschätzung ist nicht „unsicher" | Auf Vermutungen wechselt man nicht |
| Mindestens 10 Zyklen seit dem letzten Wechsel | Sonst ist jeder Wechsel für sich rational und die Summe ruinös |

Beim Wechsel **bleibt seine Person** — nur die Marke ändert sich. Der
alte Kurs samt Begründung landet im Verlauf, damit er später nachsehen
kann, was er warum aufgegeben hat.

Verdient er noch nichts, greift die Faktorregel nicht: Wer bei null steht,
soll nicht wegen einer Multiplikation mit null festsitzen.

## Zahlungsweg: Empfangen ja, Senden nein

```bash
insta-agent wallet --adresse 0x… --kette base
```

Der Agent bezieht die Adresse dann in seine Geschäftsplanung ein.

**Er bekommt keine privaten Schlüssel und keine Wiederherstellungswörter.**
Das ist keine Bevormundung, sondern eine Konsequenz aus seiner Arbeitsweise:
Er liest bei der Recherche fremde Webseiten, und deren Text landet in
seinem Kontext. Wer dort etwas unterbringt, kann versuchen, ihn zu
Handlungen zu bewegen, die niemand wollte. Ein Agent ohne Schlüssel kann
dabei nichts verlieren — einer mit Schlüssel alles.

Der Befehl erkennt und verweigert deshalb private Schlüssel (64 Hexzeichen)
und Wiederherstellungswörter (12–24 Wörter), falls die versehentlich in der
Zwischenablage landen.

Eingegangene Beträge trägst du mit `insta-agent earn` in seine Kasse ein.

## Die Kasse: was hier wirklich geht

Du hast gefragt, ob der Agent sich seine Token selbst verdienen kann.
Ehrliche Antwort in zwei Teilen.

**Was er wirklich tut:**

- Er rechnet **jeden einzelnen Modellaufruf** in USD um und bucht ihn gegen
  sein Guthaben. Er weiß auf den Cent, was er gekostet hat.
- Er **drosselt sich selbst**: Unter der Sparschwelle wechselt er auf das
  günstige Modell und lässt die teure Websuche weg.
- Er **stoppt sich selbst**, wenn die Kasse leer ist, statt weiterzulaufen.
- Ein **Zyklusbudget** fängt Ausreißer ab, bevor ein einzelner Lauf das
  ganze Guthaben frisst.
- Einnahmen bucht er als Einnahmen — und das Startkapital zählt dabei
  ausdrücklich **nicht** als Verdienst. `Kostendeckung: 0 %` heißt genau
  das, auch wenn noch viel Geld auf dem Konto liegt.

**Was er nicht tut, und nicht tun kann:**

Ein Agent kann kein Konto eröffnen, keinen Vertrag unterschreiben, kein
Geld empfangen und keine API-Credits nachkaufen. Das sind Rechtsgeschäfte,
die eine Person mit Ausweis braucht. Er kann das Produkt entwerfen, den
Text schreiben, die Preise kalkulieren und dir sagen, was zu tun ist —
`insta-agent money` gibt dir dafür eine Abhakliste. Das Einrichten und die
Auszahlung bleiben bei dir.

Der Kreis schließt sich also so: Der Agent erwirtschaftet Einnahmen auf
deinem Konto, du meldest sie ihm mit

```bash
insta-agent earn 12.50 --category digital_product --note "2 Vorlagen verkauft"
```

und ab dem Moment plant er mit diesem Geld, sieht seine Kostendeckung
steigen und weiß, dass er sich trägt. Er finanziert sich selbst — nur
nicht ohne deine Hand an der letzten Schraube.

---

## Wachstum ohne Tricks

Der Agent wächst ausschließlich über Inhalte, die jemand freiwillig
weitergibt. Es gibt kein Follower-Kaufen, kein Folgen-Entfolgen, keine
Engagement-Pods, kein Automatisieren fremder Konten, kein Abgreifen von
Nutzerdaten.

Das ist keine Zurückhaltung, sondern Selbstschutz: Solche Methoden
verstoßen gegen die Nutzungsbedingungen von Instagram und kosten früher
oder später genau den Account, den der Agent aufbaut. Deshalb nutzt er nur
die offizielle Graph API — den einzigen Weg, der auf Dauer trägt.

---

## Instagram anbinden

Nötig für `--live`. Ohne das läuft alles andere trotzdem.

1. Instagram-Account auf **Business** oder **Creator** umstellen und mit
   einer Facebook-Seite verknüpfen.
2. Unter [developers.facebook.com](https://developers.facebook.com) eine App
   anlegen, Produkt *Instagram Graph API* hinzufügen.
3. Rechte anfordern: `instagram_basic`, `instagram_content_publish`,
   `instagram_manage_insights`.
4. `IG_USER_ID` und einen langlebigen `IG_ACCESS_TOKEN` in `.env` eintragen.

**Ein Stolperstein, der oft übersehen wird:** Die Graph API nimmt keine
Datei-Uploads an. Sie holt das Bild von einer **öffentlich erreichbaren
URL**. Du brauchst also einen Ort, an dem `out/media/` im Netz liegt — S3,
Netlify, ein Webspace, egal was. Diese Adresse kommt in
`PUBLIC_MEDIA_BASE_URL`. Fehlt sie, legt der Agent statt zu veröffentlichen
einen Entwurf ab und sagt dir warum.

Der Token läuft nach rund 60 Tagen ab. `insta-agent token-refresh` holt
einen neuen.

---

## Konfiguration

`config/agent.example.yaml` nach `config/agent.yaml` kopieren und anpassen:

```yaml
llm:
  model: claude-opus-5          # Strategie, Recherche, Reflexion
  cheap_model: claude-haiku-4-5 # Routinearbeit im Sparbetrieb
  effort: high

economy:
  treasury_start_usd: 20.00
  low_balance_usd: 5.00         # darunter: Sparbetrieb
  halt_balance_usd: 0.50        # darunter: Stopp
  max_cost_per_cycle_usd: 1.50

posting:
  posts_per_day: 1
  max_hashtags: 20
  live: false
```

Setze die Sparschwelle nicht über das Startkapital — sonst läuft der Agent
vom ersten Zyklus an gedrosselt. Er warnt dich, wenn das passiert.

Für ein **kleines Startguthaben von 5 USD** liegt eine fertige
`config/agent.yaml` bei: Sparschwelle 1,50 USD, Stopp bei 0,25 USD,
höchstens 1,50 USD pro Zyklus.

Die Obergrenze muss den **Geburtszyklus** tragen — der ist der teuerste,
weil Recherche, Identität, Strategie und erster Post zusammenfallen. Ist
sie zu eng, bricht er mittendrin ab, und die bereits bezahlte Arbeit
bringt nichts. Spätere Zyklen kosten deutlich weniger.

Die Websuche läuft bewusst auf `claude-sonnet-5` statt Opus: Seiten lesen
und zusammenfassen braucht kein Spitzenmodell, kostet dort aber das
Zweieinhalbfache.

`TREASURY_START_USD` in der `.env` **überschreibt** den YAML-Wert. Lass die
Zeile auskommentiert, solange du die Kasse über die YAML-Datei steuerst —
sonst plant der Agent mit Geld, das nicht aufgeladen ist.

---

## Aufbau

```
insta_agent/
├── runner.py          Der Zyklus: messen → lernen → planen → produzieren
├── web.py             Oberfläche im Browser, nur mit Bordmitteln
├── llm.py             Claude-Zugang mit Kostenerfassung bei jedem Aufruf
├── store.py           SQLite: Identität, Strategie, Posts, Zahlen, Ledger
├── models.py          Die Verträge, die Claude über Structured Outputs füllt
├── config.py          .env + YAML
├── brain/             Was der Agent denkt
│   ├── prompts.py     Seine Haltung — hier wird aus dem Modell eine Person
│   ├── identity.py    Die einmalige Geburt
│   ├── research.py    Websuche und Marktanalyse
│   ├── strategy.py    Der Kurs der Woche
│   ├── content.py     Caption, Hashtags, Bildbauplan
│   ├── reflection.py  Lernen aus den eigenen Zahlen
│   └── business.py    Geschäftsideen
├── economy/
│   ├── pricing.py     Preistabelle der Claude API
│   └── ledger.py      Die Kasse mit Spar- und Stoppschwelle
├── imaging/renderer.py  Bilder aus Farbe und Typografie, ohne Kosten
└── instagram/
    ├── client.py      Offizielle Graph API
    └── publisher.py   Trockenlauf oder live
```

## Tests

```bash
pytest
```

130 Tests, keiner braucht einen API-Schlüssel. Der Zyklus wird mit einem
gefälschten Modell vollständig durchgespielt — inklusive Budgetbremse,
Bilderzeugung und Entwurfsablage.

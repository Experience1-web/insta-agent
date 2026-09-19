# insta-agent

Ein Agent, der einen Instagram-Account **selbst erfindet, führt und zu
finanzieren versucht**. Er sucht sich seine Nische, denkt sich sein Motto
aus, recherchiert seinen Markt, schreibt und gestaltet seine Beiträge,
liest seine eigenen Zahlen, zieht daraus Konsequenzen — und rechnet dabei
mit, was sein eigenes Denken kostet.

Was er entscheidet, entscheidet er allein. Du gibst ihm kein Thema vor
(du *darfst*, musst aber nicht).

---

## Was der Agent tut

| Schritt | Was passiert |
|---|---|
| **Geburt** | Einmalig: Marktrecherche im Web, dann erfindet er Handle, Motto, Nische, Zielgruppe, Tonfall, Bildsprache und Themensäulen. |
| **Messen** | Holt Follower, Reichweite und Beitragskennzahlen über die Graph API. |
| **Lernen** | Liest seine eigenen Zahlen und trennt dabei, was er *weiß*, von dem, was er nur *vermutet*. |
| **Recherchieren** | Alle 7 Zyklen (oder wenn der Kurs wackelt): Websuche nach Trends, Wettbewerb und Lücken. |
| **Planen** | Setzt ein einziges messbares Ziel für sieben Tage und begründet jede Änderung. |
| **Produzieren** | Schreibt Caption, Hook, Hashtags und einen Bauplan fürs Bild; rendert das Bild lokal. |
| **Veröffentlichen** | Standard: Entwurf als Datei. Mit `--live`: echter Beitrag über die offizielle API. |
| **Verdienen** | Alle 14 Zyklen (oder bei knapper Kasse): Geschäftsideen mit nüchterner Umsatzschätzung. |

Alles liegt zwischen den Läufen in einer SQLite-Datei. Der Agent kann
jederzeit gestoppt und Wochen später fortgesetzt werden, ohne sein
Gedächtnis zu verlieren.

---

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
insta-agent earn 12.50 --category digital_product --note "2 Vorlagen verkauft"
insta-agent run --cycles 7 --interval 3600   # eine Woche am Stück
```

Erst wenn dir gefällt, was in den Entwürfen steht:

```bash
insta-agent run --live
```

---

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
höchstens 0,50 USD pro Zyklus. Damit reicht das Guthaben für grob 10–50
Durchläufe.

`TREASURY_START_USD` in der `.env` **überschreibt** den YAML-Wert. Lass die
Zeile auskommentiert, solange du die Kasse über die YAML-Datei steuerst —
sonst plant der Agent mit Geld, das nicht aufgeladen ist.

---

## Aufbau

```
insta_agent/
├── runner.py          Der Zyklus: messen → lernen → planen → produzieren
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

47 Tests, keiner braucht einen API-Schlüssel. Der Zyklus wird mit einem
gefälschten Modell vollständig durchgespielt — inklusive Budgetbremse,
Bilderzeugung und Entwurfsablage.

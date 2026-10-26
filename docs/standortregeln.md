# Standortregeln

Wie im ZAM Häuser, Ebenen, Räume und Bereiche benannt und codiert werden. Die technische Seite
(Modell, Kategorien, Nummernkreise) steht in [Building structure](location-structure.md). Der
aktuelle Stand aller Orte steht im Inventar; die Seite **Ebenen und Achsen** (`/loc/structure/`,
verlinkt im Standortbaum) zeigt ihn als Übersicht.

## Grundsätze

1. **Der Baum beschreibt nur die Architektur**: Haus und Ebene, Raum, Bereich. Was dort
   passiert und wer zuständig ist, sind Merkmale am Ort und stehen nie im Code. So bleiben Codes,
   Schilder und Labels gültig, wenn sich Nutzung oder Zuständigkeit ändern.
2. **Codes sind kurz, ableitbar und hausweit eindeutig.** Aus `HH+1.WC8.2` liest man Haus,
   Ebene, Raum und Teil ab; `WC8` gilt auch allein.
3. **Die Hauptfläche ist der Elternknoten selbst.** Was in der Halle steht, steht auf `WH-1`;
   der Vorraum des WC-Bereichs ist `WC8`. Eigene Knoten gibt es nur für das, was davon abweicht.
4. **Gebäudeknoten sind fest:** Haus+Ebene, Raum, Bereich, Teilraum und Teilbereich werden nur
   im Admin angelegt, bearbeitet und gelöscht, auch Zweck und Beschreibung; dafür sind
   Staff-Rechte nötig. Auf den Inventarseiten sind Zweck, Beschreibung, Foto, Ort und Löschen
   gesperrt. Was darin steht (Regale, Kisten, Bestand), lässt sich weiter
   bewegen, und neue Regale und Schränke werden dort angelegt.
5. **Regale, Schränke und Kisten** gehören nicht zur Gebäudestruktur. Sie haben eigene Codes
   (`R303`, `K034c`) und hängen in dem Raum oder Bereich, in dem sie stehen; Regale und Schränke
   auch auf einer Palette dort.
6. **Kennungen sind fest.** Einmal vergebene Codes bleiben beim Ort, damit Labels und Links mit
   dem Code dauerhaft gelten (siehe [Kennungen bleiben](#kennungen-bleiben)).

## Gebäudeteile, Lagermöbel und Behälter

Jeder Standort gehört über seinen Typ zu einer von drei Kategorien:

| Kategorie | Was | Typen |
|---|---|---|
| **Gebäudeteil** | Teil des Gebäudes, bewegt sich nie | Haus+Ebene, Raum, Bereich, Teilraum, Teilbereich |
| **Lagermöbel** | Möbel zum Aufbewahren und Lagern, samt Fächern und Schüben | Regal, Schrank, Werkbank mit Schubladen, Werkzeugwagen, Rollcontainer, Fach/Schub |
| **Behälter** | wandert mit seinem Inhalt durchs Haus | Kiste, Karton, Palette |

Lagermöbel bleiben Lagermöbel, auch wenn sie Rollen haben. *Mobil* (unterwegs oder verliehen)
hat keine Kategorie. Die Standortseite listet die Unterstandorte je Kategorie in einem eigenen
Kasten: unter „Hier befinden sich …“ links die Sachen, rechts Gebäudeteile, Lagermöbel und
Behälter. Bei den Lagermöbeln legt **+** ein neues an (wie der Knopf **Regal / Schrank**), bei
den Behältern holt der Knopf daneben weitere hierher (wie **Hierher bewegen**).

## Häuser und Ebenen

| Code | Haus |
|---|---|
| `WH` | Werkhaus |
| `HH` | Haupthaus |

Ebenen zählen hausübergreifend: **0 ist die Ebene, die zur Hauptstraße ebenerdig liegt.** Gleiche
Zahlen liegen ungefähr auf gleicher Höhe; die Böden weichen um bis zu 1,5 m ab. Der Code trägt
immer ein Vorzeichen: `WH-1`, `WH+0`, `HH+3`. Auf Schildern und im Gespräch reicht „Ebene 1“.
Das Pflichtvorzeichen verhindert, dass ein verlorenes Minus lautlos zur falschen Ebene führt.

Das Werkhaus hat die Ebenen −1 bis +3 (die Straße am Werkhaus liegt auf −1), das Haupthaus −2
bis +3.

## Codes für Räume und Bereiche

* **Raum**: Wände und Tür. **Bereich**: Fläche ohne eigene Wände (Bühne, Teil eines Atriums,
  Außenfläche).
* Zeichen: `A–Z`, `0–9`; `+` und `-` nur in Ebenen- und Treppencodes. Der Punkt trennt nur den
  Pfad.
* **Eigene Codes** (2–3 Buchstaben) bekommen nur Orte, deren Name im Haus eingeführt ist oder
  deren Nutzung baulich festliegt („in Beton gegossen“), z. B. `CHE` Chemieraum, `LAS`
  Laserraum, `DUK` Dunkelkammer, `SRV` Serverraum, `SEM` Seminarraum, `KUE` Gemeinschaftsküche,
  `GSL` Greiners Schraubenlager, `MSL` Metallwerkstatt-Schraubenlager.
* **Alle anderen** bekommen einen generischen Stamm mit hausweit laufender Nummer, vergeben von
  unten nach oben, Werkhaus vor Haupthaus, in einer Ebene nach Achse von links nach rechts.
  Nummern werden nie wiederverwendet.

| Stamm | Bedeutung | Beispiel |
|---|---|---|
| `WC` | WC, WC-Bereich, Bad | `WC8` WC-Bereich Haupthaus 1 |
| `TGA` | Technikraum (Heizung, Anschluss, Aufzug, Lüftung) | `TGA3` Heizungskeller |
| `LAG` | Lagerraum, Dachboden mit Lagernutzung | `LAG7` Lampenlager |
| `RA` | Raum ohne eingeführten Namen | `RA1` Bits'n'Bugs Clubraum |
| `GB` | Großraumbüro | `GB1` Co-Working |
| `VR` | Vorraum | `VR2` Vorraum Bad Wohnung neu |
| `AUS` | Außenbereich | `AUS2` Westliche Stadtmauerstraße 58 |
| `DA` | Dach, Flachdach, Dachterrasse | `DA3` Dachterrasse |
| `DS` | Dachstuhl | `DS1` Dachstuhl West |
| `TR` | Erschließung: Treppenhaus, Außentreppe, Verbindungsflur | siehe unten |
| `AZ` | Aufzugkabine; hängt an der Ebene ihres Technikraums | `AZ1` Aufzugkabine Werkhaus |

**Erschließung**: `TR` + Nummer der Treppe + Ebene mit Vorzeichen, ein Knoten pro Ebene:
`TR1+0` bis `TR1+2` (Treppenhaus 1 im Werkhaus), `TR2-1` bis `TR2+2` (Treppenhaus 2 im
Haupthaus). Auch ebene Verbindungsflure heißen so (`TR3+0`). Zwischenpodeste sind Teil des
Abschnitts darunter (`TR8+0.1`).

**Ebenenziffer statt laufender Nummer** haben Räume, die es nur im Haupthaus und dort auf mehreren
Ebenen gibt: Atrium 0/1 (`ATR0`, `ATR1`), Vortrag 0/1 (`V0`, `V1`).

**Lokale Teile** eines Raums oder Bereichs sind nur Nummern, eindeutig unter ihrem Elternteil,
übereinander von unten gezählt: `HBB.1` Holzbaubühne unten, `HBB.2` oben. Sie werden immer mit
dem Elternteil geschrieben. Direkt unter einer Ebene gibt es keine bloßen Nummern
(`HH+1.1` wäre leicht mit `HH+1` zu verwechseln); dort bekommt jeder Ort einen Code.

**Kurzform**: Ab dem nächsten eindeutigen Glied darf alles davor wegfallen:
`HH+1.WC8.2` = `WC8.2`. Die Kurzform passt in der Regel in 6 Zeichen und damit in den kleinsten
QR-Code mit `i.zam.haus`.

## Achsen

Achsen sind senkrechte Spalten: Was in einer Achse steht, liegt ungefähr übereinander. Jeder Ort
direkt unter einer Ebene hat eine Achse, seine Teile erben sie. Achsen stehen nicht im Code,
ihre Namen taugen aber als Lagemerkmal im Namen („Großraumbüro Mitte“).

| Nr. | Achse | Haus |
|---|---|---|
| 1 | Treppenhaus 1 | Werkhaus |
| 2 | Werkhaus | Werkhaus |
| 3 | Passerelle | zwischen den Häusern, hängt an `WH+0` |
| 4 | Hof | Haupthaus |
| 5 | West | Haupthaus |
| 6 | Rampe | Haupthaus |
| 7 | Turm | Haupthaus |
| 8 | Mitte | Haupthaus |
| 9 | Atrium | Haupthaus |
| 10 | Hauptstraße, mit Treppenhaus 2 | Haupthaus |

## Name und Zweck

* **Name**: baulich, für sich verständlich und im ganzen Haus eindeutig, auch ohne Pfad lesbar.
  Mehrfach vorkommende Raumarten bekommen ein Lagemerkmal: eine Eigenschaft („barrierefrei“,
  „West“, „zum Innenhof“) oder „Haus Ebene n“. Teile tragen das Ganze im Namen
  („Holzbaubühne oben“). Bereiche dürfen nach ihrer Nutzung heißen (Biowerkstatt, Lounge).
* **Zweck**: was dort heute passiert, auch wenn es dem Bau nicht entspricht (`SK.4` ist ein
  Lagerbereich und dient als Myzellabor). Hat ein Ort einen Zweck, wird er mit **Code und Zweck**
  genannt: „`RA1` Bits'n'Bugs Clubraum“, sonst mit Code und Name. Ein Zweck muss mehr sagen als
  der Name, eine Nutzung beschreiben (keinen Gegenstand, keinen Vertragsstand) und kurz genug
  fürs Label sein. Bereiche, deren Name schon die Nutzung trägt, haben keinen Zweck.
* **Beschreibung**: Bauliches, Lage, Zugang, Ausstattung („Zugang nur über LAG5“,
  „mit Badewanne“, „früher Chefbüro“, „an das Schauspiel vermietet“).

## Zuständigkeit

Zuständig sind ein oder mehrere Teams (z. B. D + T). Die Zuständigkeit gilt für Regale, Kisten
und nummerierte Teile eines Orts, aber nicht für andere Räume oder Bereiche mit eigenem Code:
Die Halle `WH-1` gehört der Holzwerkstatt, das WC daneben nicht. Ein Team kann zu einer
Obergruppe gehören; ohne eigene Farbe zeigt es deren Farbe.

| Kürzel | Team | Farbe | Schrift |
|---|---|---|---|
| A | Ausprobierwerkstatt | `#3ea02e` | schwarz |
| B | Biowerkstatt (in A) | wie A | schwarz |
| D | Druckwerkstatt | `#744a97` | weiß |
| E | Elektronikwerkstatt (in P) | `#00a19d` | schwarz |
| F | Farbenwerkstatt | `#fab1b1` | schwarz |
| H | Holzwerkstatt | `#7d3a2d` | weiß |
| K | Küchenwerkstatt | `#70bddd` | schwarz |
| M | Metallwerkstatt | `#000000` | weiß |
| P | Prototypenwerkstatt | `#d29154` | schwarz |
| T | Textilwerkstatt | `#f3e634` | schwarz |
| ⌂ | Hausmeisterei | `#ffffff` | schwarz |
| IT | ZAM-IT | `#ffffff` | schwarz |

Kürzel werden nicht als Kennung aufgelöst und stehen nicht auf Labels. Die Schriftfarbe ergibt
sich aus dem Kontrast und muss nicht gepflegt werden.

**Personen als Zuständige** sind vorgesehen, aber noch nicht umgesetzt. Sie sind
personenbezogene Daten: Eine Person wird nur mit ihrer Zustimmung eingetragen und wählt selbst,
wer Name, E-Mail und Telefon sieht. Immer sichtbar sind Vorname, Initial des Nachnamens und
Username für die Gruppe *ZAM-local*, voller Name und E-Mail für die Gruppe *Aktive*; Admins sehen
alles.

## Regale, Schränke und Fächer

Regale, Schränke und Fächer gehören nicht zur Gebäudestruktur, aber ihre Nummern folgen ihr:
**Jeder Raum oder Bereich mit Regalen hat einen Nummernkreis**, meist einen Hunderter. So haben
Regale im selben Bereich ähnliche Nummern, und an der Nummer erkennt man ungefähr, wo ein Regal
steht.

| Art | Code | Regel |
|---|---|---|
| Regal | `R` + Nummer, mindestens dreistellig (`R003`, `R303`) | nächste freie Nummer im Kreis des Raums oder Bereichs |
| Schrank (auch Schubschrank) | `S` + Nummer, mindestens dreistellig (`S303`) | wie Regale, aber mit eigenen Kreisen |
| Fach, Schublade | Kleinbuchstaben `a`–`z`, dann `aa`, `ab` … | je Regal oder Schrank fortlaufend, von unten nach oben |
| Fach in Stangen- und Blechregalen | Großbuchstabe, bei Rastern mit Zahl (`P`, `A1`, `G5`) | Spalte und Ebene des Rasters |

**Kreise wirken nach unten:** Ein Kreis gilt für alles unter seinem Ort, auch für Räume und
Bereiche mit eigenem Code. Ein Teil darunter kann sich einen Abschnitt davon reservieren; den
bekommen dann nur er und seine Teile. Beispiel: `WH+1` hat 100–199, `DRU` reserviert 150–199.
Neue Regale in `TEX` oder direkt auf `WH+1` bekommen dann 100–149, in `DRU` 150–199.

Ein Fach wird mit seinem Regal genannt: `R303.a`. Der volle Pfad nennt den Raum davor
(`WH-1.R303.a`). Auch sein Name nennt das Regal oder den Schrank: **„Regal 303 Fach a“**,
„Schrank 300 Fach b“. Fächer mit eigenem Namen („Ebene A“) behalten ihn.

### Vergebene Nummernkreise

Jeder Kreis gilt für genau einen Typ.

| Kreis | Typ | Raum oder Bereich | Belegt |
|---|---|---|---|
| 000–099 | Regal | `GSL` Greiners Schraubenlager (`WH+1`) | R003–R013 |
| 100–199 | Regal | `RA1` Bits'n'Bugs Clubraum (`WH+2`) | R100–R127 |
| 200–299 | Regal | `SK` Südkeller (`HH-1`) | R200–R234 |
| 300–399 | Regal | `WH-1` Halle, Holzwerkstatt | R300–R303 |
| 300–399 | Schrank | `WH-1` Halle, Holzwerkstatt | S300–S303 |
| 400–449 | Regal | `MSL` Metallwerkstatt-Schraubenlager (`HH+0`) | R400–R411 |
| 450–499 | Regal | `LAG2` Stangenlager (`HH-2`) | R450 |
| ab 500 | – | frei für weitere Räume und Bereiche | – |

Die vorhandenen Kreise sind Hunderter oder halbe Hunderter. **Neue Kreise entstehen beim ersten
Regal** eines Bereichs, so groß wie die erwartete Zahl, und liegen in der Mitte der größten freien
Lücke, auf Zehner gerundet. So bleibt hinter dem neuen Kreis und hinter dem davor Platz, falls
einer wachsen muss. Als belegt zählen auch Nummern, die außerhalb eines Kreises vergeben sind
(z. B. `R998`). Im Admin lassen sich Kreise auch direkt anlegen; dort ist eine neue Zeile mit
20 Nummern nach derselben Regel vorbelegt.

Nummernkreise pro Bereich gibt es nur für Lagermöbel mit hausweit eindeutigem Code (Regale,
Schränke). Kisten, Kartons und Paletten wandern durchs Haus und werden hausweit fortlaufend
nummeriert.

### Neue Regale und Schränke anlegen

Neue Regale und Schränke werden auf der Seite des Raums oder Bereichs angelegt, in dem sie stehen,
oder auf der Seite der Palette, auf der sie stehen, mit dem grünen Knopf **Regal / Schrank**. Auf
einer Palette gilt der Kreis des Raums oder Bereichs, in dem sie steht; Nummern werden immer für
den Raum oder Bereich reserviert, nie für die Palette. Zuerst wird gefragt, was angelegt wird, dann die Nummer:

* **Reservierte Nummer:** eine freie Nummer aus dem Kreis, der hier gilt; die nächste ist
  vorausgewählt.
* **Wunschnummer:** jede Nummer, die weder vergeben noch irgendwo reserviert ist. Mit einer
  erwarteten Anzahl über 1 werden die folgenden Nummern für diesen Bereich reserviert.
* **Neue Nummer, automatisch:** reserviert so viele Nummern wie erwartet, hinter einem
  aufgebrauchten Kreis oder mittig in der größten freien Lücke; die erste wird vergeben.

Es sind immer nur die Felder der gewählten Art zu sehen und zählen; bei der Wunschnummer steht
das Kürzel (`R`, `S`) schon vor dem Feld, einzugeben ist nur die Zahl.

**Reihenfolge:** Nebeneinander stehende Regale bekommen aufeinanderfolgende Nummern, links die
kleinere; ein neues kommt ans Ende der Reihe. **Fächer und Schübe** werden von unten nach oben
benannt, beginnend mit `a`. Die Anlegeseite zeigt das als Bild und legt auf Wunsch gleich die
gewünschte Zahl Fächer mit an (`R301.a` „Regal 301 Fach a“, `R301.b` …). Weitere Fächer kommen später über den
Knopf **Fach/Schub** auf der Seite des Regals oder Schranks dazu; sie bekommen die nächsten
freien Buchstaben, also die oberen Fächer. Nach `z` geht es mit `aa`, `ab` … weiter.
Wer Standorte ändern darf, kommt danach auf eine Seite, auf der sich die Zwecke der neuen
Fächer gleich eintragen lassen (optional, „Überspringen“ geht direkt zum Regal). Die Felder
stehen dort so, wie die Fächer sitzen: das oberste oben, `a` ganz unten, daneben das Bild.

Regale und Schränke haben je eigene Kreise; der erste Schrank in einem Bereich reserviert seine
Nummern unabhängig von den Regalen.

### Umziehen und Paletten

Regale und Schränke lassen sich bewegen (**Bewegen** auf ihrer Seite, **Hierher bewegen** am
Ziel), aber nur in eine Ebene, einen Raum, einen Bereich oder auf eine Palette, nicht in ein Fach
oder ein anderes Regal und nie ganz ohne Ort. Eine Palette nimmt ihr Regal beim Bewegen mit. Ein Regal behält beim
Umzug seine Nummer, auch wenn sie nicht zum Kreis des neuen Orts passt.

## Kennungen bleiben

Codes werden auf den Inventarseiten nie geändert; das Kürzel lässt sich nur im Admin ändern.
Ändert sich dort ein Code (anderes Kürzel, oder ein Teil wie `R301.a`, dessen Regal umbenannt
wird), bleibt der alte als **frühere Kennung** am Ort: Er führt in Suche, Scan und **Hierher
holen** weiter dorthin und wird nie an einen anderen Ort vergeben, auch nicht als freie Nummer
oder freier Fachbuchstabe. Wird ein Ort endgültig gelöscht, bleibt sein Code ohne Ort gesperrt.
Die Standortdetails zeigen frühere Kennungen. Im Admin lassen sich Einträge entfernen (der Code
ist dann wieder frei) oder von Hand hinzufügen, z. B. für alte Labels.

### Kisten, Kartons und Paletten anlegen

Kisten, Kartons und Paletten werden auf der Seite des Orts angelegt, an dem sie stehen (Raum,
Bereich, Regal, Fach oder Palette, aber nicht in einer Kiste oder einem Karton), mit dem grünen
Knopf **Karton / Kiste / Palette** oder dem **+** beim Kasten „Behälter“. Eine Nummer wählt man
nicht: Jeder Typ zählt hausweit aufsteigend weiter, nach der höchsten vergebenen Nummer (die
nächste steht bei der Auswahl dabei, z. B. „Kiste · K0525“). Frühere Kennungen zählen als vergeben.

Beim Anlegen von Regalen, Schränken, Kisten, Kartons und Paletten wird neben dem Zweck auch die
**physische Beschreibung** abgefragt (Farbe, Material, Größe, Zahl der Böden …). Später lässt sie
sich wie der Zweck auf der Standortseite ändern (Knopf **Beschreibung**); bei Gebäudeteilen ändern
beides nur Admins.

### Nur Ziffern oder nur Buchstaben

Nummern bestehen nur aus Ziffern (Regale, Schränke, Kisten, Kartons, Paletten) oder nur aus
Buchstaben (Fächer). Kisten waren bisher hexadezimal nummeriert (`K034c`), Paletten
alphanumerisch. Ihre vorhandenen Codes bleiben, neue werden dezimal vergeben; belegte Codes
überspringt das Anlegen. Neue Kisten zählen nach der höchsten rein dezimalen Nummer weiter, also
ab `K0525`, oberhalb aller alten Codes.

### Bestehende Abweichungen

Regale behalten ihre Nummer, auch wenn sie umziehen oder nicht in den Kreis ihres Raums passen,
denn ihre Labels hängen schon. Das betrifft:

* `R998`, `R999` und `R1000`–`R1002` im Südkeller, außerhalb seines Kreises.
* `SR1`–`SR3` und `BR` (Stangen- und Blechregale) in der Metallwerkstatt (`MW`),
  `SR4`–`SR6` im Stangenlager (`LAG2`).

## Brandlastfrei und außen

**Brandlastfrei** heißt: Dort dürfen keine brennbaren Materialien lagern. Die Eigenschaft gilt
für alles darin. Brandlastfrei sind alle Dachböden außer dem über Atrium Süd (`LAG6`), die
Lagerräume im Turm (`LAG3`, `LAG5`), die Treppenhäuser 1 und 2, der Flur beim Seminarraum
(`TR3+0`) und die Treppe der alten Wohnung (`TR7`).

**Außen** sind Hof, Innenhof, Dächer, Außentreppen und die Außenbereiche an den Straßen.

## Noch nicht umgesetzt

* Warnung beim Einlagern an brandlastfreien Orten.
* Personen als Zuständige mit eigener Sichtbarkeit.

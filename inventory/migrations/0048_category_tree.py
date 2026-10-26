"""
The category tree of the ZAM (shops used as models: Dresselhaus, Hoffmann, Hornbach, boesner, Nähpark,
stoffe.de). Each description says in its first line what belongs there and then, after "Nicht hier:",
where the usual borderline cases go; the item forms show it when a category is chosen. Keywords let the
category choice find a category by words its name and description lack (Rohrschelle, Inbus, Spax).

The six earlier categories become nodes of the tree in place (same primary keys, so items and the change
log keep them); a category not in the tree stays as it is. Names contain no "/": it separates the
levels of full_name. Historical models do not compute full_name
(django-computedfields), so this migration sets it.
"""
from django.db import migrations, models


def c(name, description, *children):
    return name, description, children


TREE = [
    c("Schlösser & Schlüssel",
      "Schlösser, Schließzylinder, Schließbleche und Schlüssel samt Rohlingen.\n"
      "Nicht hier: Schraubenschlüssel → Handwerkzeuge/Schraubenschlüssel & Nüsse; Drücker und Rosetten → "
      "Beschläge/Türbeschläge",
      c("Schließzylinder",
        "Profil-, Halb-, Knauf- und Servicezylinder, auch mit Schlüsseln, und Zylinderzubehör (Brücken, "
        "Verlängerungen).\nNicht hier: Möbelschlösser mit eigenem Zylinder → Riegel-, Möbel- & Vorhängeschlösser"),
      c("Einsteck- & Kastenschlösser",
        "Einsteckschlösser (Zimmer-, Bad-, Haus- und Rohrrahmentüren), Einsteckfallen und -getriebe, "
        "Kastenschlösser, Panikschlösser.\nNicht hier: Riegelschlösser → Riegel-, Möbel- & Vorhängeschlösser"),
      c("Riegel-, Möbel- & Vorhängeschlösser",
        "Riegelschlösser (aufliegend oder einlassbar), Möbel-, Schrank-, Schiebetür- und Glastürschlösser, "
        "Vorhängeschlösser.\nNicht hier: Türriegel ohne Schloss → Riegel, Überfallen & Türöffner"),
      c("Schließbleche & Schließkästen",
        "Schließbleche und Winkelschließbleche, Schließkästen, Schließbolzen und -nocken.\n"
        "Nicht hier: Einsteckfallen → Einsteck- & Kastenschlösser"),
      c("Riegel, Überfallen & Türöffner",
        "Schlossriegel, Rohrkant-, Dreh- und Schubriegel, Überfallen, elektrische Türöffner, Tür- und "
        "Kindersicherungen.\nNicht hier: Riegelschlösser → Riegel-, Möbel- & Vorhängeschlösser"),
      c("Schlüsselrohlinge & Schlüsselkerne",
        "Rohlinge für Zylinderschlüssel und Schlüsselkerne (Möbel- und Briefkastenschlösser).\n"
        "Nicht hier: Bartschlüssel und ihre Rohlinge → Bartschlüssel"),
      c("Bartschlüssel",
        "Bartschlüssel und Rohlinge für Bartschlüssel, Nachschlüssel für Buntbartschlösser."),
      c("Schlüsselzubehör",
        "Schlüsselringe, -anhänger und -schilder, Schlüsselkästen und Schlüsselsafes."),
      ),
    c("Beschläge",
      "Teile, die fest an Türen, Fenstern, Möbeln oder Wänden montiert werden.\n"
      "Nicht hier: Schlösser und Schließbleche → Schlösser & Schlüssel; lose Schrauben, Dübel, Muttern → "
      "Befestigungstechnik",
      c("Türbeschläge",
        "Beschläge für Türen und Tore. Spione, Türstopper, Puffer und Tor-Feststeller direkt hier.\n"
        "Nicht hier: Schlösser → Schlösser & Schlüssel",
        c("Drücker, Knäufe & Drückerstifte",
          "Türdrücker und Drückergarnituren, Türknäufe, Stoßgriffe, Wechsel- und Vierkantstifte.\n"
          "Nicht hier: Fenstergriffe → Fensterbeschläge; Möbelgriffe → Möbelbeschläge"),
        c("Rosetten & Schilder",
          "Rosetten (Drücker-, Schlüssel-, Zylinderrosetten), Kurz- und Langschilder, Schutzbeschläge.\n"
          "Nicht hier: Türschilder mit Beschriftung → Möbel, Haus & Garten/Schilder & Hausnummern"),
        c("Türbänder & Bandzubehör",
          "Einbohr-, Aufschraub-, Aufsatz- und Pendeltürbänder, Fitschen, Bandaufnahmen, Klemmblöcke, "
          "Flügelteile und Ersatzstifte.\nNicht hier: Möbelscharniere → Möbelbeschläge; Fensterbänder → "
          "Fensterbeschläge"),
        c("Türschließer & Feststeller",
          "Obentürschließer, Gleitschienen und Gestänge, Montageplatten, Türfeststeller und "
          "Magnethaftungen."),
        c("Schiebetürbeschläge",
          "Laufschienen, Laufwerke und Führungen für Schiebetüren, Schiebetürmuscheln und -griffe."),
        ),
      c("Fensterbeschläge",
        "Fenstergriffe, Oliven, Fensterbänder, Dreh-Kipp-Beschläge, Fensterriegel und -feststeller.\n"
        "Nicht hier: Lüftungsgitter → Möbel, Haus & Garten/Lüftung"),
      c("Möbelbeschläge",
        "Beschläge für Möbel, Schränke, Kisten und Koffer.",
        c("Schubkastensysteme & Auszüge",
          "Schubkastenzargen (z. B. Blum Tandembox, Legrabox), Auszugführungen, Unterbodenführungen und "
          "Zubehör."),
        c("Scharniere, Klappen & Schnäpper",
          "Topf- und Möbelscharniere, Schrankbänder, Klappenhalter, Magnet- und Kugelschnäpper."),
        c("Möbelgriffe & Kistenbeschläge",
          "Möbelgriffe und -knöpfe, Kisten- und Koffergriffe, Kistenverschlüsse, -bänder und -ecken."),
        c("Verbinder & Bodenträger",
          "Möbelverbinder (Exzenter, Verbindungsbolzen, Platten- und Bettverbinder), Bodenträger, "
          "Schrankaufhänger, Rückwandhalter.\nNicht hier: Möbelverbindungsschrauben → "
          "Befestigungstechnik/Holzschrauben"),
        c("Gleiter & Möbelfüße",
          "Möbel-, Stuhl- und Teppichgleiter, Möbelfüße, Höhenversteller, Untersetzer, Schutz- und "
          "Wandpuffer.\nNicht hier: Möbelrollen → Technischer Bedarf/Rollen & Räder"),
        c("Rohrkappen & Stopfen",
          "Rohrkappen, Lamellen- und Abdeckstopfen, Abdeckkappen, Einsteckbuchsen für Rohre."),
        ),
      c("Haken & Ösen",
        "Wand-, Garderoben-, Decken- und S-Haken, Hakenleisten, Schraubhaken und -ösen, Bilderösen, Schlaufen.\n"
        "Nicht hier: Karabiner → Technischer Bedarf/Ketten, Seile & Zubehör"),
      c("Halter & Aufhänger",
        "Halter für bestimmte Dinge: Wand-, Geräte-, Handtuch-, Fahrrad- und Krawattenhalter, Aufhänger, "
        "Bilderschienen.\nNicht hier: Rohrschellen → Technischer Bedarf/Schellen & Kabelbinder"),
      c("Konsolen & Regalträger",
        "Konsolen, Regalträger und -schienen, Stützen und Bodenträger für Wandregale.\n"
        "Nicht hier: Bodenträger für Schränke → Möbelbeschläge/Verbinder & Bodenträger"),
      c("Winkel, Bleche & Holzverbinder",
        "Montagewinkel, Verbindungs-, Loch- und Stegbleche, Lochplatten, Balkenschuhe, Stützenfüße.\n"
        "Nicht hier: Anschlagwinkel zum Messen → Handwerkzeuge/Messen & Anreißen"),
      ),
    c("Befestigungstechnik",
      "Lose Verbindungselemente: Schrauben, Muttern, Scheiben, Dübel, Nägel, Nieten.\n"
      "Nicht hier: Beschläge → Beschläge; Lager, Federn, Dichtungen → Technischer Bedarf",
      c("Holzschrauben",
        "Schrauben mit Holzgewinde: Spanplatten-, Universal-, Holzbau-, Terrassen- und "
        "Möbelverbindungsschrauben.\nNicht hier: Schrauben für Blech → Blech- & Bohrschrauben"),
      c("Metrische Schrauben",
        "Schrauben mit metrischem Gewinde nach Norm. Benennung: die DIN-Nummer; eine ISO-Nummer nur, wenn es "
        "keine DIN gibt. Was zu keiner Unterkategorie passt, direkt hier.\nNicht hier: Muttern → Muttern; "
        "Scheiben → Scheiben & Sicherungselemente",
        c("DIN 933 Sechskantschrauben, Vollgewinde", "Sechskantschrauben mit Gewinde bis zum Kopf."),
        c("DIN 931 Sechskantschrauben mit Schaft", "Sechskantschrauben mit Teilgewinde."),
        c("DIN 912 Zylinderschrauben, Innensechskant", "Zylinderkopfschrauben mit Innensechskant (Inbus)."),
        c("ISO 7380 Linsenkopfschrauben, Innensechskant", "Flache Linsenköpfe mit Innensechskant."),
        c("DIN 7991 Senkschrauben, Innensechskant", "Senkkopfschrauben mit Innensechskant."),
        c("DIN 7985 Linsenschrauben, Kreuzschlitz", "Linsenkopfschrauben mit Kreuzschlitz (Phillips)."),
        c("DIN 965 Senkschrauben, Kreuzschlitz", "Senkkopfschrauben mit Kreuzschlitz."),
        c("DIN 84 Zylinderschrauben, Schlitz", "Zylinderkopfschrauben mit Schlitz."),
        c("DIN 603 Flachrundschrauben", "Flachrundschrauben mit Vierkantansatz (Schlossschrauben)."),
        c("DIN 913–916 Gewindestifte", "Gewindestifte (Madenschrauben) mit Kegel-, Zapfen-, Ring- oder "
          "Spitzenende."),
        c("DIN 975, DIN 976 Gewindestangen", "Gewindestangen und -bolzen."),
        ),
      c("Muttern",
        "Muttern mit metrischem Gewinde. Was zu keiner Unterkategorie passt, direkt hier.",
        c("DIN 934 Sechskantmuttern", "Normale Sechskantmuttern."),
        c("DIN 985 Sicherungsmuttern", "Sechskantmuttern mit Klemmteil (Nylon)."),
        c("DIN 1587 Hutmuttern", "Sechskant-Hutmuttern, hohe Form."),
        c("DIN 315 Flügelmuttern", "Flügelmuttern."),
        c("Einschlagmuttern & Gewindeeinsätze",
          "Einschlag- und Einpressmuttern, Rampa-Muffen, Einnietmuttern, Gewindeeinsätze (Helicoil)."),
        ),
      c("Scheiben & Sicherungselemente",
        "Scheiben und Elemente, die Schraubverbindungen sichern.",
        c("DIN 125 Unterlegscheiben", "Flache Scheiben für Sechskantschrauben und -muttern."),
        c("DIN 9021 Scheiben, große Außendurchmesser", "Scheiben mit etwa dreifachem Außendurchmesser "
          "(Karosseriescheiben)."),
        c("DIN 127, DIN 6798 Federringe & Zahnscheiben", "Federringe, Zahn- und Fächerscheiben."),
        c("DIN 471, DIN 472, DIN 6799 Sicherungsringe & -scheiben", "Sicherungsringe für Wellen und Bohrungen, "
          "Sicherungsscheiben."),
        ),
      c("Blech- & Bohrschrauben",
        "Blechschrauben und Bohrschrauben (DIN 7981, 7982, 7504), auch Fassadenschrauben."),
      c("Dübel & Anker",
        "Dübel und Anker für Beton, Mauerwerk und Platten.",
        c("Kunststoffdübel", "Spreiz-, Universal- und Rahmendübel aus Kunststoff."),
        c("Hohlraum- & Plattendübel", "Gipskarton-, Kipp- und Federklappdübel, Hohlraum-Metalldübel."),
        c("Metall- & Schwerlastanker", "Bolzen-, Schwerlast- und Einschlaganker, Betonschrauben."),
        c("Injektionssysteme", "Injektionsmörtel, Ankerstangen, Siebhülsen und Zubehör."),
        ),
      c("Nägel & Drahtstifte",
        "Drahtstifte, Nägel, Stauchkopf- und Dachpappstifte, Klammern zum Einschlagen.\n"
        "Nicht hier: Tackerklammern → Stifte, Nieten & Klammern"),
      c("Stifte, Nieten & Klammern",
        "Splinte, Spann-, Zylinder- und Kegelstifte, Blindnieten, Tackerklammern und Heftklammern für "
        "Handtacker.\nNicht hier: Büroklammern → Büro & IT/Büromaterial"),
      ),
    c("Technischer Bedarf",
      "Maschinenelemente und technisches Zubehör: Ketten, Seile, Schellen, Lager, Rollen, Dichtungen, Federn.\n"
      "Nicht hier: Schrauben und Dübel → Befestigungstechnik",
      c("Ketten, Seile & Zubehör",
        "Ketten, Drahtseile, Seile und Tauwerk, Karabiner, Schäkel, Kauschen, Seil- und Drahtseilklemmen."),
      c("Schellen & Kabelbinder",
        "Schlauch-, Rohr- und Gelenkschellen, Kabelbinder.\nNicht hier: Kabelkanäle → Elektro & "
        "Elektronik/Installationsmaterial"),
      c("Lager & Buchsen",
        "Kugel- und Gleitlager, Lager- und Führungsbuchsen, Führungsringe, Achsen."),
      c("Rollen & Räder",
        "Lenk-, Bock-, Möbel- und Laufrollen, Räder, Seilrollen.\nNicht hier: Schiebetür-Laufwerke → "
        "Beschläge/Türbeschläge/Schiebetürbeschläge"),
      c("Dichtungen & O-Ringe",
        "O-Ringe, Flach- und Gummidichtungen, Dichtband und Dichtfaden."),
      c("Schmiernippel, Stellringe & Federn",
        "Schmiernippel, Stellringe, Druck-, Zug- und Tellerfedern, Passfedern, Achsen."),
      ),
    c("Handwerkzeuge",
      "Werkzeug ohne Motor. Was in keine Unterkategorie passt (z. B. Entgrater, Nietzangen, Spachtel), "
      "direkt hier.\nNicht hier: Malerwerkzeug → Oberfläche & Chemie/Maler- & Lackierwerkzeug; Nähwerkzeug → "
      "Textil & Nähen",
      c("Schraubendreher & Bits",
        "Schraubendreher, Bits, Bithalter und -adapter.\nNicht hier: Innensechskantschlüssel → "
        "Schraubenschlüssel & Nüsse"),
      c("Schraubenschlüssel & Nüsse",
        "Ring-, Maul-, Ringmaul- und Innensechskantschlüssel, Steckschlüssel, Nüsse, Ratschen, "
        "Drehmomentschlüssel."),
      c("Zangen",
        "Kombi-, Seitenschneider-, Spitz-, Wasserpumpen-, Crimp-, Abisolier- und Sicherungsringzangen, "
        "Pinzetten."),
      c("Hämmer & Schlagwerkzeuge",
        "Hämmer, Fäustel, Äxte, Hammer- und Fäustelstiele, Meißel, Körner, Durchtreiber, Schlagstempel."),
      c("Sägen, Feilen & Schneidwerkzeuge",
        "Handsägen und ihre Blätter, Feilen, Raspeln, Messer und Klingen, Scheren, Hobel und Hobeleisen, "
        "Stemmeisen, Locheisen.\nNicht hier: Maschinensägeblätter → Maschinen & Elektrowerkzeuge/"
        "Einsatzwerkzeuge"),
      c("Zwingen & Spannwerkzeuge",
        "Schraub- und Einhandzwingen, Spanner, Schraubstöcke."),
      c("Messen & Anreißen",
        "Zollstöcke, Maßbänder, Messschieber, Anschlagwinkel, Wasserwaagen, Lehren, Anreißwerkzeug, "
        "Schablonen, Laser-Entfernungsmesser.\nNicht hier: elektrische Messgeräte → Elektro & Elektronik/"
        "Löten & Messen"),
      ),
    c("Maschinen & Elektrowerkzeuge",
      "Geräte mit Antrieb und ihr Zubehör.\nNicht hier: Nähmaschinen → Textil & Nähen/Nähmaschinen & Geräte; "
      "Druckpressen und Risograph → Druck",
      c("Elektrowerkzeuge",
        "Handgeführte Maschinen mit Akku oder Kabel (Bohrmaschinen, Schrauber, Schleifer, Sägen, Fräsen), "
        "Akkus, Ladegeräte und Ersatzteile."),
      c("Stationäre Maschinen",
        "Tisch-, Kapp- und Bandsägen, Standbohrmaschinen, Drehbänke, Fräsmaschinen, Schleifböcke, "
        "Absauganlagen."),
      c("Digitale Fertigung",
        "3D-Drucker, Lasercutter, CNC-Fräsen, Schneideplotter und ihr Verbrauchsmaterial (Filament, Folien)."),
      c("Einsatzwerkzeuge",
        "Bohrer, Lochsägen, Bohrkronen, Senker, Maschinensägeblätter, Fräser, Bohrfutter, Adapter.\n"
        "Nicht hier: Schleifscheiben → Oberfläche & Chemie/Schleifmittel; Bits → Handwerkzeuge/"
        "Schraubendreher & Bits"),
      c("Druckluft",
        "Kompressoren, Druckluftwerkzeuge, Schläuche, Kupplungen, Wartungseinheiten."),
      c("Schweißen & Hartlöten",
        "Schweißgeräte, Elektroden, Schweißdraht, Strom- und Gasdüsen, Brenner, Hartlot.\n"
        "Nicht hier: Elektronik-Löten → Elektro & Elektronik/Löten & Messen; Schutzausrüstung → "
        "Arbeitsschutz & Sicherheit"),
      ),
    c("Oberfläche & Chemie",
      "Schleifen, Beschichten, Kleben, Schmieren und Reinigen in Werkstatt und Haus.\n"
      "Nicht hier: Künstlerfarben → Kunst- & Malbedarf; Textilfarben → Textil & Nähen",
      c("Schleifmittel",
        "Schleifmittel zum Schleifen und Polieren.",
        c("Schleifblätter & -streifen", "Schleifpapier, -bögen und -streifen, Schleifklötze, Schleifschwämme."),
        c("Schleifscheiben & Fiberscheiben", "Klett-Schleifscheiben, Fiberscheiben, Fächer-, Trenn- und "
          "Schruppscheiben."),
        c("Schleifbänder, Vlies & Polieren", "Schleifbänder und -rollen, Schleifvlies, Stahlwolle, "
          "Drahtbürsten, Polierscheiben und -pasten, Schleifmops."),
        ),
      c("Lacke, Farben & Holzschutz",
        "Wand- und Bodenfarben, Lacke, Lasuren, Grundierungen, Holzschutz, Markier- und Sprühlacke für Werkstatt "
        "und Haus."),
      c("Holzpflege & Reparatur",
        "Hart- und Weichwachs, Wachskitt, Möbelöle, Beizen, Knetholz und Holzspachtel."),
      c("Maler- & Lackierwerkzeug",
        "Farbrollen, Flächen- und Lackpinsel, Abstreifgitter, Malerspachtel, Abdeckfolie und -band.\n"
        "Nicht hier: Künstlerpinsel → Kunst- & Malbedarf"),
      c("Kleber & Dichtstoffe",
        "Leime, Kleber, Montagekleber, Silikon und Acryl zum Dichten, Klebebänder für die Werkstatt."),
      c("Schmierstoffe & Reiniger",
        "Fette, Öle, Kriechöl, Trennmittel, Reiniger, Entferner und Lösemittel."),
      ),
    c("Elektro & Elektronik",
      "Strom, Licht und Elektronik.\nNicht hier: Veranstaltungstechnik → Veranstaltungstechnik; Rechner und "
      "Netzwerk → Büro & IT",
      c("Kabel & Verlängerungen",
        "Leitungen, Verlängerungskabel, Kabeltrommeln, Steckdosenleisten.\nNicht hier: XLR-, DMX- und "
        "Bühnenstromkabel → Veranstaltungstechnik; LAN-Kabel → Büro & IT/Netzwerk & Telefonie"),
      c("Installationsmaterial",
        "Schalter, Steckdosen, Dosen, Klemmen, Aderendhülsen, Flachsteckhülsen, Sicherungen, Kabelkanäle, "
        "Klingeltaster."),
      c("Leuchten & Leuchtmittel",
        "Arbeits- und Baustrahler, Lampen und Leuchten, Leuchtmittel.\nNicht hier: Bühnenscheinwerfer → "
        "Veranstaltungstechnik/Licht"),
      c("Elektronik-Bauteile & Mikrocontroller",
        "Widerstände, Kondensatoren, Halbleiter, Sensoren, LEDs, Steckverbinder, Platinen, Mikrocontroller."),
      c("Löten & Messen",
        "Lötstationen, Lötzinn und -zubehör, Multimeter, Oszilloskope, Spannungsprüfer.\n"
        "Nicht hier: Hartlöten → Maschinen & Elektrowerkzeuge/Schweißen & Hartlöten"),
      c("Batterien & Netzteile",
        "Batterien, Akkus (ohne Werkzeugakkus), Ladegeräte, Netzteile und Labornetzteile.\n"
        "Nicht hier: Werkzeugakkus → Maschinen & Elektrowerkzeuge/Elektrowerkzeuge"),
      ),
    c("Veranstaltungstechnik",
      "Technik für Veranstaltungen. Was zu keiner Unterkategorie passt, direkt hier.",
      c("Audio", "Mischpulte, Lautsprecher, Verstärker, Mikrofone, Stagebox, Audiokabel."),
      c("Licht", "Scheinwerfer, Moving Heads, Lichtsteuerung, DMX-Kabel, Nebelmaschinen."),
      c("Video & Projektion", "Beamer, Leinwände, Kameras, Videomischer, Präsentationsbildschirme.\n"
        "Nicht hier: Monitore für Arbeitsplätze → Büro & IT/Computer & Peripherie"),
      c("Bühne & Rigging", "Stative, Traversen, Podeste, Hängezubehör, Bühnenstrom."),
      ),
    c("Büro & IT",
      "Büro, Computer und Netzwerk.",
      c("Computer & Peripherie",
        "Rechner, Laptops, Monitore, Tastaturen, Mäuse, Drucker, Scanner und Barcodescanner.\n"
        "Nicht hier: Risograph → Druck/Risographie & Digitaldruck"),
      c("Netzwerk & Telefonie", "Router, Switches, Access Points, LAN-Kabel, Telefone und DECT."),
      c("Büromaterial",
        "Papier, Stifte, Heft- und Büroklammern, Etiketten, Ordner und Mappen.\nNicht hier: Druck- und "
        "Bastelpapier → Druck/Papier & Karton"),
      c("Verpackung & Versand",
        "Kartons, Beutel, Folien, Packband und Abroller, Polstermaterial, Bindfaden."),
      ),
    c("Möbel, Haus & Garten",
      "Einrichtung, Haustechnik und Außenbereich.\nNicht hier: Beschläge → Beschläge",
      c("Tische & Werkbänke", "Tische, Werkbänke, Arbeitsplatten und ihre Ersatzteile."),
      c("Stühle & Sitzmöbel", "Stühle, Hocker, Bänke, Sofas und ihre Ersatzteile."),
      c("Regale & Schränke", "Regale, Schränke, Rollcontainer und ihre Teile."),
      c("Aufbewahrung & Behälter", "Kisten, Boxen, Sortimentskästen, Lagersichtkästen, Werkzeugkoffer."),
      c("Küche & Haushalt", "Küchengeräte, Geschirr, Haushaltsgeräte, Reinigungsgeräte und -zubehör."),
      c("Sanitär & Heizung",
        "Siphons, Armaturen, Rohre und Rohrverbinder, Dichtungen für Wasseranschlüsse, Heizkörperzubehör, "
        "Revisionsklappen."),
      c("Lüftung",
        "Lüftungsgitter, -profile und -rohre, Wetterschutzgitter, Lüfter, Luftentfeuchter."),
      c("Garten & Außenbereich",
        "Gartengeräte und -werkzeug, Bewässerung, Fahrradständer und -haken, Fahnenstangenhalter, Briefkästen."),
      c("Schilder & Hausnummern", "Hausnummern, Tür- und Hinweisschilder, Namensschilder, Zahlenmarken."),
      ),
    c("Arbeitsschutz & Sicherheit",
      "Schutz von Menschen und Gebäude.",
      c("Persönliche Schutzausrüstung",
        "Handschuhe, Schutzbrillen, Gehör- und Atemschutz, Schutzkleidung, Sicherheitsschuhe."),
      c("Erste Hilfe", "Verbandkästen, Pflaster, Augenspülung."),
      c("Brandschutz & Sicherheitstechnik", "Feuerlöscher, Löschdecken, Rauchmelder, Absperrmaterial."),
      ),
    c("Druck",
      "Material und Geräte der Druckwerkstatt.\nNicht hier: Künstlerfarben → Kunst- & Malbedarf; "
      "Kopierpapier → Büro & IT/Büromaterial",
      c("Siebdruck", "Siebe und Rahmen, Rakel, Fotoemulsion, Belichtung, Sieb- und Textildruckfarben, "
        "Druckkarussell."),
      c("Hochdruck & Linolschnitt", "Linol- und Holzplatten, Schnitzwerkzeug, Walzen, Druckpressen, "
        "Hochdruckfarben."),
      c("Risographie & Digitaldruck", "Risograph, Master, Farbtrommeln und -patronen, Sublimations- und "
        "Großformatdruck."),
      c("Buchbinden", "Falzbeine, Ahlen, Buchbindeleim, Heft- und Bindematerial, Buchbinderkarton."),
      c("Papier & Karton", "Druck-, Bastel- und Fotopapiere, Papier in Sonderformaten, Karton und Pappe.\n"
        "Nicht hier: Malpapier → Kunst- & Malbedarf/Malgründe & Keilrahmen"),
      ),
    c("Textil & Nähen",
      "Material und Geräte der Textilwerkstatt.\nNicht hier: Siebdruck auf Textil → Druck/Siebdruck; "
      "Schneideplotter → Maschinen & Elektrowerkzeuge/Digitale Fertigung",
      c("Nähmaschinen & Geräte", "Näh-, Overlock-/Cover- und Stickmaschinen, Transferpressen, "
        "Bügelstationen."),
      c("Maschinenzubehör & Maschinennadeln", "Nähfüße, Spulen, Stickrahmen, Maschinennadeln, Pflegemittel."),
      c("Stoffe", "Meterware und Reste aller Stoffarten."),
      c("Vliese, Einlagen & Füllmaterial", "Bügel- und Stickvliese, Einlagen, Watte und Füllmaterial."),
      c("Garne", "Näh-, Overlock- und Stickgarne, Wolle."),
      c("Kurzwaren", "Knöpfe, Reißverschlüsse, Bänder, Borten, Kordeln, Gummiband, Nieten, Ösen und "
        "Druckknöpfe, Verschlüsse."),
      c("Nähwerkzeug & Schnittmuster", "Stoffscheren, Rollschneider, Schneidematten, Markier- und "
        "Messwerkzeug, Handnadeln, Schnittmuster, Schneiderbüsten."),
      c("Textilfarben & Transfer", "Stoffmalfarben, Färbemittel, Flex- und Flockfolien, Transferpapier."),
      ),
    c("Kunst- & Malbedarf",
      "Material der Farbenwerkstatt für künstlerisches Malen und Zeichnen.\n"
      "Nicht hier: Wand-, Holz- und Metalllacke → Oberfläche & Chemie/Lacke, Farben & Holzschutz",
      c("Künstlerfarben", "Acryl-, Öl-, Aquarell- und Gouachefarben, Tempera, Pastelle, Pigmente."),
      c("Malmittel & Grundierungen", "Gesso, Grundiermittel, Malmittel, Firnisse, Strukturpasten."),
      c("Pinsel, Spachtel & Malmesser", "Künstlerpinsel, Malspachtel und -messer, Paletten, Pinselpflege.\n"
        "Nicht hier: Malerpinsel und Farbrollen → Oberfläche & Chemie/Maler- & Lackierwerkzeug"),
      c("Malgründe & Keilrahmen", "Keilrahmen, Malplatten, Leinwand, Mal-, Aquarell- und Zeichenpapier, "
        "Skizzenbücher."),
      c("Zeichenmaterial", "Blei-, Farb- und Kohlestifte, Kreiden, Tusche, Fineliner, Marker, Radierer."),
      c("Staffeleien & Atelierbedarf", "Staffeleien, Malkittel, Fixative, Mappen für Arbeiten."),
      ),
]

# Further words the category choice finds a category by (synonyms, compound words, brands), by full name.
SL = "Schlösser & Schlüssel"
BE = "Beschläge"
TB = f"{BE}/Türbeschläge"
MB = f"{BE}/Möbelbeschläge"
BF = "Befestigungstechnik"
MS = f"{BF}/Metrische Schrauben"
MU = f"{BF}/Muttern"
SC = f"{BF}/Scheiben & Sicherungselemente"
DA = f"{BF}/Dübel & Anker"
TE = "Technischer Bedarf"
HW = "Handwerkzeuge"
MA = "Maschinen & Elektrowerkzeuge"
OC = "Oberfläche & Chemie"
SM = f"{OC}/Schleifmittel"
EL = "Elektro & Elektronik"
VT = "Veranstaltungstechnik"
BI = "Büro & IT"
MH = "Möbel, Haus & Garten"
AS = "Arbeitsschutz & Sicherheit"
DR = "Druck"
TX = "Textil & Nähen"
KU = "Kunst- & Malbedarf"

KEYWORDS = {
    SL: "Schloss, Schlüssel, Schließanlage",
    f"{SL}/Schließzylinder": "Profilzylinder, Halbzylinder, Knaufzylinder, Doppelzylinder, Servicezylinder, PZ, "
                             "Zylinderschloss, Schließzylinderbrücke, Zylinderverlängerung, BKS, ABUS",
    f"{SL}/Einsteck- & Kastenschlösser": "Einsteckschloss, Zimmertürschloss, Badschloss, Haustürschloss, "
                                         "Rohrrahmenschloss, Panikschloss, Fallenschloss, Einsteckfalle, "
                                         "Einsteckgetriebe, Kastenschloss, Stulp, Dornmaß",
    f"{SL}/Riegel-, Möbel- & Vorhängeschlösser": "Riegelschloss, Möbelschloss, Schrankschloss, Schubkastenschloss, "
                                                 "Briefkastenschloss, Hebelschloss, Drehstangenschloss, "
                                                 "Glastürschloss, Schiebetürschloss, Vorhängeschloss, Bügelschloss, "
                                                 "Hakenriegel",
    f"{SL}/Schließbleche & Schließkästen": "Schließblech, Winkelschließblech, Lappenschließblech, Schließkasten, "
                                          "Schließbolzen, Schließnocken",
    f"{SL}/Riegel, Überfallen & Türöffner": "Schlossriegel, Türriegel, Rohrkantriegel, Kantriegel, Schubriegel, "
                                           "Drehriegel, Überfalle, Überwurf, Türöffner, E-Öffner, Summer, "
                                           "Türsicherung, Kindersicherung",
    f"{SL}/Schlüsselrohlinge & Schlüsselkerne": "Schlüsselrohling, Rohling, Zylinderschlüssel, Schlüsselkern, "
                                                "Wechselkern, Nachschlüssel, Schlüsselkopie",
    f"{SL}/Bartschlüssel": "Buntbartschlüssel, Bartschlüsselrohling, Zimmerschlüssel, Hohlschlüssel",
    f"{SL}/Schlüsselzubehör": "Schlüsselring, Schlüsselanhänger, Schlüsselbund, Schlüsselkasten, Schlüsselbox, "
                              "Schlüsselsafe, Keysafe, Schlüsselstopp",
    BE: "Beschlag, Eisenwaren",
    TB: "Türspion, Türstopper, Türpuffer, Türkette, Türheber, Türaufsteller, Torfeststeller",
    f"{TB}/Drücker, Knäufe & Drückerstifte": "Türdrücker, Türgriff, Türklinke, Klinke, Drückergarnitur, "
                                            "Schutzgarnitur, Türknauf, Türknopf, Stoßgriff, Wechselstift, "
                                            "Vierkantstift, Drückerstift, Hoppe, FSB",
    f"{TB}/Rosetten & Schilder": "Rosette, Drückerrosette, Schlüsselrosette, Zylinderrosette, PZ-Rosette, "
                                 "Schlüsselschild, Langschild, Kurzschild, Schutzbeschlag",
    f"{TB}/Türbänder & Bandzubehör": "Türband, Scharnier Tür, Einbohrband, Aufschraubband, Aufsatzband, "
                                     "Pendeltürband, Fitschenband, Fitsche, Anuba, Bandaufnahme, Klemmblock, "
                                     "Rahmenteil, Flügelteil, Bandstift, Zierhülse, Kloben, Torband, Kistenband",
    f"{TB}/Türschließer & Feststeller": "Türschließer, Obentürschließer, Türschliesser, Gleitschiene, Gestänge, "
                                        "Montageplatte, Feststeller, Türfeststeller, Haftmagnet, Dorma, Geze",
    f"{TB}/Schiebetürbeschläge": "Schiebetür, Laufschiene, Laufwerk, Bodenführung, Schiebetürmuschel, "
                                 "Einlassmuschel, Muschelgriff, Glasschiebetür",
    f"{BE}/Fensterbeschläge": "Fenstergriff, Fensterolive, Olive, Fensterband, Fensterfischband, Dreh-Kipp, "
                              "Drehkipp, Fensterriegel, Fensterfeststeller, Ausstellschere, Fensterbankeisen, "
                              "Fenstersicherung, Rollladen, Gurtwickler, Ladenhalter, Einreiber",
    MB: "Möbelbeschlag, Schrankbeschlag",
    f"{MB}/Schubkastensysteme & Auszüge": "Schublade, Schubkasten, Auszug, Vollauszug, Schubladenführung, "
                                          "Zarge, Tandembox, Legrabox, Movento, Blum, Hettich, Tip-On, Blumotion",
    f"{MB}/Scharniere, Klappen & Schnäpper": "Scharnier, Topfscharnier, Topfband, Möbelscharnier, "
                                             "Klavierband, Stangenscharnier, Schrankband, Klappenhalter, "
                                             "Klappenstütze, Aventos, Magnetschnäpper, Kugelschnäpper, Vorreiber",
    f"{MB}/Möbelgriffe & Kistenbeschläge": "Möbelgriff, Schrankgriff, Möbelknopf, Griffleiste, Bügelgriff, "
                                           "Kistengriff, Koffergriff, Kistenverschluss, Spannverschluss, "
                                           "Kistenecke, Schatullenverschluss",
    f"{MB}/Verbinder & Bodenträger": "Möbelverbinder, Exzenter, Verbindungsbeschlag, Plattenverbinder, "
                                     "Bettbeschlag, Betthaken, Bodenträger, Regalbodenträger, Tablarträger, "
                                     "Schrankaufhänger, Rückwandverbinder, Lamello",
    f"{MB}/Gleiter & Möbelfüße": "Möbelgleiter, Filzgleiter, Stuhlgleiter, Teppichgleiter, Möbelfuß, "
                                 "Stellfuß, Höhenversteller, Nivellierfuß, Untersetzer, Puffer, Wandpuffer, "
                                 "Türpuffer",
    f"{MB}/Rohrkappen & Stopfen": "Rohrkappe, Rohrstopfen, Lamellenstopfen, Abdeckkappe, Endkappe, "
                                  "Vierkantrohr, Rundrohr, Einsteckbuchse, Schraubfußkappe",
    f"{BE}/Haken & Ösen": "Haken, Wandhaken, Garderobenhaken, Kleiderhaken, Deckenhaken, S-Haken, "
                          "Schraubhaken, Schraubösen, Öse, Bilderöse, Hakenleiste, Garderobenleiste, Schlaufe",
    f"{BE}/Halter & Aufhänger": "Halter, Wandhalter, Gerätehalter, Werkzeughalter, Handtuchhalter, "
                                "Fahrradhalter, Krawattenhalter, Kleiderbügelhalter, Rohrhalter, Aufhänger, "
                                "Bilderschiene, Bilderaufhänger",
    f"{BE}/Konsolen & Regalträger": "Konsole, Regalkonsole, Winkelkonsole, Regalträger, Wandschiene, "
                                    "Regalschiene, Regalsystem, Element-System, Handlaufstütze, Stütze",
    f"{BE}/Winkel, Bleche & Holzverbinder": "Winkel, Montagewinkel, Stuhlwinkel, Flachwinkel, Balkenwinkel, "
                                            "Verbindungsblech, Lochblech, Lochplatte, Stegblech, Lochband, "
                                            "Balkenschuh, Pfostenträger, Stützenfuß, Holzverbinder, Lasche",
    BF: "Befestigung, Normteile, Verbindungselemente, Kleineisen",
    f"{BF}/Holzschrauben": "Spax, Spanplattenschraube, Holzschraube, Universalschraube, Holzbauschraube, "
                           "Tellerkopfschraube, Terrassenschraube, Möbelschraube, Euroschraube, Schlüsselschraube, "
                           "Senkkopf, Torx, TX, Pozidriv",
    MS: "Maschinenschraube, metrisch, Gewinde, M3, M4, M5, M6, M8, M10, M12, 8.8, A2, Edelstahlschraube",
    f"{MS}/DIN 933 Sechskantschrauben, Vollgewinde": "Sechskantschraube, Sechskant, Außensechskant, "
                                                    "Vollgewinde, ISO 4017",
    f"{MS}/DIN 931 Sechskantschrauben mit Schaft": "Sechskantschraube, Teilgewinde, Schaftschraube, ISO 4014",
    f"{MS}/DIN 912 Zylinderschrauben, Innensechskant": "Zylinderkopfschraube, Inbusschraube, Inbus, Imbus, "
                                                      "Innensechskant, ISO 4762",
    f"{MS}/ISO 7380 Linsenkopfschrauben, Innensechskant": "Linsenkopf, Flachkopf, Inbus, Innensechskant",
    f"{MS}/DIN 7991 Senkschrauben, Innensechskant": "Senkkopfschraube, Senkschraube, Inbus, Innensechskant, "
                                                   "ISO 10642",
    f"{MS}/DIN 7985 Linsenschrauben, Kreuzschlitz": "Linsenkopfschraube, Linsenschraube, Kreuzschlitz, "
                                                   "Phillips, ISO 7045",
    f"{MS}/DIN 965 Senkschrauben, Kreuzschlitz": "Senkkopfschraube, Senkschraube, Kreuzschlitz, ISO 7046",
    f"{MS}/DIN 84 Zylinderschrauben, Schlitz": "Zylinderkopfschraube, Schlitzschraube, Schlitz, ISO 1207",
    f"{MS}/DIN 603 Flachrundschrauben": "Schlossschraube, Flachrundschraube, Vierkantansatz, Torbandschraube",
    f"{MS}/DIN 913–916 Gewindestifte": "Gewindestift, Madenschraube, Wurmschraube, Stiftschraube",
    f"{MS}/DIN 975, DIN 976 Gewindestangen": "Gewindestange, Gewindebolzen, Stockschraube, Stehbolzen",
    MU: "Mutter, Muttern, Ringmutter, Käfigmutter, Klemmmutter",
    f"{MU}/DIN 934 Sechskantmuttern": "Sechskantmutter, Mutter, ISO 4032",
    f"{MU}/DIN 985 Sicherungsmuttern": "Sicherungsmutter, Stoppmutter, Nylonmutter, selbstsichernd, ISO 10511",
    f"{MU}/DIN 1587 Hutmuttern": "Hutmutter, Abdeckmutter",
    f"{MU}/DIN 315 Flügelmuttern": "Flügelmutter, Rändelmutter",
    f"{MU}/Einschlagmuttern & Gewindeeinsätze": "Einschlagmutter, Einpressmutter, Einnietmutter, Nietmutter, "
                                               "Rampa, Rampamuffe, Einschraubmuffe, Gewindeeinsatz, Helicoil, "
                                               "Gewindehülse, Verbindungshülse",
    SC: "Scheibe, Unterlegscheibe, Sicherung",
    f"{SC}/DIN 125 Unterlegscheiben": "Unterlegscheibe, U-Scheibe, Beilagscheibe, Scheibe, ISO 7089",
    f"{SC}/DIN 9021 Scheiben, große Außendurchmesser": "Karosseriescheibe, große Scheibe, Kotflügelscheibe, "
                                                       "ISO 7093",
    f"{SC}/DIN 127, DIN 6798 Federringe & Zahnscheiben": "Federring, Federscheibe, Zahnscheibe, Fächerscheibe, "
                                                         "Sperrkantscheibe, Tellerfeder",
    f"{SC}/DIN 471, DIN 472, DIN 6799 Sicherungsringe & -scheiben": "Sicherungsring, Seegerring, Seeger, "
                                                                    "Wellensicherung, Sicherungsscheibe, "
                                                                    "Sprengring",
    f"{BF}/Blech- & Bohrschrauben": "Blechschraube, Bohrschraube, Fassadenschraube, Bohrspitze",
    DA: "Dübel, Anker",
    f"{DA}/Kunststoffdübel": "Dübel, Spreizdübel, Universaldübel, Rahmendübel, Nylondübel, Steinbuchse, Fischer, "
                             "Duopower, Flüssigdübel",
    f"{DA}/Hohlraum- & Plattendübel": "Hohlraumdübel, Gipskartondübel, Kippdübel, Federklappdübel, Molly, "
                                      "Plattendübel, Rigipsdübel, Spiraldübel",
    f"{DA}/Metall- & Schwerlastanker": "Schwerlastanker, Bolzenanker, Einschlaganker, Betonschraube, Metalldübel, "
                                       "Messingdübel, Steinkolben, Ankerbolzen",
    f"{DA}/Injektionssysteme": "Injektionsmörtel, Verbundmörtel, Ankerstange, Siebhülse, Reaktionsharz, "
                               "chemischer Anker",
    f"{BF}/Nägel & Drahtstifte": "Nagel, Nägel, Drahtstift, Stauchkopfnagel, Dachpappstift, Rinneisenstift, "
                                 "Ankernagel, Schraubnagel, Polsternagel, Ziernagel, Reißzwecke, Pinnnadel, "
                                 "Krampe, Zeltnagel",
    f"{BF}/Stifte, Nieten & Klammern": "Splint, Spannstift, Spannhülse, Kegelstift, Zylinderstift, Niete, "
                                       "Blindniete, Popniete, Tackerklammer, Heftklammer, Federstahlklammer, "
                                       "Klammer",
    TE: "Maschinenelement, Technischer Handel",
    f"{TE}/Ketten, Seile & Zubehör": "Kette, Rundstahlkette, Kugelkette, Kettenglied, Notglied, Seil, Drahtseil, "
                                     "Tau, Tauwerk, Schnur, Karabiner, Schäkel, Kausche, Seilklemme, "
                                     "Drahtseilklemme, Spannschloss, Wirbel, Seilrolle, Pressklemme",
    f"{TE}/Schellen & Kabelbinder": "Schelle, Rohrschelle, Schlauchschelle, Schlauchklemme, Gelenkschelle, "
                                    "Schneckengewindeschelle, Kabelbinder, Schlauchbinder, Nagelschelle",
    f"{TE}/Lager & Buchsen": "Lager, Kugellager, Rillenkugellager, Gleitlager, Walzenlager, Drehlager, "
                             "Lagerbuchse, Führungsbuchse, Bodenbuchse, Führungsring, Achse, Steckachse",
    f"{TE}/Rollen & Räder": "Rolle, Lenkrolle, Bockrolle, Möbelrolle, Transportrolle, Laufrolle, Stehrolle, "
                            "Rad, Räder, Gummirad, Torrolle",
    f"{TE}/Dichtungen & O-Ringe": "Dichtung, O-Ring, Dichtring, Flachdichtung, Gummidichtung, Fiberdichtung, "
                                  "Türdichtung, Dichtband, Dichtfaden, Hanf, Gummischeibe",
    f"{TE}/Schmiernippel, Stellringe & Federn": "Schmiernippel, Kegelschmiernippel, Stellring, Feder, "
                                                "Druckfeder, Zugfeder, Spannfeder, Haltefeder, Rahmenfeder, "
                                                "Passfeder, Rastbolzen",
    HW: "Werkzeug, Handwerkzeug, Entgrater, Magnetheber",
    f"{HW}/Schraubendreher & Bits": "Schraubendreher, Schraubenzieher, Bit, Bits, Bithalter, Bitadapter, "
                                    "Bitsatz, Torx, Pozidriv, PZ, PH, Kreuzschlitz, Schlitz, Wera, Wiha",
    f"{HW}/Schraubenschlüssel & Nüsse": "Schraubenschlüssel, Maulschlüssel, Gabelschlüssel, Ringschlüssel, "
                                        "Ringmaulschlüssel, Steckschlüssel, Nuss, Nüsse, Stecknuss, Ratsche, "
                                        "Knarre, Inbusschlüssel, Innensechskantschlüssel, Imbus, Inbus, "
                                        "Drehmomentschlüssel, Vierkantschlüssel",
    f"{HW}/Zangen": "Zange, Kombizange, Seitenschneider, Spitzzange, Wasserpumpenzange, Rohrzange, "
                    "Crimpzange, Abisolierzange, Kneifzange, Monierzange, Sicherungsringzange, Pinzette",
    f"{HW}/Hämmer & Schlagwerkzeuge": "Hammer, Schlosserhammer, Fäustel, Vorschlaghammer, Gummihammer, "
                                      "Klauenhammer, Hammerstiel, Stiel, Axt, Beil, Meißel, Körner, Durchtreiber, "
                                      "Splinttreiber, Schlagzahlen",
    f"{HW}/Sägen, Feilen & Schneidwerkzeuge": "Säge, Handsäge, Fuchsschwanz, Japansäge, Bügelsäge, Puksäge, "
                                              "Laubsäge, Sägeblatt, Feile, Raspel, Messer, Cutter, Teppichmesser, "
                                              "Klinge, Schere, Blechschere, Hobel, Stemmeisen, Stechbeitel, "
                                              "Locheisen, Kreisschneider",
    f"{HW}/Zwingen & Spannwerkzeuge": "Zwinge, Schraubzwinge, Leimzwinge, Einhandzwinge, Federzwinge, "
                                      "Spanner, Schraubstock, Spannband",
    f"{HW}/Messen & Anreißen": "Zollstock, Meterstab, Maßband, Bandmaß, Messschieber, Schieblehre, Winkel, "
                               "Anschlagwinkel, Schmiege, Wasserwaage, Lot, Senklot, Anreißnadel, Reißnadel, "
                               "Bohrlehre, Schablone, Laser, Entfernungsmesser",
    MA: "Maschine, Gerät",
    f"{MA}/Elektrowerkzeuge": "Bohrmaschine, Akkuschrauber, Schlagbohrer, Bohrhammer, Winkelschleifer, Flex, "
                              "Stichsäge, Kreissäge, Handkreissäge, Säbelsäge, Oberfräse, Schleifer, "
                              "Exzenterschleifer, Multitool, Heißluftfön, Akku, Ladegerät, Bosch, Makita, Metabo, "
                              "Festool",
    f"{MA}/Stationäre Maschinen": "Tischkreissäge, Kappsäge, Bandsäge, Standbohrmaschine, Säulenbohrmaschine, "
                                  "Drehbank, Drehmaschine, Fräsmaschine, Schleifbock, Dickenhobel, Abricht, "
                                  "Absauganlage",
    f"{MA}/Digitale Fertigung": "3D-Drucker, 3D-Druck, Filament, PLA, PETG, Lasercutter, Laser, CNC, Fräse, "
                                "Schneideplotter, Plotter, Vinyl",
    f"{MA}/Einsatzwerkzeuge": "Bohrer, Spiralbohrer, Holzbohrer, Steinbohrer, Betonbohrer, Forstnerbohrer, "
                              "Lochsäge, Bohrkrone, Senker, Kegelsenker, Sägeblatt, Kreissägeblatt, "
                              "Stichsägeblatt, Fräser, Bohrfutter, SDS, Filterbeutel, Staubsack",
    f"{MA}/Druckluft": "Kompressor, Druckluft, Pressluft, Luftschlauch, Kupplung, Schnellkupplung, Stecknippel, "
                       "Blaspistole, Druckminderer, Wartungseinheit, Tacker pneumatisch",
    f"{MA}/Schweißen & Hartlöten": "Schweißen, Schweißgerät, Elektrode, Stabelektrode, Schweißdraht, Stromdüse, "
                                   "Gasdüse, Brenner, MIG, MAG, WIG, Autogen, Acetylen, Hartlot, Hartlöten",
    OC: "Chemie, Oberfläche",
    SM: "Schleifen, Schleifmittel",
    f"{SM}/Schleifblätter & -streifen": "Schleifpapier, Sandpapier, Schmirgelpapier, Schleifbogen, Schleifblatt, "
                                        "Schleifstreifen, Schleifgitter, Schleifklotz, Schleifschwamm, "
                                        "Körnung, Korn",
    f"{SM}/Schleifscheiben & Fiberscheiben": "Schleifscheibe, Klettschleifscheibe, Fiberscheibe, Fächerscheibe, "
                                             "Lamellenscheibe, Trennscheibe, Schruppscheibe, Flexscheibe",
    f"{SM}/Schleifbänder, Vlies & Polieren": "Schleifband, Schleifrolle, Schleifvlies, Stahlwolle, Drahtbürste, "
                                             "Topfbürste, Polieren, Polierscheibe, Polierpaste, Schleifmop",
    f"{OC}/Lacke, Farben & Holzschutz": "Farbe, Wandfarbe, Lack, Klarlack, Sprühlack, Spraydose, Lasur, "
                                        "Grundierung, Haftgrund, Holzschutz, Rostschutz, Markierspray, "
                                        "Spachtelmasse, Füllspachtel",
    f"{OC}/Holzpflege & Reparatur": "Wachs, Hartwachs, Weichwachs, Wachskitt, Möbelöl, Holzöl, Leinöl, Beize, "
                                    "Knetholz, Holzkitt, Reparatur, Retusche",
    f"{OC}/Maler- & Lackierwerkzeug": "Farbrolle, Farbroller, Lackierwalze, Pinsel, Flächenpinsel, Malerpinsel, "
                                      "Abstreifgitter, Farbwanne, Spachtel, Malerspachtel, Abdeckfolie, "
                                      "Abdeckplane, Kreppband, Malerkrepp, Tapeziermaterial",
    f"{OC}/Kleber & Dichtstoffe": "Kleber, Klebstoff, Leim, Holzleim, Sekundenkleber, Montagekleber, Epoxid, "
                                  "Zweikomponentenkleber, Heißkleber, Silikon, Acryl, Fugendichtmasse, Bauschaum, "
                                  "Klebeband, Gewebeband, Doppelklebeband",
    f"{OC}/Schmierstoffe & Reiniger": "Fett, Schmierfett, Öl, Kriechöl, WD-40, Schmiermittel, Sprühöl, "
                                      "Trennmittel, Reiniger, Entferner, Lösemittel, Verdünnung, Aceton, Spiritus, "
                                      "Bremsenreiniger, Politur",
    EL: "Elektro, Elektrik, Elektronik",
    f"{EL}/Kabel & Verlängerungen": "Kabel, Leitung, Verlängerungskabel, Verlängerung, Kabeltrommel, Kabelrolle, "
                                    "Steckdosenleiste, Mehrfachsteckdose, Netzkabel, Kaltgerätekabel",
    f"{EL}/Installationsmaterial": "Schalter, Steckdose, Stecker, Schuko, Abzweigdose, Unterputzdose, Klemme, "
                                   "Wago, Lüsterklemme, Aderendhülse, Flachsteckhülse, Kabelschuh, Sicherung, "
                                   "Kabelkanal, Isolierband, Klingel, Taster, Gong",
    f"{EL}/Leuchten & Leuchtmittel": "Lampe, Leuchte, Baustrahler, Arbeitsleuchte, Taschenlampe, Stirnlampe, "
                                     "LED, Glühbirne, Leuchtmittel, Leuchtstoffröhre, Röhre",
    f"{EL}/Elektronik-Bauteile & Mikrocontroller": "Widerstand, Kondensator, Diode, Transistor, LED, Sensor, "
                                                   "Platine, Steckbrett, Breadboard, Arduino, Raspberry Pi, ESP32, "
                                                   "Mikrocontroller, Jumper",
    f"{EL}/Löten & Messen": "Lötkolben, Lötstation, Lötzinn, Entlötlitze, Multimeter, Messgerät, "
                            "Spannungsprüfer, Duspol, Oszilloskop",
    f"{EL}/Batterien & Netzteile": "Batterie, Akku, Knopfzelle, AA, AAA, Ladegerät, Netzteil, Labornetzteil, "
                                   "Powerbank",
    VT: "Veranstaltung, Event, Bühne",
    f"{VT}/Audio": "Lautsprecher, Box, Mischpult, Mikrofon, Funkmikrofon, Verstärker, Endstufe, Stagebox, XLR, "
                   "Klinke, Audiokabel, PA",
    f"{VT}/Licht": "Scheinwerfer, Spot, PAR, Moving Head, Lichtpult, DMX, Nebelmaschine, Hazer, Farbfilter",
    f"{VT}/Video & Projektion": "Beamer, Projektor, Leinwand, Kamera, Videomischer, Bildschirm, Fernseher, TV, "
                                "HDMI",
    f"{VT}/Bühne & Rigging": "Stativ, Boxenstativ, Lichtstativ, Traverse, Truss, Podest, Bühnenelement, "
                             "Sicherungsseil, Schäkel, Bühnenstrom, CEE",
    BI: "Büro, IT, Computer",
    f"{BI}/Computer & Peripherie": "Computer, PC, Rechner, Laptop, Notebook, Monitor, Bildschirm, Tastatur, Maus, "
                                   "Drucker, Scanner, Barcodescanner, Webcam, VGA, USB",
    f"{BI}/Netzwerk & Telefonie": "Router, Switch, Access Point, WLAN, LAN, Netzwerkkabel, Patchkabel, Telefon, "
                                  "DECT, Modem",
    f"{BI}/Büromaterial": "Papier, Stift, Kugelschreiber, Textmarker, Heftklammer, Büroklammer, Briefklammer, "
                          "Hefter, Locher, Etikett, Etikettendrucker, Beschriftungsgerät, Ordner, Mappe",
    f"{BI}/Verpackung & Versand": "Karton, Umzugskarton, Beutel, Tüte, Zip-Beutel, Folie, Stretchfolie, Packband, "
                                  "Klebebandabroller, Luftpolster, Polstermaterial, Bindfaden, Schnur",
    MH: "Haus, Einrichtung, Haustechnik",
    f"{MH}/Tische & Werkbänke": "Tisch, Werkbank, Werktisch, Arbeitsplatte, Tischplatte, Tischbein, "
                                "Klapptisch, Biertisch",
    f"{MH}/Stühle & Sitzmöbel": "Stuhl, Bürostuhl, Hocker, Bank, Sofa, Sessel, Bierbank",
    f"{MH}/Regale & Schränke": "Regal, Schrank, Schwerlastregal, Spind, Rollcontainer, Schubladenschrank, "
                               "Hamburger Schrankschraube",
    f"{MH}/Aufbewahrung & Behälter": "Kiste, Box, Eurokiste, Sortierkasten, Sortimentskasten, Lagersichtkasten, "
                                     "Werkzeugkoffer, Werkzeugkiste, Behälter, Eimer, Dose",
    f"{MH}/Küche & Haushalt": "Küche, Geschirr, Besteck, Tasse, Wasserkocher, Kaffeemaschine, Kühlschrank, "
                              "Staubsauger, Besen, Putzzeug, Saugnapf, Sauger",
    f"{MH}/Sanitär & Heizung": "Sanitär, Siphon, Abfluss, Ablauf, Armatur, Wasserhahn, Rohr, Rohrverbinder, "
                               "Fitting, Muffe, Reduzierstück, Quetschverschraubung, Kupferrohr, Heizung, "
                               "Heizkörper, Thermostat, Ventil, Revisionsklappe",
    f"{MH}/Lüftung": "Lüftung, Lüftungsgitter, Wetterschutzgitter, Lüftungsrohr, Lüftungsschlauch, Lüfter, "
                     "Ventilator, Luftentfeuchter, Bautrockner",
    f"{MH}/Garten & Außenbereich": "Garten, Gartengerät, Gartenschlauch, Bewässerung, Gardena, Spaten, Rechen, "
                                   "Harke, Heckenschere, Rasentrimmer, Fahrrad, Fahrradständer, Fahnenstange, "
                                   "Briefkasten, Mausefalle, Zaun",
    f"{MH}/Schilder & Hausnummern": "Schild, Türschild, Namensschild, Hinweisschild, Piktogramm, Hausnummer, "
                                    "Zahlen, Buchstaben, Schildhalter",
    AS: "Sicherheit, Schutz, Arbeitssicherheit",
    f"{AS}/Persönliche Schutzausrüstung": "PSA, Handschuhe, Arbeitshandschuhe, Schutzbrille, Gehörschutz, "
                                          "Ohrstöpsel, Atemschutz, Staubmaske, FFP2, Schutzhelm, Arbeitskleidung, "
                                          "Arbeitshose, Arbeitsjacke, Sicherheitsschuhe, Gummistiefel, Knieschoner, "
                                          "Schürze, Warnweste",
    f"{AS}/Erste Hilfe": "Verbandkasten, Erste-Hilfe-Kasten, Pflaster, Verband, Augenspülung, Kühlpack",
    f"{AS}/Brandschutz & Sicherheitstechnik": "Feuerlöscher, Löschdecke, Rauchmelder, Brandmelder, Absperrband, "
                                              "Warnband, Flatterband, Absperrung, Fluchtweg",
    DR: "Druckwerkstatt, drucken",
    f"{DR}/Siebdruck": "Siebdruck, Sieb, Siebdruckrahmen, Rakel, Fotoemulsion, Emulsion, Belichtung, "
                       "Belichtungsgerät, Siebdruckfarbe, Textildruckfarbe, Druckkarussell, Entschichter",
    f"{DR}/Hochdruck & Linolschnitt": "Linoldruck, Linolschnitt, Linol, Holzschnitt, Hochdruck, Schnitzwerkzeug, "
                                      "Linolmesser, Walze, Farbwalze, Druckpresse, Tiefdruck, Radierung",
    f"{DR}/Risographie & Digitaldruck": "Risograph, Riso, Master, Farbtrommel, Sublimation, Sublimationsdruck, "
                                        "Großformatdruck, Plotterdruck, Tinte",
    f"{DR}/Buchbinden": "Buchbinden, Falzbein, Ahle, Buchbindeleim, Fadenheftung, Heftgarn, Buchbinderkarton, "
                        "Bindung, Ringbindung",
    f"{DR}/Papier & Karton": "Papier, Druckpapier, Fotopapier, Bastelpapier, Tonpapier, Karton, Pappe, "
                             "Graupappe, Sonderformat, A3, A2",
    TX: "Textil, Nähen, Textilwerkstatt",
    f"{TX}/Nähmaschinen & Geräte": "Nähmaschine, Overlock, Coverlock, Stickmaschine, Transferpresse, "
                                   "Bügelpresse, Bügeleisen, Bügelstation, Bernina, Brother, Pfaff",
    f"{TX}/Maschinenzubehör & Maschinennadeln": "Nähfuß, Spule, Unterfaden, Stickrahmen, Maschinennadel, "
                                                "Nähmaschinennadel, Nähmaschinenöl",
    f"{TX}/Stoffe": "Stoff, Meterware, Baumwolle, Jersey, Fleece, Filz, Leinen, Canvas, Stoffrest",
    f"{TX}/Vliese, Einlagen & Füllmaterial": "Vlies, Bügelvlies, Stickvlies, Einlage, Volumenvlies, Watte, "
                                             "Füllwatte, Füllmaterial",
    f"{TX}/Garne": "Garn, Nähgarn, Overlockgarn, Stickgarn, Wolle, Faden",
    f"{TX}/Kurzwaren": "Knopf, Knöpfe, Reißverschluss, Druckknopf, Kam Snaps, Band, Gummiband, Schrägband, "
                       "Borte, Kordel, Klettband, Ösen, Nieten, Schnürsenkel",
    f"{TX}/Nähwerkzeug & Schnittmuster": "Stoffschere, Schneiderschere, Rollschneider, Schneidematte, "
                                         "Schneiderkreide, Markierstift, Maßband, Stecknadel, Nähnadel, "
                                         "Fingerhut, Nahttrenner, Schnittmuster, Schneiderpuppe, Schneiderbüste",
    f"{TX}/Textilfarben & Transfer": "Stofffarbe, Textilfarbe, Färben, Batik, Flexfolie, Flockfolie, Plotterfolie, "
                                     "Bügelbild, Transferpapier, Textilmarker",
    KU: "Kunst, Malen, Zeichnen, Farbenwerkstatt",
    f"{KU}/Künstlerfarben": "Acrylfarbe, Ölfarbe, Aquarellfarbe, Gouache, Tempera, Pastell, Pigment, "
                            "Künstlerfarbe",
    f"{KU}/Malmittel & Grundierungen": "Gesso, Grundierung, Malmittel, Firnis, Strukturpaste, Medium, Bindemittel",
    f"{KU}/Pinsel, Spachtel & Malmesser": "Künstlerpinsel, Pinsel, Rundpinsel, Flachpinsel, Malspachtel, "
                                          "Malmesser, Palette, Palettmesser",
    f"{KU}/Malgründe & Keilrahmen": "Keilrahmen, Leinwand, Malplatte, Malpappe, Malpapier, Aquarellpapier, "
                                    "Zeichenpapier, Skizzenbuch, Zeichenblock",
    f"{KU}/Zeichenmaterial": "Bleistift, Buntstift, Farbstift, Kohle, Zeichenkohle, Kreide, Pastellkreide, Tusche, "
                             "Fineliner, Marker, Radiergummi",
    f"{KU}/Staffeleien & Atelierbedarf": "Staffelei, Tischstaffelei, Malkittel, Fixativ, Zeichenmappe, "
                                         "Mappe",
}

# Earlier categories (full name) and the path they become.
LEGACY = {
    "Handwerkzeuge": ("Handwerkzeuge",),
    "Schleifmittel": ("Oberfläche & Chemie", "Schleifmittel"),
    "Elektrische Werkzeuge": ("Maschinen & Elektrowerkzeuge", "Elektrowerkzeuge"),
    "Normteile": ("Befestigungstechnik",),
    "Normteile/Holzschrauben": ("Befestigungstechnik", "Holzschrauben"),
    "Normteile/Maschinenschrauben": ("Befestigungstechnik", "Metrische Schrauben"),
}


def forward(apps, schema_editor):
    Category = apps.get_model("inventory", "Category")
    legacy = {path: Category.objects.filter(full_name=old).first() for old, path in LEGACY.items()}

    def place(nodes, parent, path):
        for name, description, children in nodes:
            here = (*path, name)
            category = legacy.get(here) or Category.objects.filter(parent_category=parent, name=name).first()
            if category is None:
                category = Category(name=name)
            old = category.description.replace("\r\n", "\n").strip()
            if old and old != description and description not in old:
                description = f"{description}\n\n{old}"  # e.g. the naming rules of the abrasives
            category.name, category.description, category.parent_category = name, description, parent
            category.keywords = KEYWORDS.get("/".join(here), category.keywords)
            category.full_name = f"{parent.full_name}/{name}" if parent else name
            category.save()
            place(children, category, here)

    place(TREE, None, ())
    # Categories outside the tree below a moved one (and any other) get their full name from their parents.
    categories = {category.pk: category for category in Category.objects.all()}

    def full_name(category, seen=()):
        parent = categories.get(category.parent_category_id)
        if parent is None or parent.pk in seen:
            return category.name
        return f"{full_name(parent, (*seen, category.pk))}/{category.name}"

    for category in categories.values():
        if category.full_name != (name := full_name(category)):
            Category.objects.filter(pk=category.pk).update(full_name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0047_reserved_containers"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="keywords",
            field=models.TextField(
                blank=True,
                help_text="Further words the category choice finds it by, separated by commas: synonyms, "
                          "compound words, brands.",
                verbose_name="keywords",
            ),
        ),
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]

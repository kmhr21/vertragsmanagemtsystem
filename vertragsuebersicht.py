"""
Vertragsübersicht – Oberfläche für Endbenutzer

Zeigt alle Verträge in einer Liste, die man durchsuchen, filtern und
nach Wunsch anordnen kann.

Bedienung:
    Suchen              oben ins Suchfeld tippen (mehrere Wörter: alle müssen vorkommen)
    Status              Schnellfilter oben (Alle, Aktiv, Entwurf, Gekündigt, Abgelaufen)
    Weitere Filter      Button „Filter“ oder Rechtsklick → „Filter anpassen …“
    Sortieren           Klick auf einen Spaltenkopf, nochmal klicken = umgekehrt
    Spalten verschieben Spaltenkopf mit gedrückter Maustaste nach links/rechts ziehen
    Spalten ein/aus     Rechtsklick auf einen Spaltenkopf
    Nach Wert filtern   Rechtsklick auf eine Zelle, z. B. auf einen Vertragspartner
    Aktualisieren       F5 oder Rechtsklick → „Aktualisieren“

Reihenfolge, Breite und Sichtbarkeit der Spalten, die Sortierung und das
Design werden in einstellungen_uebersicht.json gespeichert.

Benötigt: pip install customtkinter
Die Dateien vertragsverwaltung_gui.py und vertrag_erfassen.py müssen im
selben Ordner liegen (Datenbank-Einstellungen stehen in vertragsverwaltung_gui.py).
"""

import json
import subprocess
import sys
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk

from vertragsverwaltung_gui import (
    DB_CONFIG, DB_TYPE, ABTEILUNGEN_AKTIV, dbapi,
    Datenbankverbindung, VertragRepository, lese_datum, formatiere_betrag,
)
from vertrag_erfassen import (
    HINTERGRUND, KARTE, KARTE_RAND, TEXT, TEXT_LEISE, EINGABE_RAND, EINGABE_HG, PLATZHALTER,
    AKZENT, AKZENT_HOVER, FEHLER, WARNUNG, SEGMENT_HG, SEGMENT_HOVER,
    STATUS_ANZEIGE, INTERVALL_ANZEIGE,
    berechne_kuendigungsstichtag, berechne_jahreskosten,
)


ORDNER = Path(__file__).resolve().parent
EINSTELLUNGEN_DATEI = ORDNER / "einstellungen_uebersicht.json"
ERFASSEN_DATEI = ORDNER / "vertrag_erfassen.py"

WARN_TAGE = 90                     # Kündigungsstichtag in <= 90 Tagen -> orange

AUSWAHL_HG = ("#dbe7fd", "#26354f")
KOPF_HG = ("#f6f7f9", "#262a31")
STREIFEN_HG = ("#fafbfc", "#22252c")

ALLE = "Alle"
STATUS_TEXT = {db: anzeige for anzeige, db in STATUS_ANZEIGE.items()}       # "aktiv" -> "Aktiv"
INTERVALL_TEXT = {db: anzeige for anzeige, db in INTERVALL_ANZEIGE.items()}

FRIST_OPTIONEN = {                 # Anzeige -> (Art, Tage)
    ALLE: None,
    "Bereits verpasst": ("verpasst", 0),
    "In den nächsten 30 Tagen": ("bis", 30),
    "In den nächsten 60 Tagen": ("bis", 60),
    "In den nächsten 90 Tagen": ("bis", 90),
    "In den nächsten 180 Tagen": ("bis", 180),
    "Im nächsten Jahr": ("bis", 365),
}

# Diese Felder werden bei der Suche durchsucht
SUCH_FELDER = ("vertragsnummer", "titel", "beschreibung", "partner", "art",
               "laufzeit", "verantwortlich", "abteilung", "status")


# =====================================================
# SPALTEN DER LISTE
# =====================================================

class Spalte:
    def __init__(self, key, titel, breite, ausrichtung="w", sichtbar=True, filter=None):
        self.key = key                  # Schlüssel in der Zeile (siehe baue_zeile)
        self.titel = titel
        self.breite = breite
        self.ausrichtung = ausrichtung  # w = links, e = rechts, center
        self.sichtbar = sichtbar        # Standard: sichtbar oder ausgeblendet
        self.filter = filter            # Rechtsklick „Nur … anzeigen“ setzt diesen Filter


SPALTEN = [
    Spalte("vertragsnummer", "Nummer", 105),
    Spalte("titel", "Titel", 200),
    Spalte("partner", "Vertragspartner", 160, filter="partner"),
    Spalte("art", "Vertragsart", 120, filter="art"),
    Spalte("status", "Status", 95, filter="status"),
    Spalte("beginn", "Beginn", 95, "center", sichtbar=False),
    Spalte("ende", "Ende", 95, "center"),
    Spalte("stichtag", "Kündigen bis", 110, "center"),
    Spalte("tage", "Noch Tage", 100, "e"),
    Spalte("kosten", "Kosten", 100, "e"),
    Spalte("intervall", "Intervall", 100, filter="intervall"),
    Spalte("jahreskosten", "Kosten pro Jahr", 125, "e", sichtbar=False),
    Spalte("verantwortlich", "Verantwortlich", 140, filter="verantwortlich"),
    Spalte("laufzeit", "Laufzeit", 100, sichtbar=False, filter="laufzeit"),
    Spalte("auto", "Auto-Verlängerung", 135, "center", sichtbar=False),
]
if ABTEILUNGEN_AKTIV:
    SPALTEN.insert(13, Spalte("abteilung", "Abteilung", 120, filter="abteilung"))

SPALTE = {s.key: s for s in SPALTEN}
STANDARD_SORTIERUNG = ("tage", False)          # dringendste Kündigungen zuerst


def anzeige(key: str, wert) -> str:
    """Wert einer Zelle als Text."""
    if wert is None or wert == "":
        return ""
    if key in ("beginn", "ende", "stichtag"):
        return wert.strftime("%d.%m.%Y")
    if key in ("kosten", "jahreskosten"):
        return f"{formatiere_betrag(wert)} €"
    if key == "auto":
        return "ja" if wert else "nein"
    return str(wert)


def kurz(text: str, laenge=32) -> str:
    return text if len(text) <= laenge else text[:laenge - 1] + "…"


# =====================================================
# DATENZUGRIFF
# =====================================================

class VertragUebersichtRepository(VertragRepository):
    """Lädt alle Verträge mit den Namen aus den verknüpften Tabellen (JOIN)."""

    def finde_uebersicht(self) -> list:
        spalten = ["id_vertrag", "vertragsnummer", "titel", "beschreibung", "status",
                   "beginn_datum", "end_datum", "kuendigungsfrist_tage", "auto_verlaengerung",
                   "kosten", "zahlungsintervall",
                   "firmenname", "vertragsart", "laufzeit", "vorname", "nachname"]
        sql = ("SELECT v.id_vertrag, v.vertragsnummer, v.titel, v.beschreibung, v.status, "
               "v.beginn_datum, v.end_datum, v.kuendigungsfrist_tage, v.auto_verlaengerung, "
               "v.kosten, v.zahlungsintervall, "
               "p.firmenname, a.bezeichnung, l.bezeichnung, b.vorname, b.nachname")
        joins = (" FROM vertrag v"
                 " JOIN vertragspartner p ON p.id_vertragspartner = v.id_vertragspartner"
                 " JOIN vertragsart a ON a.id_vertragsart = v.id_vertragsart"
                 " JOIN laufzeit l ON l.id_laufzeit = v.id_laufzeit"
                 " JOIN benutzer b ON b.id_benutzer = v.id_benutzer")
        if ABTEILUNGEN_AKTIV:
            spalten.append("abteilung")
            sql += ", ab.bezeichnung"
            joins += " JOIN abteilung ab ON ab.id_abteilung = v.id_abteilung"
        zeilen = self._db.abfragen(sql + joins + " ORDER BY v.id_vertrag")
        return [dict(zip(spalten, zeile)) for zeile in zeilen]


def baue_zeile(d: dict, heute: date) -> dict:
    """Aus einem Datenbank-Datensatz die Werte für die Liste berechnen."""
    stichtag = None
    if d["end_datum"] is not None:
        stichtag = berechne_kuendigungsstichtag(d["end_datum"], d["kuendigungsfrist_tage"])
    # Tage bis zum Stichtag nur bei Verträgen, bei denen noch gehandelt werden kann
    offen = d["status"] in ("aktiv", "entwurf")
    tage = (stichtag - heute).days if stichtag is not None and offen else None
    kosten = d["kosten"]
    return {
        "id": d["id_vertrag"],
        "vertragsnummer": d["vertragsnummer"],
        "titel": d["titel"],
        "beschreibung": d["beschreibung"] or "",
        "partner": d["firmenname"],
        "art": d["vertragsart"],
        "laufzeit": d["laufzeit"],
        "verantwortlich": f"{d['vorname']} {d['nachname']}",
        "abteilung": d.get("abteilung"),
        "status": STATUS_TEXT.get(d["status"], d["status"]),
        "beginn": d["beginn_datum"],
        "ende": d["end_datum"],
        "stichtag": stichtag,
        "tage": tage,
        "kosten": kosten,
        "intervall": INTERVALL_TEXT.get(d["zahlungsintervall"]),
        "jahreskosten": None if kosten is None else berechne_jahreskosten(kosten, d["zahlungsintervall"]),
        "auto": bool(d["auto_verlaengerung"]),
    }


def leere_filter() -> dict:
    return {"suche": "", "status": None, "art": None, "partner": None, "verantwortlich": None,
            "laufzeit": None, "intervall": None, "abteilung": None, "frist": None,
            "ende_von": None, "ende_bis": None}


def passt(z: dict, f: dict) -> bool:
    """True, wenn die Zeile alle Filter erfüllt."""
    for key in ("status", "art", "partner", "verantwortlich", "laufzeit", "intervall", "abteilung"):
        if f[key] is not None and z[key] != f[key]:
            return False
    if f["frist"] is not None:
        art, tage = f["frist"]
        if z["tage"] is None:
            return False
        if art == "verpasst" and z["tage"] >= 0:
            return False
        if art == "bis" and not 0 <= z["tage"] <= tage:
            return False
    if f["ende_von"] is not None and (z["ende"] is None or z["ende"] < f["ende_von"]):
        return False
    if f["ende_bis"] is not None and (z["ende"] is None or z["ende"] > f["ende_bis"]):
        return False
    if f["suche"]:
        text = " ".join(str(z[k] or "") for k in SUCH_FELDER).casefold()
        if not all(wort in text for wort in f["suche"].casefold().split()):
            return False
    return True


def sortiere_zeilen(zeilen: list, key: str, absteigend: bool) -> list:
    """Sortiert nach einer Spalte. Leere Werte stehen immer am Ende."""
    mit_wert = [z for z in zeilen if z[key] is not None and z[key] != ""]
    ohne_wert = [z for z in zeilen if z[key] is None or z[key] == ""]

    def schluessel(z):
        wert = z[key]
        return wert.casefold() if isinstance(wert, str) else wert

    return sorted(mit_wert, key=schluessel, reverse=absteigend) + ohne_wert


# =====================================================
# HAUPTFENSTER
# =====================================================

class Vertragsuebersicht(ctk.CTk):
    def __init__(self, db: Datenbankverbindung):
        super().__init__()
        self.db = db
        self.repo = VertragUebersichtRepository(db)
        self.alle_zeilen = []
        self.zeilen = []                 # gefiltert und sortiert
        self.zeile_nach_id = {}
        self.filter = leere_filter()
        self._ziehen = None              # Zustand beim Verschieben einer Spalte
        self._erfassen_prozess = None
        self._menue_variablen = []

        self._lade_einstellungen()
        ctk.set_appearance_mode(self.design)

        self.title("Vertragsübersicht")
        breite = min(1400, self.winfo_screenwidth() - 40)        # passt auch auf kleine Bildschirme
        hoehe = min(860, self.winfo_screenheight() - 80)
        self.geometry(f"{breite}x{hoehe}")
        self.minsize(900, 560)
        self.configure(fg_color=HINTERGRUND)
        self.protocol("WM_DELETE_WINDOW", self.beenden)

        self.schrift_titel = ctk.CTkFont(size=24, weight="bold")
        self.schrift_fett = ctk.CTkFont(size=13, weight="bold")
        self.schrift_normal = ctk.CTkFont(size=13)
        self.schrift_klein = ctk.CTkFont(size=12)
        self.schrift_tabelle = ctk.CTkFont(size=13)
        self.schrift_kopf = ctk.CTkFont(size=12, weight="bold")

        self._baue_kopfzeile()
        self._baue_fusszeile()
        self._baue_werkzeugleiste()
        self._baue_filterleiste()
        self._baue_tabelle()
        self._style_tabelle()

        self.bind("<F5>", lambda _e: self.aktualisieren())
        self.bind("<Control-f>", lambda _e: self.suchfeld.focus_set())
        self.aktualisieren()

    # ---------- Aufbau ----------

    def _baue_kopfzeile(self):
        kopf = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=0)
        kopf.pack(fill="x")
        texte = ctk.CTkFrame(kopf, fg_color="transparent")
        texte.pack(side="left", padx=32, pady=18)
        ctk.CTkLabel(texte, text="Vertragsübersicht", font=self.schrift_titel,
                     text_color=TEXT, anchor="w").pack(fill="x")
        self.anzahl_text = ctk.CTkLabel(texte, text="", font=self.schrift_normal,
                                        text_color=TEXT_LEISE, anchor="w")
        self.anzahl_text.pack(fill="x")

        ctk.CTkButton(kopf, text="+  Neuer Vertrag", command=self.neuer_vertrag, height=40,
                      width=160, corner_radius=10, font=self.schrift_fett, fg_color=AKZENT,
                      hover_color=AKZENT_HOVER).pack(side="right", padx=(12, 32))
        self.dunkel = ctk.CTkSwitch(kopf, text="Dunkles Design", font=self.schrift_normal,
                                    text_color=TEXT_LEISE, progress_color=AKZENT,
                                    command=self._design_wechseln)
        if self.design == "dark":
            self.dunkel.select()
        self.dunkel.pack(side="right", padx=12)

    def _baue_werkzeugleiste(self):
        leiste = ctk.CTkFrame(self, fg_color="transparent")
        leiste.pack(fill="x", padx=24, pady=(18, 12))

        self.suchfeld = ctk.CTkEntry(leiste, width=340, height=36, corner_radius=10,
                                     border_width=1, border_color=EINGABE_RAND, fg_color=KARTE,
                                     text_color=TEXT, placeholder_text_color=PLATZHALTER,
                                     placeholder_text="Suchen: Nummer, Titel, Partner …",
                                     font=self.schrift_normal)
        self.suchfeld.pack(side="left")
        self.suchfeld.bind("<KeyRelease>", self._suche_geaendert)
        self.suchfeld.bind("<Escape>", lambda _e: self.suche_nach(""))

        self.status_filter = ctk.CTkSegmentedButton(
            leiste, values=[ALLE, "Aktiv", "Entwurf", "Gekündigt", "Abgelaufen"], width=470,
            height=36, dynamic_resizing=False, font=self.schrift_normal, fg_color=SEGMENT_HG,
            unselected_color=SEGMENT_HG, unselected_hover_color=SEGMENT_HOVER,
            selected_color=KARTE, selected_hover_color=KARTE, text_color=TEXT,
            command=lambda _w: self._status_geaendert())
        self.status_filter.set(ALLE)
        self.status_filter.pack(side="left", padx=16)

        ctk.CTkButton(leiste, text="Aktualisieren", command=self.aktualisieren, height=36,
                      width=120, corner_radius=10, font=self.schrift_normal,
                      fg_color="transparent", border_width=1, border_color=EINGABE_RAND,
                      text_color=TEXT, hover_color=SEGMENT_HOVER).pack(side="right")
        self.filter_knopf = ctk.CTkButton(leiste, text="Filter", command=self.filter_umschalten,
                                          height=36, width=110, corner_radius=10,
                                          font=self.schrift_normal, border_width=1)
        self.filter_knopf.pack(side="right", padx=10)
        self._zeige_filter_knopf()

    def _baue_filterleiste(self):
        self.filterleiste = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=14,
                                         border_width=1, border_color=KARTE_RAND)
        raster = ctk.CTkFrame(self.filterleiste, fg_color="transparent")
        raster.pack(fill="x", padx=20, pady=(14, 6))
        raster.columnconfigure((0, 1, 2, 3), weight=1, uniform="filter")

        self.filter_auswahl = {}          # Filter-Schlüssel -> Combobox
        felder = [("art", "Vertragsart"), ("partner", "Vertragspartner"),
                  ("verantwortlich", "Verantwortlich"), ("laufzeit", "Laufzeit"),
                  ("intervall", "Zahlungsintervall")]
        if ABTEILUNGEN_AKTIV:
            felder.append(("abteilung", "Abteilung"))
        for nr, (key, titel) in enumerate(felder):
            self.filter_auswahl[key] = self._filter_combo(raster, nr, titel, [ALLE])
        nr = len(felder)
        self.f_frist = self._filter_combo(raster, nr, "Kündigung fällig", list(FRIST_OPTIONEN))

        zelle = self._filter_zelle(raster, nr + 1, "Ende zwischen")
        datum = ctk.CTkFrame(zelle, fg_color="transparent")
        datum.pack(fill="x", pady=(4, 0))
        self.f_ende_von = self._datum_feld(datum, "von TT.MM.JJJJ")
        ctk.CTkLabel(datum, text="–", text_color=TEXT_LEISE, width=16).pack(side="left", padx=4)
        self.f_ende_bis = self._datum_feld(datum, "bis TT.MM.JJJJ")

        unten = ctk.CTkFrame(self.filterleiste, fg_color="transparent")
        unten.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkButton(unten, text="Schließen", width=90, height=32, corner_radius=8,
                      fg_color="transparent", text_color=TEXT_LEISE, hover_color=SEGMENT_HOVER,
                      font=self.schrift_normal, command=self.filter_umschalten).pack(side="right")
        ctk.CTkButton(unten, text="Filter zurücksetzen", width=150, height=32, corner_radius=8,
                      fg_color="transparent", text_color=AKZENT, hover_color=SEGMENT_HOVER,
                      font=self.schrift_normal, command=self.filter_zuruecksetzen).pack(side="right")

    def _filter_zelle(self, raster, nr, titel):
        zelle = ctk.CTkFrame(raster, fg_color="transparent")
        zelle.grid(row=nr // 4, column=nr % 4, sticky="ew", padx=6, pady=(0, 10))
        ctk.CTkLabel(zelle, text=titel, font=self.schrift_klein, text_color=TEXT_LEISE,
                     anchor="w", height=18).pack(fill="x")
        return zelle

    def _filter_combo(self, raster, nr, titel, werte):
        zelle = self._filter_zelle(raster, nr, titel)
        combo = ctk.CTkComboBox(zelle, values=werte, state="readonly", height=34, corner_radius=8,
                                border_width=1, border_color=EINGABE_RAND, fg_color=EINGABE_HG,
                                text_color=TEXT, button_color=SEGMENT_HG,
                                button_hover_color=SEGMENT_HOVER, dropdown_fg_color=KARTE,
                                dropdown_hover_color=SEGMENT_HG, dropdown_text_color=TEXT,
                                font=self.schrift_normal, dropdown_font=self.schrift_normal,
                                command=lambda _w: self._filter_aus_oberflaeche())
        combo.set(ALLE)
        if hasattr(combo, "_entry") and hasattr(combo, "_open_dropdown_menu"):
            combo._entry.bind("<Button-1>", lambda _e: combo._open_dropdown_menu())
        combo.pack(fill="x", pady=(4, 0))
        return combo

    def _datum_feld(self, eltern, platzhalter):
        feld = ctk.CTkEntry(eltern, height=34, corner_radius=8, border_width=1,
                            border_color=EINGABE_RAND, fg_color=EINGABE_HG, text_color=TEXT,
                            placeholder_text=platzhalter, placeholder_text_color=PLATZHALTER,
                            font=self.schrift_normal, width=120)
        feld.pack(side="left", fill="x", expand=True)
        feld.bind("<KeyRelease>", lambda _e: self._filter_aus_oberflaeche())
        return feld

    def _baue_tabelle(self):
        self.tabellen_karte = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=14,
                                           border_width=1, border_color=KARTE_RAND)
        self.tabellen_karte.pack(fill="both", expand=True, padx=24, pady=(0, 14))
        self.tabellen_rahmen = ctk.CTkFrame(self.tabellen_karte, fg_color="transparent", corner_radius=0)
        self.tabellen_rahmen.pack(fill="both", expand=True, padx=8, pady=8)
        self.tabellen_rahmen.rowconfigure(0, weight=1)
        self.tabellen_rahmen.columnconfigure(0, weight=1)

        self.tabelle = ttk.Treeview(self.tabellen_rahmen, columns=[s.key for s in SPALTEN],
                                    show="headings", style="Uebersicht.Treeview",
                                    selectmode="browse")
        for s in SPALTEN:
            self.tabelle.heading(s.key, text=s.titel, anchor=s.ausrichtung)
            self.tabelle.column(s.key, width=self.breiten.get(s.key, s.breite), minwidth=60,
                                anchor=s.ausrichtung, stretch=False)
        self._setze_anzeige_spalten()

        scroll_y = ctk.CTkScrollbar(self.tabellen_rahmen, command=self.tabelle.yview, bg_color=KARTE)
        scroll_x = ctk.CTkScrollbar(self.tabellen_rahmen, orientation="horizontal",
                                    command=self.tabelle.xview, bg_color=KARTE)
        self.tabelle.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tabelle.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        # blaue Linie, die beim Verschieben einer Spalte die Zielposition zeigt
        self.markierung = tk.Frame(self.tabelle, width=3, bd=0, highlightthickness=0)

        # Hinweis, wenn nichts gefunden wird
        self.leer_hinweis = ctk.CTkFrame(self.tabellen_rahmen, fg_color=KARTE)
        self.leer_titel = ctk.CTkLabel(self.leer_hinweis, text="", font=ctk.CTkFont(size=16, weight="bold"),
                                       text_color=TEXT)
        self.leer_titel.pack()
        self.leer_text = ctk.CTkLabel(self.leer_hinweis, text="", font=self.schrift_normal,
                                      text_color=TEXT_LEISE)
        self.leer_text.pack(pady=(2, 12))
        self.leer_knopf = ctk.CTkButton(self.leer_hinweis, text="", height=36, corner_radius=10,
                                        font=self.schrift_normal, fg_color=AKZENT,
                                        hover_color=AKZENT_HOVER)
        self.leer_knopf.pack()

        self.tabelle.bind("<ButtonPress-1>", self._maus_druck, add="+")
        self.tabelle.bind("<B1-Motion>", self._maus_ziehen, add="+")
        self.tabelle.bind("<ButtonRelease-1>", self._maus_loslassen, add="+")
        self.tabelle.bind("<Button-3>", self._rechtsklick)
        if sys.platform == "darwin":                       # Mac: Rechtsklick = Button-2 / Ctrl-Klick
            self.tabelle.bind("<Button-2>", self._rechtsklick)
            self.tabelle.bind("<Control-Button-1>", self._rechtsklick)

    def _baue_fusszeile(self):
        fuss = ctk.CTkFrame(self, fg_color="transparent")
        fuss.pack(side="bottom", fill="x", padx=32, pady=(0, 14))
        for farbe, text in ((FEHLER, "Kündigungsfrist verpasst"),
                            (WARNUNG, f"Kündigung in ≤ {WARN_TAGE} Tagen"),
                            (TEXT_LEISE, "Gekündigt / abgelaufen")):
            ctk.CTkLabel(fuss, text="●", text_color=farbe, font=self.schrift_normal).pack(side="left")
            ctk.CTkLabel(fuss, text=text, text_color=TEXT_LEISE,
                         font=self.schrift_klein).pack(side="left", padx=(4, 18))
        self.meldung = ctk.CTkLabel(fuss, text="", font=self.schrift_klein, text_color=TEXT_LEISE)
        self.meldung.pack(side="right")
        ctk.CTkLabel(fuss, text="Spaltenkopf ziehen = verschieben · Klick = sortieren · "
                                "Rechtsklick = weitere Optionen",
                     font=self.schrift_klein, text_color=TEXT_LEISE).pack(side="right", padx=24)

    def _style_tabelle(self):
        """Farben der Tabelle passend zum hellen bzw. dunklen Design."""
        dunkel = ctk.get_appearance_mode() == "Dark"

        def f(farbe):
            return farbe[1] if dunkel else farbe[0]

        style = ttk.Style(self)
        style.theme_use("clam")
        hg = f(KARTE)
        style.layout("Uebersicht.Treeview", [("Uebersicht.Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Uebersicht.Treeview", background=hg, fieldbackground=hg,
                        foreground=f(TEXT), rowheight=36, borderwidth=0, relief="flat",
                        font=self.schrift_tabelle)
        style.map("Uebersicht.Treeview", background=[("selected", f(AUSWAHL_HG))],
                  foreground=[("selected", f(TEXT))])
        kopf = f(KOPF_HG)
        style.configure("Uebersicht.Treeview.Heading", background=kopf, foreground=f(TEXT_LEISE),
                        font=self.schrift_kopf, relief="flat", borderwidth=1, padding=(8, 10),
                        bordercolor=f(KARTE_RAND), lightcolor=kopf, darkcolor=kopf)
        style.map("Uebersicht.Treeview.Heading",
                  background=[("pressed", f(SEGMENT_HOVER)), ("active", f(SEGMENT_HOVER))],
                  relief=[("pressed", "flat")])
        self.tabelle.tag_configure("streifen", background=f(STREIFEN_HG))
        self.tabelle.tag_configure("verpasst", foreground=f(FEHLER))
        self.tabelle.tag_configure("bald", foreground=f(WARNUNG))
        self.tabelle.tag_configure("beendet", foreground=f(TEXT_LEISE))
        self.markierung.configure(bg=f(AKZENT))

    # ---------- Daten ----------

    def aktualisieren(self):
        """Lädt alle Verträge neu aus der Datenbank."""
        try:
            daten = self.repo.finde_uebersicht()
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler",
                                 f"Die Verträge konnten nicht geladen werden:\n\n{fehler}", parent=self)
            return
        heute = date.today()
        self.alle_zeilen = [baue_zeile(d, heute) for d in daten]
        self.zeile_nach_id = {z["id"]: z for z in self.alle_zeilen}
        self._aktualisiere_filter_werte()
        self.anwenden()
        self.zeige_meldung(f"Aktualisiert um {datetime.now():%H:%M} Uhr")

    def _aktualisiere_filter_werte(self):
        """Die Auswahllisten im Filter enthalten nur Werte, die tatsächlich vorkommen."""
        for key, combo in self.filter_auswahl.items():
            werte = sorted({z[key] for z in self.alle_zeilen if z[key]}, key=str.casefold)
            combo.configure(values=[ALLE] + werte)
            if self.filter[key] is not None and self.filter[key] not in werte:
                self.filter[key] = None
            combo.set(self.filter[key] or ALLE)

    def anwenden(self):
        """Filter und Sortierung anwenden und die Liste neu füllen."""
        auswahl = self.tabelle.selection()
        zeilen = [z for z in self.alle_zeilen if passt(z, self.filter)]
        if self.sortierung:
            zeilen = sortiere_zeilen(zeilen, *self.sortierung)
        self.zeilen = zeilen

        self.tabelle.delete(*self.tabelle.get_children())
        for nr, z in enumerate(zeilen):
            tags = ["streifen"] if nr % 2 else []
            if z["status"] in ("Gekündigt", "Abgelaufen"):
                tags.append("beendet")
            elif z["tage"] is not None and z["tage"] < 0:
                tags.append("verpasst")
            elif z["tage"] is not None and z["tage"] <= WARN_TAGE:
                tags.append("bald")
            werte = []
            for s in SPALTEN:
                text = anzeige(s.key, z[s.key])
                werte.append(f"{text}  " if s.ausrichtung == "e" else f"  {text}" if s.ausrichtung == "w" else text)
            self.tabelle.insert("", "end", iid=str(z["id"]), values=werte, tags=tags)
        if auswahl and self.tabelle.exists(auswahl[0]):
            self.tabelle.selection_set(auswahl[0])

        gesamt = len(self.alle_zeilen)
        self.anzahl_text.configure(
            text=f"{len(zeilen)} von {gesamt} Verträgen" if len(zeilen) != gesamt
            else f"{gesamt} Vertrag" if gesamt == 1 else f"{gesamt} Verträge")
        self._zeige_kopfzeilen()
        self._zeige_filter_knopf()
        self._zeige_leer_hinweis()

    def _zeige_kopfzeilen(self):
        for s in SPALTEN:
            text = s.titel
            if self.sortierung and self.sortierung[0] == s.key:
                text += "  ▼" if self.sortierung[1] else "  ▲"
            self.tabelle.heading(s.key, text=text)

    def _zeige_leer_hinweis(self):
        if self.zeilen:
            self.leer_hinweis.place_forget()
            return
        if not self.alle_zeilen:
            self.leer_titel.configure(text="Noch keine Verträge vorhanden")
            self.leer_text.configure(text="Legen Sie den ersten Vertrag an.")
            self.leer_knopf.configure(text="+  Neuer Vertrag", command=self.neuer_vertrag)
        else:
            self.leer_titel.configure(text="Keine Verträge gefunden")
            self.leer_text.configure(text="Passen Sie die Suche oder die Filter an.")
            self.leer_knopf.configure(text="Alle Filter zurücksetzen", command=self.filter_zuruecksetzen)
        self.leer_hinweis.place(relx=0.5, rely=0.5, anchor="center")

    # ---------- Filter ----------

    def _suche_geaendert(self, _event=None):
        self.filter["suche"] = self.suchfeld.get().strip()
        self.anwenden()

    def _status_geaendert(self):
        wert = self.status_filter.get()
        self.filter["status"] = None if wert == ALLE else wert
        self.anwenden()

    def _filter_aus_oberflaeche(self):
        for key, combo in self.filter_auswahl.items():
            wert = combo.get()
            self.filter[key] = None if wert == ALLE else wert
        self.filter["frist"] = FRIST_OPTIONEN.get(self.f_frist.get())
        self.filter["ende_von"] = self._lese_datumsfilter(self.f_ende_von)
        self.filter["ende_bis"] = self._lese_datumsfilter(self.f_ende_bis)
        self.anwenden()

    def _lese_datumsfilter(self, feld):
        text = feld.get().strip()
        if not text:
            feld.configure(border_color=EINGABE_RAND)
            return None
        try:
            wert = lese_datum(text)
        except ValueError:
            feld.configure(border_color=FEHLER)       # ungültig: Filter wird ignoriert
            return None
        feld.configure(border_color=EINGABE_RAND)
        return wert

    def _anzahl_filter(self) -> int:
        """Anzahl der Filter aus der Filterleiste (ohne Suche und Status)."""
        return sum(1 for key, wert in self.filter.items()
                   if key not in ("suche", "status") and wert is not None)

    def filter_aktiv(self) -> bool:
        return self._anzahl_filter() > 0 or bool(self.filter["suche"]) or self.filter["status"] is not None

    def _zeige_filter_knopf(self):
        anzahl = self._anzahl_filter()
        if anzahl:
            self.filter_knopf.configure(text=f"Filter ({anzahl})", fg_color=AKZENT,
                                        hover_color=AKZENT_HOVER, text_color="#ffffff",
                                        border_color=AKZENT)
        else:
            self.filter_knopf.configure(text="Filter", fg_color="transparent",
                                        hover_color=SEGMENT_HOVER, text_color=TEXT,
                                        border_color=EINGABE_RAND)

    def filter_umschalten(self):
        if self.filterleiste.winfo_manager():
            self.filterleiste.pack_forget()
        else:
            self.filter_oeffnen()

    def filter_oeffnen(self):
        if not self.filterleiste.winfo_manager():
            self.filterleiste.pack(fill="x", padx=24, pady=(0, 12), before=self.tabellen_karte)

    def filter_zuruecksetzen(self):
        self.filter = leere_filter()
        for combo in self.filter_auswahl.values():
            combo.set(ALLE)
        self.f_frist.set(ALLE)
        for feld in (self.f_ende_von, self.f_ende_bis, self.suchfeld):
            self._leere(feld)
            feld.configure(border_color=EINGABE_RAND)
        self.status_filter.set(ALLE)
        self.anwenden()

    def filtere_nach(self, key: str, wert):
        """Rechtsklick „Nur … anzeigen“."""
        if key == "status":
            self.status_filter.set(wert)
            self.filter["status"] = wert
        else:
            self.filter[key] = wert
            self.filter_auswahl[key].set(wert)
            self.filter_oeffnen()
        self.anwenden()

    def suche_nach(self, text: str):
        self._leere(self.suchfeld)
        if text:
            self.suchfeld.insert(0, text)
        self.filter["suche"] = text
        self.anwenden()

    # ---------- Sortieren ----------

    def sortiere(self, key, absteigend=False):
        self.sortierung = (key, absteigend) if key else None
        self.anwenden()
        self._speichere_einstellungen()

    def _kopf_geklickt(self, key):
        if self.sortierung and self.sortierung[0] == key:
            self.sortiere(key, not self.sortierung[1])     # nochmal klicken = umgekehrt
        else:
            self.sortiere(key, False)

    # ---------- Spalten ziehen ----------

    def _spalte_bei(self, x):
        """Schlüssel der sichtbaren Spalte an der x-Position (oder None)."""
        spalte = self.tabelle.identify_column(x)
        anzeige_spalten = list(self.tabelle["displaycolumns"])
        try:
            nummer = int(spalte.lstrip("#"))
        except ValueError:
            return None
        return anzeige_spalten[nummer - 1] if 1 <= nummer <= len(anzeige_spalten) else None

    def _einfuege_position(self, x):
        """Wohin würde die Spalte beim Loslassen an x verschoben? -> (Index, x der Linie)"""
        anzeige_spalten = list(self.tabelle["displaycolumns"])
        breiten = [self.tabelle.column(k, "width") for k in anzeige_spalten]
        links = -self.tabelle.xview()[0] * sum(breiten)    # waagerechtes Scrollen beachten
        for index, breite in enumerate(breiten):
            if x < links + breite / 2:
                return index, links
            links += breite
        return len(anzeige_spalten), links

    def _maus_druck(self, event):
        if self.tabelle.identify_region(event.x, event.y) == "heading":
            self._ziehen = {"spalte": self._spalte_bei(event.x), "x": event.x, "aktiv": False}
        else:
            self._ziehen = None

    def _maus_ziehen(self, event):
        z = self._ziehen
        if not z or not z["spalte"]:
            return
        if not z["aktiv"] and abs(event.x - z["x"]) > 8:
            z["aktiv"] = True
            self.tabelle.configure(cursor="fleur")
        if z["aktiv"]:
            _, linie = self._einfuege_position(event.x)
            linie = max(0, min(linie, self.tabelle.winfo_width() - 3))
            self.markierung.place(x=linie - 1, y=0, width=3, relheight=1)
            self.markierung.lift()

    def _maus_loslassen(self, event):
        z, self._ziehen = self._ziehen, None
        self.markierung.place_forget()
        self.tabelle.configure(cursor="")
        if not z or not z["spalte"]:
            return
        if z["aktiv"]:
            self.verschiebe_spalte(z["spalte"], self._einfuege_position(event.x)[0])
        elif (self.tabelle.identify_region(event.x, event.y) == "heading"
              and self._spalte_bei(event.x) == z["spalte"]):
            self._kopf_geklickt(z["spalte"])

    def verschiebe_spalte(self, key, ziel_index):
        anzeige_spalten = list(self.tabelle["displaycolumns"])
        alt = anzeige_spalten.index(key)
        anzeige_spalten.pop(alt)
        if ziel_index > alt:
            ziel_index -= 1
        anzeige_spalten.insert(ziel_index, key)
        # Gesamtreihenfolge anpassen; ausgeblendete Spalten behalten ihren Platz
        neu = iter(anzeige_spalten)
        self.reihenfolge = [next(neu) if k not in self.ausgeblendet else k for k in self.reihenfolge]
        self._setze_anzeige_spalten()
        self._speichere_einstellungen()

    def _setze_anzeige_spalten(self):
        self.tabelle.configure(displaycolumns=[k for k in self.reihenfolge if k not in self.ausgeblendet])

    def setze_sichtbar(self, key, sichtbar: bool):
        if sichtbar:
            self.ausgeblendet.discard(key)
        elif len(self.reihenfolge) - len(self.ausgeblendet) > 1:   # mindestens eine bleibt
            self.ausgeblendet.add(key)
        self._setze_anzeige_spalten()
        self._speichere_einstellungen()

    def standardansicht(self):
        self.reihenfolge = [s.key for s in SPALTEN]
        self.ausgeblendet = {s.key for s in SPALTEN if not s.sichtbar}
        for s in SPALTEN:
            self.tabelle.column(s.key, width=s.breite)
        self.sortierung = STANDARD_SORTIERUNG
        self._setze_anzeige_spalten()
        self.anwenden()
        self._speichere_einstellungen()

    # ---------- Rechtsklick ----------

    def _neues_menue(self, eltern=None):
        dunkel = ctk.get_appearance_mode() == "Dark"
        i = 1 if dunkel else 0
        return tk.Menu(eltern or self, tearoff=0, bg=KARTE[i], fg=TEXT[i],
                       activebackground=AUSWAHL_HG[i], activeforeground=TEXT[i],
                       disabledforeground=TEXT_LEISE[i], selectcolor=AKZENT[i],
                       bd=1, relief="solid", font=self.schrift_normal)

    def baue_kontextmenue(self, x, y) -> tk.Menu:
        """Menü je nachdem, wohin geklickt wurde: Spaltenkopf, Zelle oder leere Fläche."""
        menue = self._neues_menue()
        self._menue_variablen = []
        bereich = self.tabelle.identify_region(x, y)
        key = self._spalte_bei(x)

        if bereich in ("heading", "separator") and key:
            titel = SPALTE[key].titel
            menue.add_command(label=f"Nach „{titel}“ aufsteigend sortieren",
                              command=lambda: self.sortiere(key, False))
            menue.add_command(label=f"Nach „{titel}“ absteigend sortieren",
                              command=lambda: self.sortiere(key, True))
            menue.add_command(label="Sortierung aufheben", command=lambda: self.sortiere(None),
                              state="normal" if self.sortierung else "disabled")
            menue.add_separator()
            letzte = len(self.reihenfolge) - len(self.ausgeblendet) <= 1
            menue.add_command(label=f"Spalte „{titel}“ ausblenden",
                              command=lambda: self.setze_sichtbar(key, False),
                              state="disabled" if letzte else "normal")
            spalten_menue = self._neues_menue(menue)
            for s in SPALTEN:
                variable = tk.BooleanVar(value=s.key not in self.ausgeblendet)
                self._menue_variablen.append(variable)
                spalten_menue.add_checkbutton(
                    label=s.titel, variable=variable,
                    command=lambda k=s.key, v=variable: self.setze_sichtbar(k, v.get()))
            menue.add_cascade(label="Spalten ein- und ausblenden", menu=spalten_menue)
            menue.add_command(label="Standardansicht wiederherstellen", command=self.standardansicht)
            menue.add_separator()

        elif bereich == "cell" and key:
            zeile_id = self.tabelle.identify_row(y)
            if zeile_id:
                self.tabelle.selection_set(zeile_id)
                self.tabelle.focus(zeile_id)
                z = self.zeile_nach_id[int(zeile_id)]
                text = anzeige(key, z[key])
                if text and SPALTE[key].filter:
                    menue.add_command(label=f"Nur „{kurz(text)}“ anzeigen",
                                      command=lambda: self.filtere_nach(SPALTE[key].filter, z[key]))
                elif text:
                    menue.add_command(label=f"Nach „{kurz(text)}“ suchen",
                                      command=lambda: self.suche_nach(text))
                if text:
                    menue.add_command(label="Wert kopieren", command=lambda: self.kopiere(text))
                    menue.add_separator()

        menue.add_command(label="Filter anpassen …", command=self.filter_oeffnen)
        menue.add_command(label="Alle Filter zurücksetzen", command=self.filter_zuruecksetzen,
                          state="normal" if self.filter_aktiv() else "disabled")
        menue.add_separator()
        menue.add_command(label="Aktualisieren", accelerator="F5", command=self.aktualisieren)
        return menue

    def _rechtsklick(self, event):
        menue = self.baue_kontextmenue(event.x, event.y)
        try:
            menue.tk_popup(event.x_root, event.y_root)
        finally:
            menue.grab_release()

    def kopiere(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.zeige_meldung(f"„{kurz(text)}“ kopiert")

    # ---------- Neuer Vertrag ----------

    def neuer_vertrag(self):
        """Öffnet das Erfassungsformular. Nach dem Schließen wird die Liste neu geladen."""
        if self._erfassen_prozess is not None and self._erfassen_prozess.poll() is None:
            self.zeige_meldung("Das Fenster „Neuen Vertrag erfassen“ ist bereits geöffnet.")
            return
        if not ERFASSEN_DATEI.is_file():
            messagebox.showerror("Datei fehlt", f"{ERFASSEN_DATEI.name} wurde nicht gefunden.\n"
                                                "Sie muss im selben Ordner liegen.", parent=self)
            return
        self._erfassen_prozess = subprocess.Popen([sys.executable, str(ERFASSEN_DATEI)], cwd=ORDNER)
        self.after(1000, self._pruefe_erfassen)

    def _pruefe_erfassen(self):
        if self._erfassen_prozess is None:
            return
        if self._erfassen_prozess.poll() is None:
            self.after(1000, self._pruefe_erfassen)
        else:
            self._erfassen_prozess = None
            self.aktualisieren()

    # ---------- Einstellungen ----------

    def _lade_einstellungen(self):
        try:
            daten = json.loads(EINSTELLUNGEN_DATEI.read_text(encoding="utf-8"))
            if not isinstance(daten, dict):
                daten = {}
        except (OSError, ValueError):
            daten = {}
        alle = [s.key for s in SPALTEN]

        reihenfolge = [k for k in daten.get("reihenfolge", []) if k in alle]
        self.reihenfolge = reihenfolge + [k for k in alle if k not in reihenfolge]
        ausgeblendet = daten.get("ausgeblendet")
        if not isinstance(ausgeblendet, list):
            ausgeblendet = [s.key for s in SPALTEN if not s.sichtbar]
        self.ausgeblendet = {k for k in ausgeblendet if k in alle}
        if len(self.ausgeblendet) >= len(alle):
            self.ausgeblendet = set()

        self.breiten = {}
        for k, breite in (daten.get("breiten") or {}).items():
            if k in alle and isinstance(breite, int) and 40 <= breite <= 1500:
                self.breiten[k] = breite

        sortierung = daten.get("sortierung", list(STANDARD_SORTIERUNG))
        if isinstance(sortierung, list) and len(sortierung) == 2 and sortierung[0] in alle:
            self.sortierung = (sortierung[0], bool(sortierung[1]))
        elif sortierung is None:
            self.sortierung = None
        else:
            self.sortierung = STANDARD_SORTIERUNG
        self.design = "dark" if daten.get("design") == "dark" else "light"

    def _speichere_einstellungen(self):
        daten = {
            "reihenfolge": self.reihenfolge,
            "ausgeblendet": sorted(self.ausgeblendet),
            "breiten": {s.key: int(self.tabelle.column(s.key, "width")) for s in SPALTEN},
            "sortierung": list(self.sortierung) if self.sortierung else None,
            "design": self.design,
        }
        try:
            EINSTELLUNGEN_DATEI.write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
        except OSError:
            pass                       # z. B. keine Schreibrechte: dann eben nicht gespeichert

    # ---------- Sonstiges ----------

    def _leere(self, feld):
        """Eingabefeld leeren und den grauen Platzhaltertext wieder anzeigen."""
        feld.delete(0, "end")
        if self.focus_get() is not getattr(feld, "_entry", None) and hasattr(feld, "_entry_focus_out"):
            feld._entry_focus_out()

    def zeige_meldung(self, text: str):
        self.meldung.configure(text=text)

    def _design_wechseln(self):
        self.design = "dark" if self.dunkel.get() else "light"
        ctk.set_appearance_mode(self.design)
        self._style_tabelle()
        self._speichere_einstellungen()

    def beenden(self):
        self._speichere_einstellungen()          # merkt sich auch die Spaltenbreiten
        self.db.trennen()
        for after_id in self.tk.eval("after info").split():   # offene Timer beenden
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        self.destroy()


# =====================================================
# START
# =====================================================

def main():
    ctk.set_default_color_theme("blue")
    db = Datenbankverbindung(DB_CONFIG, DB_TYPE)
    try:
        db.verbinden()
    except dbapi.Error as fehler:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Verbindung fehlgeschlagen",
                             f"Keine Verbindung zur Datenbank möglich:\n\n{fehler}\n\n"
                             "Bitte die Einstellungen in vertragsverwaltung_gui.py prüfen.")
        root.destroy()
        return
    Vertragsuebersicht(db).mainloop()


if __name__ == "__main__":
    main()

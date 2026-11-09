"""
Vertragsübersicht – Verträge ansehen, filtern, neu anlegen und bearbeiten

Eine durchsuchbare Liste aller Verträge. Per Doppelklick (oder Button
"Bearbeiten") öffnet sich der Vertrag im selben Formular wie beim Erfassen,
mit denselben Prüfungen. Beim Speichern wird der Vertrag in der Datenbank
aktualisiert (UPDATE), danach zeigt die Liste den neuen Stand.

Bedienung der Liste:
    Suchen              oben ins Suchfeld tippen (mehrere Wörter: alle müssen vorkommen)
    Status              Auswahl neben dem Suchfeld
    Weitere Filter      Button „Filter“ oder Rechtsklick → „Filter anpassen …“
    Sortieren           Klick auf einen Spaltenkopf, nochmal klicken = umgekehrt
    Spalten verschieben Spaltenkopf mit gedrückter Maustaste nach links/rechts ziehen
    Spalten ein/aus     Rechtsklick auf einen Spaltenkopf
    Nach Wert filtern   Rechtsklick auf eine Zelle, z. B. auf einen Vertragspartner
    Aktualisieren       F5, Button „Liste neu laden“ oder Rechtsklick → „Aktualisieren“

Reihenfolge, Breite und Sichtbarkeit der Spalten sowie die Sortierung werden
in einstellungen_vertraege_uebersicht.json (neben dieser Datei) gespeichert.

Benötigt vertrag_erfassen.py und vertragsverwaltung_gui.py im selben Ordner.
"""

import json
import sys
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk

from vertrag_erfassen import (
    AKZENT, AKZENT_HOVER, EINGABE_HG, EINGABE_RAND, ERFOLG, FEHLER, HINTERGRUND, KARTE, KARTE_RAND,
    INTERVALL_ANZEIGE, PLATZHALTER, SEGMENT_HG, SEGMENT_HOVER, STATUS_ANZEIGE, TEXT, TEXT_LEISE,
    WARNUNG, VertragBearbeiten, VertragUnterfenster, berechne_kuendigungsstichtag,
)
from vertragsverwaltung_gui import (
    DB_CONFIG, DB_TYPE, Datenbankverbindung, VertragRepository, dbapi, formatiere_betrag, lese_datum,
)


EINSTELLUNGEN_DATEI = Path(__file__).resolve().with_name("einstellungen_vertraege_uebersicht.json")

ALLE_STATUS = "Alle Status"
ALLE = "Alle"
STATUS_TEXT = {wert: text for text, wert in STATUS_ANZEIGE.items()}
INTERVALL_TEXT = {wert: text for text, wert in INTERVALL_ANZEIGE.items()}

WARN_TAGE = 90                     # Kündigungsstichtag in <= 90 Tagen -> orange
AUSWAHL_HG = "#dbe7fd"
STREIFEN_HG = "#fafbfc"

FRIST_OPTIONEN = {                 # Anzeige -> (Art, Tage)
    ALLE: None,
    "Bereits verpasst": ("verpasst", 0),
    "In den nächsten 30 Tagen": ("bis", 30),
    "In den nächsten 60 Tagen": ("bis", 60),
    "In den nächsten 90 Tagen": ("bis", 90),
    "In den nächsten 180 Tagen": ("bis", 180),
    "Im nächsten Jahr": ("bis", 365),
}


# =====================================================
# SPALTEN DER TABELLE
# =====================================================

class Spalte:
    def __init__(self, key, titel, breite, ausrichtung="w", sichtbar=True, filter=None):
        self.key = key                  # Schlüssel in der Zeile (siehe tabellenzeile)
        self.titel = titel
        self.breite = breite
        self.ausrichtung = ausrichtung  # w = links, e = rechts, center
        self.sichtbar = sichtbar        # Standard: sichtbar oder ausgeblendet
        self.filter = filter            # Rechtsklick „Nur … anzeigen“ setzt diesen Filter


SPALTEN = [
    Spalte("nummer", "Nummer", 95),
    Spalte("titel", "Titel", 160),
    Spalte("partner", "Vertragspartner", 140, filter="partner"),
    Spalte("art", "Vertragsart", 100, filter="art"),
    Spalte("verantwortlich", "Verantwortlich", 115, filter="verantwortlich"),
    Spalte("abteilung", "Abteilung", 85, filter="abteilung"),
    Spalte("laufzeit", "Monate", 70, filter="laufzeit"),
    Spalte("beginn", "Beginn", 80),
    Spalte("ende", "Ende", 80),
    Spalte("stichtag", "Kündigen bis", 95, sichtbar=False),
    Spalte("tage", "Noch Tage", 80, "e", sichtbar=False),
    Spalte("kosten", "Kosten", 165),
    Spalte("status", "Status", 80, filter="status"),
]
SPALTE = {s.key: s for s in SPALTEN}
STANDARD_SORTIERUNG = None           # wie aus der Datenbank: neueste zuerst

# Filter aus der Filterleiste: Schlüssel -> Überschrift
AUSWAHL_FILTER = [("art", "Vertragsart"), ("partner", "Vertragspartner"),
                  ("verantwortlich", "Verantwortlich"), ("abteilung", "Abteilung"),
                  ("laufzeit", "Laufzeit (Monate)"), ("intervall", "Zahlungsintervall")]


def tabellenzeile(v: dict, heute: date) -> dict:
    """Vertrag aus der Datenbank -> Werte für Tabelle, Filter und Sortierung."""
    stichtag = None
    if v["end_datum"] is not None:
        stichtag = berechne_kuendigungsstichtag(v["end_datum"], v["kuendigungsfrist_tage"])
    # Tage bis zum Stichtag nur bei Verträgen, bei denen man noch handeln kann
    offen = v["status"] in ("aktiv", "entwurf")
    laufzeit = v["laufzeit"]
    return {
        "id": v["id_vertrag"],
        "nummer": v["vertragsnummer"],
        "titel": v["titel"],
        "partner": v["firmenname"],
        "art": v["vertragsart"],
        "verantwortlich": f"{v['vorname']} {v['nachname']}",
        "abteilung": v["abteilung"],
        "laufzeit": int(laufzeit) if str(laufzeit).isdigit() else laufzeit,
        "beginn": v["beginn_datum"],
        "ende": v["end_datum"],
        "stichtag": stichtag,
        "tage": (stichtag - heute).days if stichtag is not None and offen else None,
        "kosten": v["kosten"],
        "intervall": INTERVALL_TEXT.get(v["zahlungsintervall"], v["zahlungsintervall"]),
        "status": STATUS_TEXT.get(v["status"], v["status"]),
        "beschreibung": v.get("beschreibung") or "",
    }


def anzeige(key: str, z: dict) -> str:
    """Text einer Zelle."""
    wert = z[key]
    if key == "ende" and wert is None:
        return "unbefristet"
    if wert is None:
        return ""
    if key in ("beginn", "ende", "stichtag"):
        return f"{wert:%d.%m.%Y}"
    if key == "kosten":
        text = f"{formatiere_betrag(wert)} €"
        return f"{text} ({z['intervall']})" if z["intervall"] else text
    return str(wert)


def leere_filter() -> dict:
    return {"suche": "", "status": None, "art": None, "partner": None, "verantwortlich": None,
            "abteilung": None, "laufzeit": None, "intervall": None, "frist": None,
            "ende_von": None, "ende_bis": None}


def passt_zum_filter(z: dict, f: dict) -> bool:
    """True, wenn die Zeile alle Filter erfüllt."""
    for key in ("status", "art", "partner", "verantwortlich", "abteilung", "laufzeit", "intervall"):
        if f[key] is not None and str(z[key]) != str(f[key]):
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
        text = " ".join(anzeige(s.key, z) for s in SPALTEN).lower() + " " + z["beschreibung"].lower()
        if not all(wort in text for wort in f["suche"].lower().split()):
            return False
    return True


def sortiere_zeilen(zeilen: list, key: str, absteigend: bool) -> list:
    """Sortiert nach einer Spalte. Leere Werte stehen immer am Ende."""
    mit_wert = [z for z in zeilen if z[key] not in (None, "")]
    ohne_wert = [z for z in zeilen if z[key] in (None, "")]

    def schluessel(z):
        wert = z[key]
        return wert.lower() if isinstance(wert, str) else wert

    try:
        return sorted(mit_wert, key=schluessel, reverse=absteigend) + ohne_wert
    except TypeError:            # gemischte Werte (z. B. Zahl und Text): als Text sortieren
        return sorted(mit_wert, key=lambda z: str(z[key]).lower(), reverse=absteigend) + ohne_wert


def kurz(text: str, laenge=32) -> str:
    return text if len(text) <= laenge else text[:laenge - 1] + "…"


# =====================================================
# HAUPTFENSTER
# =====================================================

class VertragsUebersicht(ctk.CTk):
    def __init__(self, db: Datenbankverbindung):
        super().__init__()
        self.db = db
        self.repo = VertragRepository(db)
        self.vertraege = []
        self.zeilen = {}                 # id -> Zeile (alle Verträge)
        self.bearbeiten_fenster = None
        self.filter = leere_filter()
        self._ziehen = None              # Zustand beim Verschieben einer Spalte
        self._menue_variablen = []
        self._lade_einstellungen()

        self.title("Vertragsübersicht")
        self.geometry("1280x720")
        self.minsize(820, 480)
        self.configure(fg_color=HINTERGRUND)
        self.protocol("WM_DELETE_WINDOW", self.beenden)

        self.schrift_titel = ctk.CTkFont(size=24, weight="bold")
        self.schrift_feld = ctk.CTkFont(size=13, weight="bold")
        self.schrift_normal = ctk.CTkFont(size=13)
        self.schrift_klein = ctk.CTkFont(size=12)

        self._baue_kopfzeile()
        self._baue_fusszeile()
        self._baue_filterleiste()
        self._baue_tabelle()
        self.bind("<F5>", lambda _e: self.neu_laden())
        self.neu_laden()

    # ---------- Aufbau ----------

    def _baue_kopfzeile(self):
        kopf = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=0)
        kopf.pack(fill="x")
        ctk.CTkLabel(kopf, text="Vertragsübersicht", font=self.schrift_titel, text_color=TEXT,
                     anchor="w").pack(fill="x", padx=32, pady=(18, 0))
        ctk.CTkLabel(kopf, text="Doppelklick auf einen Vertrag öffnet ihn zum Bearbeiten. "
                                "Spaltenkopf ziehen = verschieben, Klick = sortieren, "
                                "Rechtsklick = weitere Optionen.",
                     font=self.schrift_normal, text_color=TEXT_LEISE,
                     anchor="w").pack(fill="x", padx=32)

        filter_zeile = ctk.CTkFrame(kopf, fg_color="transparent")
        filter_zeile.pack(fill="x", padx=32, pady=(12, 18))
        self.suche = ctk.CTkEntry(filter_zeile, placeholder_text="Suchen: Nummer, Titel, Partner …",
                                  height=36, width=340, corner_radius=8, border_width=1,
                                  border_color=EINGABE_RAND, fg_color=EINGABE_HG, text_color=TEXT,
                                  font=self.schrift_normal)
        self.suche.pack(side="left")
        self.suche.bind("<KeyRelease>", lambda _e: self._suche_geaendert())
        self.suche.bind("<Escape>", lambda _e: self.suche_nach(""))

        self.status_filter = ctk.CTkOptionMenu(filter_zeile, values=[ALLE_STATUS, *STATUS_ANZEIGE],
                                               height=36, width=150, corner_radius=8,
                                               fg_color=SEGMENT_HG, button_color=SEGMENT_HG,
                                               button_hover_color=SEGMENT_HOVER, text_color=TEXT,
                                               dropdown_fg_color=KARTE, dropdown_text_color=TEXT,
                                               dropdown_hover_color=SEGMENT_HG, font=self.schrift_normal,
                                               command=lambda _w: self._status_geaendert())
        self.status_filter.pack(side="left", padx=(10, 0))

        ctk.CTkButton(filter_zeile, text="Liste neu laden", command=self.neu_laden, height=36, width=130,
                      corner_radius=8, font=self.schrift_normal, fg_color="transparent",
                      border_width=1, border_color=EINGABE_RAND, text_color=TEXT,
                      hover_color=KARTE_RAND).pack(side="right")
        self.filter_knopf = ctk.CTkButton(filter_zeile, text="Filter", command=self.filter_umschalten,
                                          height=36, width=110, corner_radius=8, border_width=1,
                                          font=self.schrift_normal)
        self.filter_knopf.pack(side="right", padx=10)
        self._zeige_filter_knopf()

    def _baue_fusszeile(self):
        fuss = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=0)
        fuss.pack(side="bottom", fill="x")
        self.status = ctk.CTkLabel(fuss, text="", font=self.schrift_normal, text_color=TEXT_LEISE,
                                   anchor="w", justify="left")
        self.status.pack(side="left", padx=32, fill="x", expand=True)
        ctk.CTkButton(fuss, text="Bearbeiten", command=self.bearbeiten, height=42, width=160,
                      corner_radius=10, font=self.schrift_feld, fg_color=AKZENT,
                      hover_color=AKZENT_HOVER).pack(side="right", padx=(8, 32), pady=15)
        ctk.CTkButton(fuss, text="Neuer Vertrag", command=self.neuer_vertrag, height=42, width=160,
                      corner_radius=10, font=self.schrift_feld, fg_color="transparent",
                      border_width=1, border_color=AKZENT, text_color=AKZENT,
                      hover_color=KARTE_RAND).pack(side="right", pady=15)
        # Farblegende (von rechts nach links gepackt, daher umgekehrte Reihenfolge)
        for farbe, text in ((TEXT_LEISE, "Gekündigt / abgelaufen"),
                            (WARNUNG, f"Kündigung in ≤ {WARN_TAGE} Tagen"),
                            (FEHLER, "Kündigungsfrist verpasst")):
            ctk.CTkLabel(fuss, text=f"● {text}", text_color=farbe,
                         font=self.schrift_klein).pack(side="right", padx=(0, 16))

    def _baue_filterleiste(self):
        """Wird erst über den Button „Filter“ oder per Rechtsklick eingeblendet."""
        self.filterleiste = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=14,
                                         border_width=1, border_color=KARTE_RAND)
        raster = ctk.CTkFrame(self.filterleiste, fg_color="transparent")
        raster.pack(fill="x", padx=20, pady=(14, 6))
        raster.columnconfigure((0, 1, 2, 3), weight=1, uniform="filter")

        self.filter_auswahl = {}          # Filter-Schlüssel -> Combobox
        for nr, (key, titel) in enumerate(AUSWAHL_FILTER):
            self.filter_auswahl[key] = self._filter_combo(raster, nr, titel, [ALLE])
        nr = len(AUSWAHL_FILTER)
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
                            font=self.schrift_normal, width=110)
        feld.pack(side="left", fill="x", expand=True)
        feld.bind("<KeyRelease>", lambda _e: self._filter_aus_oberflaeche())
        return feld

    def _baue_tabelle(self):
        stil = ttk.Style(self)
        stil.theme_use("clam")
        hell = lambda farbe: farbe[0]
        stil.configure("Vertraege.Treeview", background=hell(KARTE), fieldbackground=hell(KARTE),
                       foreground=hell(TEXT), rowheight=32, borderwidth=0, font=("Segoe UI", 10))
        stil.configure("Vertraege.Treeview.Heading", background=hell(SEGMENT_HG), foreground=hell(TEXT),
                       relief="flat", padding=6, font=("Segoe UI", 10, "bold"))
        stil.map("Vertraege.Treeview", background=[("selected", hell(AKZENT))],
                 foreground=[("selected", "#ffffff")])
        stil.map("Vertraege.Treeview.Heading", background=[("active", hell(SEGMENT_HOVER))])

        self.tabellen_rahmen = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=14, border_width=1,
                                            border_color=KARTE_RAND)
        self.tabellen_rahmen.pack(fill="both", expand=True, padx=24, pady=16)
        rahmen = self.tabellen_rahmen

        self.tabelle = ttk.Treeview(rahmen, columns=[s.key for s in SPALTEN], show="headings",
                                    style="Vertraege.Treeview", selectmode="browse")
        for s in SPALTEN:
            self.tabelle.heading(s.key, text=s.titel, anchor=s.ausrichtung)
            self.tabelle.column(s.key, width=self.breiten.get(s.key, s.breite), minwidth=50,
                                anchor=s.ausrichtung, stretch=False)
        self._setze_anzeige_spalten()
        scroll = ctk.CTkScrollbar(rahmen, command=self.tabelle.yview)
        scroll_quer = ctk.CTkScrollbar(rahmen, orientation="horizontal", command=self.tabelle.xview)
        self.tabelle.configure(yscrollcommand=scroll.set, xscrollcommand=scroll_quer.set)
        scroll_quer.pack(side="bottom", fill="x", padx=(8, 6), pady=(0, 6))
        scroll.pack(side="right", fill="y", padx=(0, 6), pady=(8, 0))
        self.tabelle.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(8, 0))

        self.tabelle.tag_configure("streifen", background=STREIFEN_HG)
        self.tabelle.tag_configure("verpasst", foreground=FEHLER[0])
        self.tabelle.tag_configure("bald", foreground=WARNUNG[0])
        self.tabelle.tag_configure("beendet", foreground=TEXT_LEISE[0])

        # blaue Linie, die beim Verschieben einer Spalte die Zielposition zeigt
        self.markierung = tk.Frame(self.tabelle, width=3, bd=0, highlightthickness=0, bg=AKZENT[0])

        self.leer_hinweis = ctk.CTkLabel(rahmen, text="", font=self.schrift_normal, text_color=TEXT_LEISE,
                                         fg_color=KARTE)

        self.tabelle.bind("<Double-1>", self._doppelklick)
        self.tabelle.bind("<Return>", lambda _e: self.bearbeiten())
        self.tabelle.bind("<ButtonPress-1>", self._maus_druck, add="+")
        self.tabelle.bind("<B1-Motion>", self._maus_ziehen, add="+")
        self.tabelle.bind("<ButtonRelease-1>", self._maus_loslassen, add="+")
        self.tabelle.bind("<Button-3>", self._rechtsklick)
        if sys.platform == "darwin":                       # Mac: Rechtsklick = Button-2 / Ctrl-Klick
            self.tabelle.bind("<Button-2>", self._rechtsklick)
            self.tabelle.bind("<Control-Button-1>", self._rechtsklick)

    # ---------- Daten ----------

    def neu_laden(self):
        try:
            self.vertraege = self.repo.finde_alle()
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", f"Die Verträge konnten nicht geladen werden:\n\n{fehler}")
            return
        heute = date.today()
        self.zeilen = {v["id_vertrag"]: tabellenzeile(v, heute) for v in self.vertraege}
        self._aktualisiere_filter_werte()
        self.zeige_vertraege()

    def _aktualisiere_filter_werte(self):
        """Die Auswahllisten im Filter enthalten nur Werte, die tatsächlich vorkommen."""
        for key, combo in self.filter_auswahl.items():
            werte = {z[key] for z in self.zeilen.values() if z[key] not in (None, "")}
            werte = [str(w) for w in sorted(werte, key=lambda w: (isinstance(w, str), str(w).lower()))]
            combo.configure(values=[ALLE] + werte)
            if self.filter[key] is not None and str(self.filter[key]) not in werte:
                self.filter[key] = None
            combo.set(ALLE if self.filter[key] is None else str(self.filter[key]))

    def zeige_vertraege(self):
        """Filter und Sortierung anwenden und die Tabelle neu füllen."""
        gewaehlt = self.tabelle.selection()
        self.tabelle.delete(*self.tabelle.get_children())

        zeilen = [z for z in self.zeilen.values() if passt_zum_filter(z, self.filter)]
        if self.sortierung:
            zeilen = sortiere_zeilen(zeilen, *self.sortierung)
        for nr, z in enumerate(zeilen):
            tags = ["streifen"] if nr % 2 else []
            if z["status"] in ("Gekündigt", "Abgelaufen"):
                tags.append("beendet")
            elif z["tage"] is not None and z["tage"] < 0:
                tags.append("verpasst")
            elif z["tage"] is not None and z["tage"] <= WARN_TAGE:
                tags.append("bald")
            self.tabelle.insert("", "end", iid=str(z["id"]), tags=tags,
                                values=[anzeige(s.key, z) for s in SPALTEN])
        if gewaehlt and self.tabelle.exists(gewaehlt[0]):
            self.tabelle.selection_set(gewaehlt[0])

        if zeilen:
            self.leer_hinweis.place_forget()
        else:
            self.leer_hinweis.configure(text="Keine passenden Verträge gefunden." if self.vertraege
                                        else "Es sind noch keine Verträge gespeichert.")
            self.leer_hinweis.place(relx=0.5, rely=0.5, anchor="center")
        self.status.configure(text=f"{len(zeilen)} von {len(self.vertraege)} Verträgen", text_color=TEXT_LEISE)
        self._zeige_kopfzeilen()
        self._zeige_filter_knopf()

    def _zeige_kopfzeilen(self):
        for s in SPALTEN:
            text = s.titel
            if self.sortierung and self.sortierung[0] == s.key:
                text += "  ▼" if self.sortierung[1] else "  ▲"
            self.tabelle.heading(s.key, text=text)

    # ---------- Filter ----------

    def _suche_geaendert(self):
        self.filter["suche"] = self.suche.get().strip()
        self.zeige_vertraege()

    def _status_geaendert(self):
        wert = self.status_filter.get()
        self.filter["status"] = None if wert == ALLE_STATUS else wert
        self.zeige_vertraege()

    def _filter_aus_oberflaeche(self):
        for key, combo in self.filter_auswahl.items():
            wert = combo.get()
            self.filter[key] = None if wert == ALLE else wert
        self.filter["frist"] = FRIST_OPTIONEN.get(self.f_frist.get())
        self.filter["ende_von"] = self._lese_datumsfilter(self.f_ende_von)
        self.filter["ende_bis"] = self._lese_datumsfilter(self.f_ende_bis)
        self.zeige_vertraege()

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
                                        hover_color=KARTE_RAND, text_color=TEXT,
                                        border_color=EINGABE_RAND)

    def filter_umschalten(self):
        if self.filterleiste.winfo_manager():
            self.filterleiste.pack_forget()
        else:
            self.filter_oeffnen()

    def filter_oeffnen(self):
        if not self.filterleiste.winfo_manager():
            self.filterleiste.pack(fill="x", padx=24, pady=(16, 0), before=self.tabellen_rahmen)

    def filter_zuruecksetzen(self):
        self.filter = leere_filter()
        for combo in self.filter_auswahl.values():
            combo.set(ALLE)
        self.f_frist.set(ALLE)
        for feld in (self.f_ende_von, self.f_ende_bis, self.suche):
            self._leere(feld)
            feld.configure(border_color=EINGABE_RAND)
        self.status_filter.set(ALLE_STATUS)
        self.zeige_vertraege()

    def filtere_nach(self, key: str, wert):
        """Rechtsklick „Nur … anzeigen“."""
        if key == "status":
            self.status_filter.set(wert)
            self.filter["status"] = wert
        else:
            self.filter[key] = str(wert)
            self.filter_auswahl[key].set(str(wert))
            self.filter_oeffnen()
        self.zeige_vertraege()

    def suche_nach(self, text: str):
        self._leere(self.suche)
        if text:
            self.suche.insert(0, text)
        self.filter["suche"] = text
        self.zeige_vertraege()

    def _leere(self, feld):
        """Eingabefeld leeren und den grauen Platzhaltertext wieder anzeigen."""
        feld.delete(0, "end")
        if self.focus_get() is not getattr(feld, "_entry", None) and hasattr(feld, "_entry_focus_out"):
            feld._entry_focus_out()

    # ---------- Sortieren ----------

    def sortiere(self, key, absteigend=False):
        self.sortierung = (key, absteigend) if key else None
        self.zeige_vertraege()
        self._speichere_einstellungen()

    def _kopf_geklickt(self, key):
        if self.sortierung and self.sortierung[0] == key:
            self.sortiere(key, not self.sortierung[1])     # nochmal klicken = umgekehrt
        else:
            self.sortiere(key, False)

    # ---------- Spalten mit der Maus verschieben ----------

    def _spalte_bei(self, x):
        """Schlüssel der sichtbaren Spalte an der x-Position (oder None)."""
        anzeige_spalten = list(self.tabelle["displaycolumns"])
        try:
            nummer = int(self.tabelle.identify_column(x).lstrip("#"))
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
        self.zeige_vertraege()
        self._speichere_einstellungen()

    # ---------- Rechtsklick ----------

    def _neues_menue(self, eltern=None):
        return tk.Menu(eltern or self, tearoff=0, bg=KARTE[0], fg=TEXT[0],
                       activebackground=AUSWAHL_HG, activeforeground=TEXT[0],
                       disabledforeground=TEXT_LEISE[0], selectcolor=AKZENT[0],
                       font=self.schrift_normal)

    def baue_kontextmenue(self, x, y) -> tk.Menu:
        """Menü je nachdem, wohin geklickt wurde: Spaltenkopf, Zeile oder leere Fläche."""
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
                self._menue_variablen.append(variable)       # sonst räumt Python sie weg
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
                z = self.zeilen[int(zeile_id)]
                text = anzeige(key, z)
                menue.add_command(label="Vertrag bearbeiten …", command=self.bearbeiten)
                menue.add_separator()
                if z[key] not in (None, "") and SPALTE[key].filter:
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
        menue.add_command(label="Aktualisieren", accelerator="F5", command=self.neu_laden)
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
        self.status.configure(text=f"„{kurz(text)}“ kopiert", text_color=TEXT_LEISE)

    # ---------- Neu anlegen und bearbeiten ----------

    def _doppelklick(self, event):
        if self.tabelle.identify_region(event.x, event.y) == "heading":
            self._maus_druck(event)      # schneller zweiter Klick auf einen Spaltenkopf = normaler Klick
        elif self.tabelle.identify_row(event.y):
            self.bearbeiten()

    def _fenster_schon_offen(self) -> bool:
        if self.bearbeiten_fenster is None or not self.bearbeiten_fenster.winfo_exists():
            return False
        self.status.configure(text="Bitte zuerst das offene Vertragsfenster schließen.", text_color=FEHLER)
        self.bearbeiten_fenster.lift()
        self.bearbeiten_fenster.focus_force()
        return True

    def neuer_vertrag(self):
        if self._fenster_schon_offen():
            return
        try:
            self.bearbeiten_fenster = VertragUnterfenster(self.db, self._gespeichert)
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))

    def bearbeiten(self):
        auswahl = self.tabelle.selection()
        if not auswahl:
            self.status.configure(text="Bitte zuerst einen Vertrag in der Liste auswählen.", text_color=FEHLER)
            return
        if self._fenster_schon_offen():
            return
        try:
            daten = self.repo.finde_nach_id(int(auswahl[0]))     # immer der aktuelle Stand
            if daten is None:
                messagebox.showwarning("Nicht gefunden", "Diesen Vertrag gibt es nicht mehr.")
                self.neu_laden()
                return
            self.bearbeiten_fenster = VertragBearbeiten(self.db, daten, self._gespeichert)
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))

    def _gespeichert(self, id_vertrag: int, zusammenfassung: str):
        self.neu_laden()
        if self.tabelle.exists(str(id_vertrag)):
            self.tabelle.selection_set(str(id_vertrag))
            self.tabelle.see(str(id_vertrag))
        self.status.configure(text=zusammenfassung, text_color=ERFOLG)

    # ---------- Einstellungen speichern und laden ----------

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

        self.breiten = {k: b for k, b in (daten.get("breiten") or {}).items()
                        if k in alle and isinstance(b, int) and 40 <= b <= 1500}

        sortierung = daten.get("sortierung")
        if isinstance(sortierung, list) and len(sortierung) == 2 and sortierung[0] in alle:
            self.sortierung = (sortierung[0], bool(sortierung[1]))
        else:
            self.sortierung = STANDARD_SORTIERUNG

    def _speichere_einstellungen(self):
        daten = {
            "reihenfolge": self.reihenfolge,
            "ausgeblendet": sorted(self.ausgeblendet),
            "breiten": {s.key: int(self.tabelle.column(s.key, "width")) for s in SPALTEN},
            "sortierung": list(self.sortierung) if self.sortierung else None,
        }
        try:
            EINSTELLUNGEN_DATEI.write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
        except OSError:
            pass                       # z. B. keine Schreibrechte: dann eben nicht gespeichert

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
    ctk.set_appearance_mode("light")
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
    VertragsUebersicht(db).mainloop()


if __name__ == "__main__":
    main()

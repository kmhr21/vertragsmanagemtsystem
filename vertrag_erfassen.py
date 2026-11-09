"""
Vertrag erfassen – Oberfläche für Endbenutzer

Ein modernes Formular, in dem ein neuer Vertrag mit allen Daten erfasst wird:
    1. Vertragsdaten        (Nummer, Titel, Art, Laufzeit, Verantwortlicher, Status)
    2. Vertragspartner      (bestehenden wählen oder neuen anlegen, optional Ansprechpartner)
    3. Laufzeit & Kündigung (mit live berechnetem Kündigungsstichtag)
    4. Kosten               (mit Hochrechnung auf ein Jahr)
    5. Dokument             (z. B. der Vertrag als PDF)

Alles wird in EINER Transaktion gespeichert: Entweder landen alle Daten in
der Datenbank oder bei einem Fehler gar keine (Atomarität).

Benötigt zusätzlich:
    pip install customtkinter

Die Datenbank-Einstellungen (DB_TYPE, Passwort, ...) stehen in
vertragsverwaltung_gui.py. Beide Dateien müssen im selben Ordner liegen.
"""

import re
import shutil
import tkinter as tk
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from vertragsverwaltung_gui import (
    DB_CONFIG, DB_TYPE, ABTEILUNGEN_AKTIV, dbapi,
    Datenbankverbindung, VertragRepository, VertragspartnerRepository,
    AnsprechpartnerRepository, BenutzerRepository, VertragsartRepository,
    LaufzeitRepository, AbteilungRepository, DokumentRepository,
    lese_datum, lese_betrag, formatiere_betrag,
)


# Dokumente werden in diesen Ordner kopiert (neben dieser Datei)
DOKUMENT_ORDNER = Path(__file__).resolve().parent / "dokumente"


# =====================================================
# FARBEN (jeweils hell, dunkel)
# =====================================================

HINTERGRUND = ("#f3f5f9", "#15171c")
KARTE = ("#ffffff", "#1f2229")
KARTE_RAND = ("#e3e7ee", "#2c3039")
TEXT = ("#1c2430", "#e8eaed")
TEXT_LEISE = ("#6b7480", "#9aa1ab")
EINGABE_RAND = ("#cfd5de", "#3a3f4a")
EINGABE_HG = ("#f9fafb", "#2a2e36")
PLATZHALTER = ("#9aa1ab", "#6b7480")
SEGMENT_HG = ("#e8ecf2", "#2a2e36")
SEGMENT_HOVER = ("#dde3eb", "#343944")
SEGMENT_AKTIV = ("#ffffff", "#4a5160")
AKZENT = ("#2563eb", "#3b82f6")
AKZENT_HOVER = ("#1d4ed8", "#2563eb")
FEHLER = ("#d93838", "#ff6b6b")
WARNUNG = ("#b45309", "#fbbf24")
ERFOLG = ("#15803d", "#4ade80")
ERFOLG_HG = ("#e8f6ec", "#15291c")
INFO_HG = ("#eef3fd", "#1b2436")


# =====================================================
# ANZEIGETEXTE <-> DATENBANKWERTE
# =====================================================

STATUS_ANZEIGE = {"Entwurf": "entwurf", "Aktiv": "aktiv",
                  "Gekündigt": "gekuendigt", "Abgelaufen": "abgelaufen"}

INTERVALL_ANZEIGE = {"Einmalig": "einmalig", "Monatlich": "monatlich",
                     "Quartalsweise": "quartalsweise", "Halbjährlich": "halbjaehrlich",
                     "Jährlich": "jaehrlich"}

PARTNER_BESTEHEND = "Bestehender Partner"
PARTNER_NEU = "Neuer Partner"

BITTE_WAEHLEN = "Bitte wählen …"
EMAIL_MUSTER = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# =====================================================
# GESCHÄFTSLOGIK (ohne Oberfläche, gut mit pytest testbar)
# =====================================================

ZAHLUNGEN_PRO_JAHR = {"monatlich": 12, "quartalsweise": 4, "halbjaehrlich": 2, "jaehrlich": 1}


def berechne_kuendigungsstichtag(end_datum: date, frist_tage) -> date:
    """Letzter Tag, an dem der Vertrag noch gekündigt werden kann."""
    return end_datum - timedelta(days=frist_tage or 0)


def berechne_jahreskosten(kosten: Decimal, intervall: str):
    """Kosten pro Jahr; None bei einmaliger Zahlung oder unbekanntem Intervall."""
    anzahl = ZAHLUNGEN_PRO_JAHR.get(intervall)
    return None if anzahl is None else kosten * anzahl


def eindeutige_auswahl(eintraege) -> dict:
    """[(id, text), ...] -> {text: id}. Gleiche Texte bekommen die Nummer angehängt."""
    anzahl = Counter(text for _, text in eintraege)
    ergebnis = {}
    for id_wert, text in eintraege:
        if anzahl[text] > 1:
            text = f"{text} (Nr. {id_wert})"
        ergebnis[text] = id_wert
    return ergebnis


def kopiere_dokument(quelle: Path, vertragsnummer: str) -> Path:
    """Kopiert die Datei in den Dokumente-Ordner. Name: <Vertragsnummer>_<Dateiname>."""
    DOKUMENT_ORDNER.mkdir(exist_ok=True)
    praefix = re.sub(r"[^A-Za-z0-9._-]", "_", vertragsnummer)
    ziel = DOKUMENT_ORDNER / f"{praefix}_{quelle.name}"
    nummer = 2
    while ziel.exists():
        ziel = DOKUMENT_ORDNER / f"{praefix}_{quelle.stem}_{nummer}{quelle.suffix}"
        nummer += 1
    shutil.copy2(quelle, ziel)
    return ziel


# =====================================================
# BAUSTEINE DER OBERFLÄCHE
# =====================================================

def kreis(eltern, text: str, farbe, schrift):
    """Runder Punkt mit Text (Schrittnummer, Häkchen)."""
    punkt = ctk.CTkFrame(eltern, width=30, height=30, corner_radius=15, fg_color=farbe)
    ctk.CTkLabel(punkt, text=text, text_color="#ffffff", font=schrift, fg_color="transparent",
                 width=20, height=20).place(relx=0.5, rely=0.5, anchor="center")
    return punkt


def segmente(eltern, app, werte, command=None):
    """Umschalter im modernen Stil: heller Hintergrund, gewählter Teil als weiße Fläche."""
    return ctk.CTkSegmentedButton(eltern, values=list(werte), height=36, font=app.schrift_normal,
                                  fg_color=SEGMENT_HG, unselected_color=SEGMENT_HG,
                                  unselected_hover_color=SEGMENT_HOVER, selected_color=SEGMENT_AKTIV,
                                  selected_hover_color=SEGMENT_AKTIV, text_color=TEXT,
                                  command=command)

class Formularfeld(ctk.CTkFrame):
    """Beschriftung oben, Eingabe in der Mitte, Hinweis bzw. Fehlertext darunter.

    Pflichtfelder bekommen ein rotes *. Bei einem Fehler wird der Rahmen rot
    und der Fehlertext erscheint. Sobald man tippt, verschwindet der Fehler.
    """

    def __init__(self, eltern, app, beschriftung: str, pflicht=False, hinweis=""):
        super().__init__(eltern, fg_color="transparent")
        self.app = app
        self.beschriftung = beschriftung
        self.hinweis = hinweis
        self.pflicht = pflicht
        self.hat_fehler = False

        self.kopf = ctk.CTkFrame(self, fg_color="transparent")
        self.kopf.pack(fill="x")
        ctk.CTkLabel(self.kopf, text=beschriftung, font=app.schrift_feld,
                     text_color=TEXT, height=22).pack(side="left")
        self._stern = ctk.CTkLabel(self.kopf, text="", font=app.schrift_feld,
                                   text_color=FEHLER, height=22)
        self._stern.pack(side="left", padx=(3, 0))

        self.eingabe = self._erzeuge_eingabe()
        self.eingabe.pack(fill="x", pady=(4, 0))

        self._meldung = ctk.CTkLabel(self, text=hinweis, font=app.schrift_klein,
                                     text_color=TEXT_LEISE, anchor="w", justify="left", height=20)
        self._meldung.pack(fill="x")
        self.setze_pflicht(pflicht)
        app.alle_felder.append(self)

    def _erzeuge_eingabe(self):
        raise NotImplementedError

    def setze_pflicht(self, pflicht: bool):
        self.pflicht = pflicht
        self._stern.configure(text="*" if pflicht else "")

    def setze_hinweis(self, text: str):
        self.hinweis = text
        if not self.hat_fehler:
            self._meldung.configure(text=text)

    def zeige_fehler(self, text: str):
        self.hat_fehler = True
        self.eingabe.configure(border_color=FEHLER)
        self._meldung.configure(text=text, text_color=FEHLER)
        self.app.fehlerfelder.append(self)

    def loesche_fehler(self):
        if self.hat_fehler:
            self.hat_fehler = False
            self.eingabe.configure(border_color=EINGABE_RAND)
            self._meldung.configure(text=self.hinweis, text_color=TEXT_LEISE)

    def _geaendert(self, _event=None):
        self.loesche_fehler()
        self.app.bei_aenderung()


class TextFeld(Formularfeld):
    def __init__(self, eltern, app, beschriftung, platzhalter="", **kwargs):
        self.platzhalter = platzhalter
        super().__init__(eltern, app, beschriftung, **kwargs)

    def _erzeuge_eingabe(self):
        eingabe = ctk.CTkEntry(self, placeholder_text=self.platzhalter, height=36,
                               corner_radius=8, border_width=1, border_color=EINGABE_RAND,
                               fg_color=EINGABE_HG, text_color=TEXT,
                               placeholder_text_color=PLATZHALTER, font=self.app.schrift_normal)
        eingabe.bind("<KeyRelease>", self._geaendert)
        return eingabe

    def get(self) -> str:
        return self.eingabe.get().strip()

    def set(self, text: str):
        zustand = self.eingabe.cget("state")
        self.eingabe.configure(state="normal")
        self.eingabe.delete(0, "end")
        if text:
            self.eingabe.insert(0, text)
        self.eingabe.configure(state=zustand)
        if not text:
            self.app.focus_set()        # sonst zeigt CTkEntry den Platzhalter nicht wieder an

    def aktiv(self, ja: bool):
        if not ja:
            self.set("")
            self.loesche_fehler()
        self.eingabe.configure(state="normal" if ja else "disabled")


class GanzzahlFeld(TextFeld):
    """Textfeld, in das nur Ziffern getippt oder eingefügt werden können."""

    def _erzeuge_eingabe(self):
        eingabe = super()._erzeuge_eingabe()
        eingabe.configure(validate="key",
                          validatecommand=(self.register(self._erlaubt), "%P"))
        return eingabe

    @staticmethod
    def _erlaubt(neuer_text: str) -> bool:
        return re.fullmatch(r"[0-9]*", neuer_text) is not None


class AuswahlFeld(Formularfeld):
    def _erzeuge_eingabe(self):
        combo = ctk.CTkComboBox(self, values=[], state="readonly", height=36, corner_radius=8,
                                border_width=1, border_color=EINGABE_RAND, fg_color=EINGABE_HG,
                                text_color=TEXT, button_color=SEGMENT_HG,
                                button_hover_color=SEGMENT_HOVER, dropdown_fg_color=KARTE,
                                dropdown_hover_color=SEGMENT_HG, dropdown_text_color=TEXT,
                                font=self.app.schrift_normal, dropdown_font=self.app.schrift_normal,
                                command=lambda _wert: self._geaendert())
        # Klick auf das ganze Feld öffnet die Liste (nicht nur auf den Pfeil)
        if hasattr(combo, "_entry") and hasattr(combo, "_open_dropdown_menu"):
            combo._entry.bind("<Button-1>", lambda _e: combo._open_dropdown_menu())
        return combo

    def setze_werte(self, werte):
        self.eingabe.configure(values=list(werte) if werte else ["Keine Einträge vorhanden"])
        self.set("")

    def get(self) -> str:
        wert = self.eingabe.get()
        return "" if wert in (BITTE_WAEHLEN, "Keine Einträge vorhanden") else wert

    def set(self, text: str):
        self.eingabe.set(text or BITTE_WAEHLEN)


class MehrzeiligFeld(Formularfeld):
    def _erzeuge_eingabe(self):
        textfeld = ctk.CTkTextbox(self, height=80, corner_radius=8, border_width=1,
                                  border_color=EINGABE_RAND, fg_color=EINGABE_HG, text_color=TEXT,
                                  font=self.app.schrift_normal)
        textfeld.bind("<KeyRelease>", self._geaendert)
        return textfeld

    def get(self) -> str:
        return self.eingabe.get("1.0", "end-1c").strip()

    def set(self, text: str):
        self.eingabe.delete("1.0", "end")
        if text:
            self.eingabe.insert("1.0", text)


class Raster(ctk.CTkFrame):
    """Ordnet Felder automatisch in zwei Spalten an."""

    def __init__(self, eltern):
        super().__init__(eltern, fg_color="transparent")
        self.columnconfigure((0, 1), weight=1, uniform="spalte")
        self._zeile = 0
        self._spalte = 0

    def add(self, widget, breit=False):
        if breit:
            if self._spalte == 1:
                self._zeile += 1
            widget.grid(row=self._zeile, column=0, columnspan=2, sticky="ew", pady=(0, 6))
            self._zeile += 1
            self._spalte = 0
        else:
            widget.grid(row=self._zeile, column=self._spalte, sticky="new", pady=(0, 6),
                        padx=(0, 10) if self._spalte == 0 else (10, 0))
            self._spalte += 1
            if self._spalte == 2:
                self._spalte = 0
                self._zeile += 1
        return widget

    def leer(self):
        """Eine Zelle frei lassen."""
        self.add(ctk.CTkFrame(self, fg_color="transparent", height=1))


class Karte(ctk.CTkFrame):
    """Ein Abschnitt des Formulars mit Nummer, Titel und Untertitel."""

    def __init__(self, eltern, app, nummer: int, titel: str, untertitel: str):
        super().__init__(eltern, fg_color=KARTE, corner_radius=14,
                         border_width=1, border_color=KARTE_RAND)
        kopf = ctk.CTkFrame(self, fg_color="transparent")
        kopf.pack(fill="x", padx=24, pady=(20, 14))
        kreis(kopf, str(nummer), AKZENT, app.schrift_feld).pack(side="left", anchor="n", pady=(2, 0))
        texte = ctk.CTkFrame(kopf, fg_color="transparent")
        texte.pack(side="left", padx=(12, 0), fill="x")
        ctk.CTkLabel(texte, text=titel, font=app.schrift_karte, text_color=TEXT,
                     anchor="w", height=24).pack(fill="x")
        ctk.CTkLabel(texte, text=untertitel, font=app.schrift_klein, text_color=TEXT_LEISE,
                     anchor="w", height=18).pack(fill="x")
        self.raster = Raster(self)
        self.raster.pack(fill="x", padx=24, pady=(0, 16))


class Infobox(ctk.CTkFrame):
    """Hellblaue Box für berechnete Werte (Kündigungsstichtag, Jahreskosten)."""

    def __init__(self, eltern, app):
        super().__init__(eltern, fg_color=INFO_HG, corner_radius=10)
        self._text = ctk.CTkLabel(self, text="", font=app.schrift_normal, text_color=TEXT,
                                  anchor="w", justify="left")
        self._text.pack(fill="x", padx=14, pady=10)

    def setze(self, text: str, farbe=TEXT):
        self._text.configure(text=text, text_color=farbe)

    def get(self) -> str:
        return self._text.cget("text")


# =====================================================
# HAUPTFENSTER
# =====================================================

class VertragFormular:
    """Das Formular selbst. Wird mit einem Fenstertyp kombiniert (siehe unten):
    VertragErfassen = neuer Vertrag, VertragBearbeiten = bestehender Vertrag."""

    FENSTERTITEL = "Neuen Vertrag erfassen"
    SPEICHERN_TEXT = "Vertrag speichern"
    MIT_DESIGN_SCHALTER = True
    dokument_leer_text = "Keine Datei ausgewählt"
    behalte_benutzer = None      # dieser Benutzer bleibt wählbar, auch wenn er inaktiv ist

    def __init__(self, db: Datenbankverbindung, **kwargs):
        super().__init__(**kwargs)
        self.db = db
        self.repos = {
            "vertrag": VertragRepository(db),
            "vertragspartner": VertragspartnerRepository(db),
            "ansprechpartner": AnsprechpartnerRepository(db),
            "benutzer": BenutzerRepository(db),
            "vertragsart": VertragsartRepository(db),
            "laufzeit": LaufzeitRepository(db),
            "dokument": DokumentRepository(db),
        }
        if ABTEILUNGEN_AKTIV:
            self.repos["abteilung"] = AbteilungRepository(db)

        self.auswahl = {}            # z. B. "vertragsart" -> {anzeigetext: id}
        self.alle_felder = []
        self.fehlerfelder = []
        self.dokument = None         # Path der gewählten Datei

        self.title(self.FENSTERTITEL)
        self.geometry("1040x860")
        self.minsize(820, 600)
        self.configure(fg_color=HINTERGRUND)
        self.protocol("WM_DELETE_WINDOW", self.beenden)
        self.bind("<Control-s>", lambda _e: self.speichern())

        self.schrift_titel = ctk.CTkFont(size=24, weight="bold")
        self.schrift_karte = ctk.CTkFont(size=16, weight="bold")
        self.schrift_feld = ctk.CTkFont(size=13, weight="bold")
        self.schrift_normal = ctk.CTkFont(size=13)
        self.schrift_klein = ctk.CTkFont(size=12)

        self._baue_kopfzeile()
        self._baue_fusszeile()       # vor dem Inhalt packen, damit sie immer sichtbar bleibt
        self.inhalt = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.inhalt.pack(fill="both", expand=True, padx=16)
        self.inhalt.columnconfigure(0, weight=1)

        self._baue_erfolgsmeldung()
        self._karte_vertragsdaten()
        self._karte_partner()
        self._karte_laufzeit()
        self._karte_kosten()
        self._karte_dokument()

        self.lade_auswahllisten()
        self.formular_leeren()

    # ---------- Kopf- und Fußzeile ----------

    def _baue_kopfzeile(self):
        kopf = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=0, height=88)
        kopf.pack(fill="x")
        texte = ctk.CTkFrame(kopf, fg_color="transparent")
        texte.pack(side="left", padx=32, pady=18)
        ctk.CTkLabel(texte, text=self.FENSTERTITEL, font=self.schrift_titel,
                     text_color=TEXT, anchor="w").pack(fill="x")
        hinweis = ctk.CTkFrame(texte, fg_color="transparent")
        hinweis.pack(fill="x")
        ctk.CTkLabel(hinweis, text="Bitte alle Angaben zum Vertrag eintragen. Pflichtfelder sind mit ",
                     font=self.schrift_normal, text_color=TEXT_LEISE).pack(side="left")
        ctk.CTkLabel(hinweis, text="*", font=self.schrift_feld, text_color=FEHLER).pack(side="left")
        ctk.CTkLabel(hinweis, text=" markiert.", font=self.schrift_normal,
                     text_color=TEXT_LEISE).pack(side="left")

        if self.MIT_DESIGN_SCHALTER:
            self.dunkel = ctk.CTkSwitch(kopf, text="Dunkles Design", font=self.schrift_normal,
                                        text_color=TEXT_LEISE, progress_color=AKZENT,
                                        command=self._design_wechseln)
            self.dunkel.pack(side="right", padx=32)

    def _baue_fusszeile(self):
        fuss = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=0, height=72)
        fuss.pack(side="bottom", fill="x")
        self.status = ctk.CTkLabel(fuss, text="", font=self.schrift_normal, anchor="w")
        self.status.pack(side="left", padx=32, fill="x", expand=True)
        ctk.CTkButton(fuss, text=self.SPEICHERN_TEXT, command=self.speichern, height=42, width=180,
                      corner_radius=10, font=self.schrift_feld, fg_color=AKZENT,
                      hover_color=AKZENT_HOVER).pack(side="right", padx=(8, 32), pady=15)
        ctk.CTkButton(fuss, text="Zurücksetzen", command=self.zuruecksetzen, height=42, width=140,
                      corner_radius=10, font=self.schrift_feld, fg_color="transparent",
                      border_width=1, border_color=EINGABE_RAND, text_color=TEXT,
                      hover_color=KARTE_RAND).pack(side="right", pady=15)

    def _baue_erfolgsmeldung(self):
        self.erfolg = ctk.CTkFrame(self.inhalt, fg_color=ERFOLG_HG, corner_radius=12,
                                   border_width=1, border_color=ERFOLG)
        self.erfolg.grid(row=0, column=0, sticky="ew", padx=8, pady=(16, 0))
        kreis(self.erfolg, "✓", ERFOLG, self.schrift_feld).pack(side="left", padx=(16, 12), pady=14)
        self.erfolg_text = ctk.CTkLabel(self.erfolg, text="", font=self.schrift_normal,
                                        text_color=TEXT, anchor="w", justify="left")
        self.erfolg_text.pack(side="left", fill="x", expand=True, pady=12)
        ctk.CTkButton(self.erfolg, text="✕", width=30, height=30, fg_color="transparent",
                      text_color=TEXT_LEISE, hover_color=KARTE_RAND,
                      command=self.erfolg.grid_remove).pack(side="right", padx=12)
        self.erfolg.grid_remove()

    def _neue_karte(self, nummer, titel, untertitel) -> Raster:
        karte = Karte(self.inhalt, self, nummer, titel, untertitel)
        karte.grid(row=nummer, column=0, sticky="ew", padx=8, pady=(16, 0))
        return karte.raster

    # ---------- Abschnitt 1: Vertragsdaten ----------

    def _karte_vertragsdaten(self):
        r = self._neue_karte(1, "Vertragsdaten", "Worum geht es in dem Vertrag?")
        self.f_nummer = r.add(TextFeld(r, self, "Vertragsnummer", pflicht=True,
                                       platzhalter="z. B. V-2026-001",
                                       hinweis="Vorschlag – kann geändert werden"))
        self.f_titel = r.add(TextFeld(r, self, "Titel", pflicht=True,
                                      platzhalter="z. B. Wartung Druckerflotte"))
        self.f_art = r.add(TextFeld(r, self, "Vertragsart", pflicht=True,
                                    platzhalter="z. B. Wartung"))
        self.f_laufzeit = r.add(GanzzahlFeld(r, self, "Laufzeit in Monaten", pflicht=True,
                                             hinweis="Nur ganze Zahlen, z. B. 12"))
        self.f_verantwortlich = r.add(AuswahlFeld(r, self, "Verantwortlich", pflicht=True,
                                                  hinweis="Wer betreut den Vertrag?"))
        self.f_abteilung = None
        if ABTEILUNGEN_AKTIV:
            self.f_abteilung = r.add(AuswahlFeld(r, self, "Abteilung", pflicht=True))
            r.leer()

        status = ctk.CTkFrame(r, fg_color="transparent")
        ctk.CTkLabel(status, text="Status", font=self.schrift_feld, text_color=TEXT,
                     anchor="w", height=22).pack(fill="x")
        self.f_status = segmente(status, self, STATUS_ANZEIGE)
        self.f_status.pack(fill="x", pady=(4, 20))
        r.add(status)

        self.f_beschreibung = r.add(MehrzeiligFeld(r, self, "Beschreibung",
                                                   hinweis="Optional: Leistungsumfang, Besonderheiten …"),
                                    breit=True)

    # ---------- Abschnitt 2: Vertragspartner ----------

    def _karte_partner(self):
        r = self._neue_karte(2, "Vertragspartner", "Mit wem wird der Vertrag geschlossen?")
        self.f_partner_modus = segmente(r, self, [PARTNER_BESTEHEND, PARTNER_NEU],
                                        command=lambda _w: self._partner_modus_anzeigen())
        r.add(self.f_partner_modus, breit=True)

        # bestehender Partner
        self.r_bestehend = r.add(Raster(r), breit=True)
        self.f_partner = self.r_bestehend.add(
            AuswahlFeld(self.r_bestehend, self, "Vertragspartner", pflicht=True,
                        hinweis=f"Nicht in der Liste? Oben „{PARTNER_NEU}“ wählen."), breit=True)

        # neuer Partner
        n = self.r_neu = r.add(Raster(r), breit=True)
        self.f_firma = n.add(TextFeld(n, self, "Firmenname", pflicht=True,
                                      platzhalter="z. B. Muster GmbH"), breit=True)
        self.f_strasse = n.add(TextFeld(n, self, "Straße und Hausnummer"))
        self.f_plz = n.add(TextFeld(n, self, "PLZ"))
        self.f_ort = n.add(TextFeld(n, self, "Ort"))
        self.f_land = n.add(TextFeld(n, self, "Land"))
        self.f_p_email = n.add(TextFeld(n, self, "E-Mail", platzhalter="info@firma.de"))
        self.f_p_telefon = n.add(TextFeld(n, self, "Telefon"))

        # Ansprechpartner
        self.f_mit_ansprech = ctk.CTkSwitch(r, text="Ansprechpartner hinzufügen",
                                            font=self.schrift_feld, text_color=TEXT,
                                            progress_color=AKZENT,
                                            command=self._ansprechpartner_anzeigen)
        r.add(self.f_mit_ansprech, breit=True)
        a = self.r_ansprech = r.add(Raster(r), breit=True)
        self.f_a_vorname = a.add(TextFeld(a, self, "Vorname"))
        self.f_a_nachname = a.add(TextFeld(a, self, "Nachname", pflicht=True))
        self.f_a_position = a.add(TextFeld(a, self, "Position", platzhalter="z. B. Account Manager"))
        self.f_a_email = a.add(TextFeld(a, self, "E-Mail"))
        self.f_a_telefon = a.add(TextFeld(a, self, "Telefon"))

    def _partner_modus_anzeigen(self):
        neu = self.f_partner_modus.get() == PARTNER_NEU
        (self.r_neu.grid if neu else self.r_neu.grid_remove)()
        (self.r_bestehend.grid_remove if neu else self.r_bestehend.grid)()
        for feld in (self.f_partner, self.f_firma):
            feld.loesche_fehler()

    def _ansprechpartner_anzeigen(self):
        if self.f_mit_ansprech.get():
            self.r_ansprech.grid()
        else:
            self.r_ansprech.grid_remove()

    # ---------- Abschnitt 3: Laufzeit & Kündigung ----------

    def _karte_laufzeit(self):
        r = self._neue_karte(3, "Laufzeit & Kündigung", "Wann beginnt und endet der Vertrag?")
        self.f_beginn = r.add(TextFeld(r, self, "Beginn", pflicht=True, platzhalter="TT.MM.JJJJ"))
        self.f_ende = r.add(TextFeld(r, self, "Ende", pflicht=True, platzhalter="TT.MM.JJJJ"))
        self.f_unbefristet = ctk.CTkCheckBox(self.f_ende.kopf, text="unbefristet",
                                             font=self.schrift_klein, text_color=TEXT_LEISE,
                                             checkbox_width=18, checkbox_height=18, height=22,
                                             fg_color=AKZENT, command=self._unbefristet_geaendert)
        self.f_unbefristet.pack(side="right")

        self.f_frist = r.add(TextFeld(r, self, "Kündigungsfrist (Tage)", platzhalter="z. B. 30",
                                      hinweis="Wie viele Tage vor Vertragsende muss gekündigt werden?"))
        self.f_monate = r.add(TextFeld(r, self, "Automatische Verlängerung",
                                       platzhalter="Monate, z. B. 12"))
        self.f_auto = ctk.CTkSwitch(self.f_monate.kopf, text="", width=46, height=22,
                                    progress_color=AKZENT, command=self._auto_geaendert)
        self.f_auto.pack(side="right")

        self.info_stichtag = r.add(Infobox(r, self), breit=True)

    def _unbefristet_geaendert(self):
        unbefristet = bool(self.f_unbefristet.get())
        self.f_ende.aktiv(not unbefristet)
        self.f_ende.setze_pflicht(not unbefristet)
        self.bei_aenderung()

    def _auto_geaendert(self):
        auto = bool(self.f_auto.get())
        self.f_monate.aktiv(auto)
        self.f_monate.setze_pflicht(auto)
        self.f_monate.setze_hinweis("Um wie viele Monate verlängert sich der Vertrag?" if auto
                                    else "Aus: Der Vertrag endet zum Enddatum.")
        self.bei_aenderung()

    # ---------- Abschnitt 4: Kosten ----------

    def _karte_kosten(self):
        r = self._neue_karte(4, "Kosten", "Was kostet der Vertrag?")
        self.f_kosten = r.add(TextFeld(r, self, "Betrag (€)", platzhalter="z. B. 1.234,56"))
        self.f_intervall = r.add(AuswahlFeld(r, self, "Zahlungsintervall"))
        self.f_intervall.setze_werte(INTERVALL_ANZEIGE)
        self.info_kosten = r.add(Infobox(r, self), breit=True)

    # ---------- Abschnitt 5: Dokument ----------

    def _karte_dokument(self):
        r = self._neue_karte(5, "Dokument", "Optional: den Vertrag als Datei anhängen (z. B. PDF)")
        zeile = ctk.CTkFrame(r, fg_color="transparent")
        ctk.CTkButton(zeile, text="Datei auswählen …", command=self._datei_waehlen, height=36,
                      corner_radius=8, font=self.schrift_normal, fg_color="transparent",
                      border_width=1, border_color=AKZENT, text_color=AKZENT,
                      hover_color=INFO_HG).pack(side="left")
        self.dokument_name = ctk.CTkLabel(zeile, text=self.dokument_leer_text,
                                          font=self.schrift_normal, text_color=TEXT_LEISE)
        self.dokument_name.pack(side="left", padx=14)
        self.dokument_entfernen = ctk.CTkButton(zeile, text="Entfernen", width=90, height=30,
                                                fg_color="transparent", text_color=FEHLER,
                                                hover_color=KARTE_RAND, font=self.schrift_normal,
                                                command=lambda: self._setze_dokument(None))
        r.add(zeile, breit=True)
        ctk.CTkLabel(r, text=f"Die Datei wird beim Speichern in den Ordner „{DOKUMENT_ORDNER.name}“ kopiert.",
                     font=self.schrift_klein, text_color=TEXT_LEISE, anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="ew")

    def _datei_waehlen(self):
        pfad = filedialog.askopenfilename(
            title="Vertragsdokument auswählen",
            filetypes=[("PDF-Dateien", "*.pdf"), ("Alle Dateien", "*.*")])
        if pfad:
            self._setze_dokument(Path(pfad))

    def _setze_dokument(self, pfad):
        self.dokument = pfad
        if pfad:
            self.dokument_name.configure(text=pfad.name, text_color=TEXT)
            self.dokument_entfernen.pack(side="left")
        else:
            self.dokument_name.configure(text=self.dokument_leer_text, text_color=TEXT_LEISE)
            self.dokument_entfernen.pack_forget()

    # ---------- Auswahllisten aus der Datenbank ----------

    def lade_auswahllisten(self):
        try:
            benutzer = self.repos["benutzer"].finde_alle_als_dict()
            partner = self.repos["vertragspartner"].finde_alle()
            abteilungen = self.repos["abteilung"].finde_alle() if ABTEILUNGEN_AKTIV else []
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler",
                                 f"Die Auswahllisten konnten nicht geladen werden:\n\n{fehler}")
            return

        self.auswahl["benutzer"] = eindeutige_auswahl(          # nur aktive Benutzer
            [(z["id_benutzer"], f"{z['vorname']} {z['nachname']}") for z in benutzer
             if z["aktiv"] or z["id_benutzer"] == self.behalte_benutzer])
        self.auswahl["vertragspartner"] = eindeutige_auswahl(
            [(z["id_vertragspartner"], z["firmenname"] + (f" – {z['ort']}" if z["ort"] else ""))
             for z in sorted(partner, key=lambda z: z["firmenname"].lower())])
        self.auswahl["abteilung"] = eindeutige_auswahl(
            [(z["id_abteilung"], z["bezeichnung"]) for z in abteilungen])

        self.f_verantwortlich.setze_werte(self.auswahl["benutzer"])
        self.f_partner.setze_werte(self.auswahl["vertragspartner"])
        if self.f_abteilung:
            self.f_abteilung.setze_werte(self.auswahl["abteilung"])

    # ---------- Live-Berechnungen ----------

    def bei_aenderung(self):
        self._zeige_stichtag()
        self._zeige_jahreskosten()

    def _zeige_stichtag(self):
        if self.f_unbefristet.get():
            self.info_stichtag.setze("Unbefristeter Vertrag – es gibt keinen festen Kündigungsstichtag.",
                                     TEXT_LEISE)
            return
        try:
            ende = lese_datum(self.f_ende.get())
            frist = int(self.f_frist.get() or 0)
        except ValueError:
            self.info_stichtag.setze("Der Kündigungsstichtag wird berechnet, sobald Ende und "
                                     "Kündigungsfrist eingetragen sind.", TEXT_LEISE)
            return
        stichtag = berechne_kuendigungsstichtag(ende, frist)
        tage = (stichtag - date.today()).days
        text = f"Kündigungsstichtag: {stichtag:%d.%m.%Y}"
        if tage < 0:
            text += f" – bereits verstrichen (vor {-tage} Tagen)"
            if self.f_auto.get():
                text += ". Der Vertrag verlängert sich automatisch."
            farbe = FEHLER
        elif tage == 0:
            text += " – heute!"
            farbe = FEHLER
        else:
            text += f" – noch {tage} Tage"
            farbe = WARNUNG if tage <= 90 else ERFOLG
        self.info_stichtag.setze(text, farbe)

    def _zeige_jahreskosten(self):
        intervall = INTERVALL_ANZEIGE.get(self.f_intervall.get())
        try:
            kosten = lese_betrag(self.f_kosten.get())
        except (InvalidOperation, ValueError):
            kosten = None
        if kosten is None or intervall is None:
            self.info_kosten.setze("Die Jahreskosten werden berechnet, sobald Betrag und "
                                   "Zahlungsintervall eingetragen sind.", TEXT_LEISE)
        elif intervall == "einmalig":
            self.info_kosten.setze(f"Einmalige Zahlung von {formatiere_betrag(kosten)} €", TEXT)
        else:
            jahr = berechne_jahreskosten(kosten, intervall)
            self.info_kosten.setze(f"Hochgerechnet pro Jahr: {formatiere_betrag(jahr)} €", TEXT)

    # ---------- Prüfen ----------

    def _text(self, feld, max_laenge, email=False):
        wert = feld.get()
        if not wert:
            if feld.pflicht:
                feld.zeige_fehler("Pflichtfeld – bitte ausfüllen.")
            return None
        if len(wert) > max_laenge:
            feld.zeige_fehler(f"Höchstens {max_laenge} Zeichen erlaubt (aktuell {len(wert)}).")
            return None
        if email and not EMAIL_MUSTER.match(wert):
            feld.zeige_fehler("Bitte eine gültige E-Mail-Adresse eingeben, z. B. name@firma.de")
            return None
        return wert

    def _auswahl(self, feld, liste):
        wert = feld.get()
        if not wert:
            if feld.pflicht:
                if not self.auswahl.get(liste):
                    feld.zeige_fehler("Noch keine Einträge vorhanden – bitte zuerst in der Verwaltung anlegen.")
                else:
                    feld.zeige_fehler("Bitte einen Eintrag auswählen.")
            return None
        return self.auswahl[liste][wert]

    def _datum(self, feld):
        wert = feld.get()
        if not wert:
            if feld.pflicht:
                feld.zeige_fehler("Pflichtfeld – bitte ein Datum eingeben (TT.MM.JJJJ).")
            return None
        try:
            return lese_datum(wert)
        except ValueError:
            feld.zeige_fehler("Ungültiges Datum. Format: TT.MM.JJJJ, z. B. 31.12.2026")
            return None

    def _ganzzahl(self, feld, minimum=0):
        wert = feld.get()
        if not wert:
            if feld.pflicht:
                feld.zeige_fehler("Pflichtfeld – bitte eine Zahl eingeben.")
            return None
        if not wert.isdigit() or int(wert) < minimum or int(wert) > 99999:
            feld.zeige_fehler(f"Bitte eine ganze Zahl ab {minimum} eingeben.")
            return None
        return int(wert)

    def _betrag(self, feld):
        wert = feld.get()
        if not wert:
            return None
        try:
            betrag = lese_betrag(wert)
        except (InvalidOperation, ValueError):
            feld.zeige_fehler("Ungültiger Betrag. Beispiel: 1.234,56")
            return None
        if betrag < 0 or betrag >= Decimal("10000000000"):
            feld.zeige_fehler("Der Betrag muss zwischen 0 und 9.999.999.999,99 liegen.")
            return None
        return betrag

    def pruefen(self):
        """Prüft alle Felder. Liefert die Daten für die Datenbank oder None bei Fehlern."""
        for feld in self.alle_felder:
            feld.loesche_fehler()
        self.fehlerfelder = []

        vertrag = {
            "vertragsnummer": self._text(self.f_nummer, 50),
            "titel": self._text(self.f_titel, 255),
            "vertragsart": self._text(self.f_art, 100),
            "laufzeit_monate": self._ganzzahl(self.f_laufzeit, minimum=1),
            "id_benutzer": self._auswahl(self.f_verantwortlich, "benutzer"),
            "status": STATUS_ANZEIGE[self.f_status.get()],
            "beschreibung": self.f_beschreibung.get() or None,
            "beginn_datum": self._datum(self.f_beginn),
            "end_datum": None if self.f_unbefristet.get() else self._datum(self.f_ende),
            "kuendigungsfrist_tage": self._ganzzahl(self.f_frist),
            "auto_verlaengerung": bool(self.f_auto.get()),
            "verlaengerung_monate": self._ganzzahl(self.f_monate, minimum=1) if self.f_auto.get() else None,
            "kosten": self._betrag(self.f_kosten),
            "zahlungsintervall": INTERVALL_ANZEIGE.get(self.f_intervall.get()),
        }
        if ABTEILUNGEN_AKTIV:
            vertrag["id_abteilung"] = self._auswahl(self.f_abteilung, "abteilung")

        # Regeln, die mehrere Felder betreffen
        beginn, ende = vertrag["beginn_datum"], vertrag["end_datum"]
        if beginn and ende and ende <= beginn:
            self.f_ende.zeige_fehler("Das Ende muss nach dem Beginn liegen.")
        if self.f_kosten.get() and not self.f_intervall.get():
            self.f_intervall.zeige_fehler("Bitte angeben, wie oft gezahlt wird.")
        if self.f_intervall.get() and not self.f_kosten.get():
            self.f_kosten.zeige_fehler("Bitte den Betrag eingeben.")

        # Vertragspartner
        partner_neu = None
        if self.f_partner_modus.get() == PARTNER_NEU:
            partner_neu = {
                "firmenname": self._text(self.f_firma, 255),
                "strasse": self._text(self.f_strasse, 255),
                "plz": self._text(self.f_plz, 10),
                "ort": self._text(self.f_ort, 100),
                "land": self._text(self.f_land, 100),
                "email": self._text(self.f_p_email, 255, email=True),
                "telefon": self._text(self.f_p_telefon, 50),
            }
        else:
            vertrag["id_vertragspartner"] = self._auswahl(self.f_partner, "vertragspartner")

        ansprechpartner = None
        if self.f_mit_ansprech.get():
            ansprechpartner = {
                "vorname": self._text(self.f_a_vorname, 100),
                "nachname": self._text(self.f_a_nachname, 100),
                "position": self._text(self.f_a_position, 100),
                "email": self._text(self.f_a_email, 255, email=True),
                "telefon": self._text(self.f_a_telefon, 50),
            }

        if self.dokument is not None and not self.dokument.is_file():
            self.status.configure(text="Die gewählte Datei gibt es nicht mehr.", text_color=FEHLER)
            return None

        if self.fehlerfelder:
            return None
        return vertrag, partner_neu, ansprechpartner

    # ---------- Speichern ----------

    def speichern(self):
        self.erfolg.grid_remove()
        ergebnis = self.pruefen()
        if ergebnis is None:
            if self.fehlerfelder:
                anzahl = len(self.fehlerfelder)
                self.status.configure(
                    text=f"Bitte {anzahl} markierte{'s' if anzahl == 1 else ''} Feld"
                         f"{'' if anzahl == 1 else 'er'} prüfen.", text_color=FEHLER)
                self._zeige_feld(self.fehlerfelder[0])
            return
        vertrag, partner_neu, ansprechpartner = ergebnis

        try:
            if self._nummer_vergeben(vertrag["vertragsnummer"]):
                self.f_nummer.zeige_fehler("Diese Vertragsnummer ist schon vergeben.")
                self.status.configure(text="Bitte eine andere Vertragsnummer wählen.", text_color=FEHLER)
                self._zeige_feld(self.f_nummer)
                return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return

        kopie = None
        try:
            if self.dokument is not None:
                kopie = kopiere_dokument(self.dokument, vertrag["vertragsnummer"])

            # Alles oder nichts: Partner, Ansprechpartner, Vertrag und Dokument gemeinsam
            with self.db.transaktion():
                if partner_neu is not None:
                    vertrag["id_vertragspartner"] = self.repos["vertragspartner"].einfuegen(partner_neu)
                if ansprechpartner is not None:
                    ansprechpartner["id_vertragspartner"] = vertrag["id_vertragspartner"]
                    self.repos["ansprechpartner"].einfuegen(ansprechpartner)
                vertrag["id_vertragsart"] = self.repos["vertragsart"].finde_oder_anlegen(
                    vertrag.pop("vertragsart"))
                vertrag["id_laufzeit"] = self.repos["laufzeit"].finde_oder_anlegen(
                    vertrag.pop("laufzeit_monate"))
                id_vertrag = self._schreibe_vertrag(vertrag)
                if kopie is not None:
                    self.repos["dokument"].einfuegen({
                        "id_vertrag": id_vertrag,
                        "id_benutzer": vertrag["id_benutzer"],   # später: angemeldeter Benutzer
                        "dateiname": self.dokument.name[:255],
                        "dateipfad": str(kopie),
                    })
        except (dbapi.Error, OSError) as fehler:
            if kopie is not None and kopie.exists():
                kopie.unlink()                                   # keine verwaisten Dateien
            if "uq_vertrag_vertragsnummer" in str(fehler):
                self.f_nummer.zeige_fehler("Diese Vertragsnummer ist schon vergeben.")
            self.status.configure(text="Nicht gespeichert – es wurden keine Daten übernommen.",
                                  text_color=FEHLER)
            messagebox.showerror("Nicht gespeichert",
                                 "Der Vertrag konnte nicht gespeichert werden. "
                                 f"Es wurden keine Daten übernommen.\n\nDetails: {fehler}")
            return

        zusammenfassung = f"Vertrag {vertrag['vertragsnummer']} „{vertrag['titel']}“ wurde gespeichert."
        if partner_neu is not None:
            zusammenfassung += f"\nNeuer Vertragspartner „{partner_neu['firmenname']}“ wurde angelegt."
        if kopie is not None:
            zusammenfassung += f"\nDokument abgelegt im Ordner „{DOKUMENT_ORDNER.name}“ als {kopie.name}"
        self._nach_speichern(zusammenfassung)

    def _nummer_vergeben(self, vertragsnummer: str) -> bool:
        return self.repos["vertrag"].nummer_vergeben(vertragsnummer)

    def _schreibe_vertrag(self, vertrag: dict) -> int:
        return self.repos["vertrag"].einfuegen(vertrag)

    def _nach_speichern(self, zusammenfassung: str):
        self.lade_auswahllisten()      # neuer Partner erscheint in der Liste
        self.formular_leeren()
        self.erfolg_text.configure(text=zusammenfassung)
        self.erfolg.grid()
        self.status.configure(text="Gespeichert. Sie können den nächsten Vertrag erfassen.",
                              text_color=ERFOLG)
        self._nach_oben()

    # ---------- Formular zurücksetzen ----------

    def zuruecksetzen(self):
        if messagebox.askyesno("Formular zurücksetzen", "Alle Eingaben verwerfen?", parent=self):
            self.erfolg.grid_remove()
            self.formular_leeren()

    def formular_leeren(self):
        for feld in self.alle_felder:
            feld.set("")
            feld.loesche_fehler()
        self.fehlerfelder = []

        try:
            self.f_nummer.set(self.repos["vertrag"].vorschlag_nummer(date.today().year))
        except dbapi.Error:
            pass
        if len(self.auswahl.get("benutzer", {})) == 1:          # nur ein Benutzer -> vorbelegen
            self.f_verantwortlich.set(next(iter(self.auswahl["benutzer"])))
        self.f_land.set("Deutschland")
        self.f_status.set("Aktiv")

        self.f_partner_modus.set(PARTNER_BESTEHEND if self.auswahl.get("vertragspartner") else PARTNER_NEU)
        self._partner_modus_anzeigen()
        self.f_mit_ansprech.deselect()
        self._ansprechpartner_anzeigen()
        self.f_unbefristet.deselect()
        self._unbefristet_geaendert()
        self.f_auto.deselect()
        self._auto_geaendert()
        self._setze_dokument(None)
        self.status.configure(text="")
        self.bei_aenderung()

    # ---------- Hilfen ----------

    def _zeige_feld(self, feld):
        """Scrollt zum Feld und setzt den Cursor hinein."""
        try:
            self.update_idletasks()
            hoehe = self.inhalt.winfo_height()
            abstand = feld.winfo_rooty() - self.inhalt.winfo_rooty()
            if hoehe > 0:
                self.inhalt._parent_canvas.yview_moveto(max(0, (abstand - 60) / hoehe))
        except (AttributeError, tk.TclError):
            pass
        if isinstance(feld, TextFeld):
            feld.eingabe.focus_set()

    def _nach_oben(self):
        try:
            self.inhalt._parent_canvas.yview_moveto(0)
        except AttributeError:
            pass

    def _design_wechseln(self):
        ctk.set_appearance_mode("dark" if self.dunkel.get() else "light")

    def beenden(self):
        self.db.trennen()
        self.destroy()


class VertragErfassen(VertragFormular, ctk.CTk):
    """Eigenständiges Fenster für einen neuen Vertrag."""


class VertragUnterfenster(VertragFormular, ctk.CTkToplevel):
    """Neuer Vertrag als Unterfenster der Vertragsübersicht. Schließt sich nach dem Speichern."""

    MIT_DESIGN_SCHALTER = False

    def __init__(self, db: Datenbankverbindung, bei_gespeichert):
        self.bei_gespeichert = bei_gespeichert
        self.gespeicherte_id = None
        super().__init__(db)
        self.after(150, self.lift)
        self.after(200, self.focus_force)

    def _schreibe_vertrag(self, vertrag: dict) -> int:
        self.gespeicherte_id = super()._schreibe_vertrag(vertrag)
        return self.gespeicherte_id

    def _nach_speichern(self, zusammenfassung: str):
        self.bei_gespeichert(self.gespeicherte_id, zusammenfassung)
        self.destroy()

    def beenden(self):
        self.destroy()           # die Verbindung gehört der Vertragsübersicht


class VertragBearbeiten(VertragUnterfenster):
    """Unterfenster für einen bestehenden Vertrag (geöffnet aus der Vertragsübersicht)."""

    FENSTERTITEL = "Vertrag bearbeiten"
    SPEICHERN_TEXT = "Änderungen speichern"

    def __init__(self, db: Datenbankverbindung, daten: dict, bei_gespeichert):
        self.daten = daten
        self.behalte_benutzer = daten["id_benutzer"]
        vorhanden = DokumentRepository(db).dateinamen_zu_vertrag(daten["id_vertrag"])
        if vorhanden:
            self.dokument_leer_text = "Vorhanden: " + ", ".join(vorhanden)
        super().__init__(db, bei_gespeichert)
        self.f_nummer.setze_hinweis("")

    @staticmethod
    def _text_zu_id(auswahl: dict, id_wert) -> str:
        return next((text for text, wert in auswahl.items() if wert == id_wert), "")

    def formular_leeren(self):
        """Füllt das Formular mit den gespeicherten Werten des Vertrags."""
        super().formular_leeren()
        d = self.daten
        self.f_nummer.set(d["vertragsnummer"])
        self.f_titel.set(d["titel"])
        self.f_art.set(d["vertragsart"])
        self.f_laufzeit.set(d["laufzeit"])
        self.f_verantwortlich.set(self._text_zu_id(self.auswahl["benutzer"], d["id_benutzer"]))
        if self.f_abteilung:
            self.f_abteilung.set(self._text_zu_id(self.auswahl["abteilung"], d["id_abteilung"]))
        self.f_status.set(self._text_zu_id(STATUS_ANZEIGE, d["status"]))
        self.f_beschreibung.set(d["beschreibung"] or "")

        self.f_partner_modus.set(PARTNER_BESTEHEND)
        self._partner_modus_anzeigen()
        self.f_partner.set(self._text_zu_id(self.auswahl["vertragspartner"], d["id_vertragspartner"]))

        self.f_beginn.set(f"{d['beginn_datum']:%d.%m.%Y}")
        if d["end_datum"] is None:
            self.f_unbefristet.select()
            self._unbefristet_geaendert()
        else:
            self.f_ende.set(f"{d['end_datum']:%d.%m.%Y}")
        if d["kuendigungsfrist_tage"] is not None:
            self.f_frist.set(str(d["kuendigungsfrist_tage"]))
        if d["auto_verlaengerung"]:
            self.f_auto.select()
            self._auto_geaendert()
            if d["verlaengerung_monate"] is not None:
                self.f_monate.set(str(d["verlaengerung_monate"]))

        if d["kosten"] is not None:
            self.f_kosten.set(formatiere_betrag(d["kosten"]))
        self.f_intervall.set(self._text_zu_id(INTERVALL_ANZEIGE, d["zahlungsintervall"]))
        self.bei_aenderung()

    def _nummer_vergeben(self, vertragsnummer: str) -> bool:
        return self.repos["vertrag"].nummer_vergeben(vertragsnummer, ausser_id=self.daten["id_vertrag"])

    def _schreibe_vertrag(self, vertrag: dict) -> int:
        id_vertrag = self.daten["id_vertrag"]
        if self.repos["vertrag"].aktualisieren(id_vertrag, vertrag) == 0:
            raise dbapi.Error("Diesen Vertrag gibt es nicht mehr.")
        self.gespeicherte_id = id_vertrag
        return id_vertrag


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
    VertragErfassen(db).mainloop()


if __name__ == "__main__":
    main()

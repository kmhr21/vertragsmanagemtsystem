"""
Vertragsverwaltung - einfache Tkinter-GUI (Testversion)

Ein Fenster mit Reitern (Tabs). Jede Tabelle bekommt einen eigenen Reiter.
Bisher:
    Reiter "Rollen"   -> Tabelle rolle   anzeigen, einfuegen, aktualisieren, loeschen
    Reiter "Benutzer" -> Tabelle benutzer anzeigen, einfuegen, aktualisieren, loeschen
    Reiter "Abteilungen" -> Tabelle abteilung anzeigen, einfuegen, aktualisieren, loeschen

Aufbau (wie im Klassendiagramm, vorerst alles in einer Datei):
    Datenbankverbindung  -> Verbindung und SQL ausfuehren
    RolleRepository      -> SQL fuer die Tabelle rolle
    BenutzerRepository   -> SQL fuer die Tabelle benutzer
    weitere Repositories -> SQL fuer die Vertragstabellen (genutzt von vertrag_erfassen.py)
    RollenReiter         -> Oberflaeche fuer rolle
    BenutzerReiter       -> Oberflaeche fuer benutzer
    Hauptfenster         -> Fenster mit den Reitern

Benoetigt:
    PostgreSQL: pip install "psycopg[binary]"
    MySQL:      pip install mysql-connector-python
Tkinter ist bei Python unter Windows bereits dabei.
"""

import hashlib
import hmac
import os
import re
import tkinter as tk
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from tkinter import ttk, messagebox


# =====================================================
# KONFIGURATION - hier anpassen
# =====================================================

DB_TYPE = "postgres"       # "mysql" oder "postgres"

ABTEILUNGEN_AKTIV = True   # departments feature on/off

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,          # MySQL: 3306, PostgreSQL: 5432
    "user": "postgres",    # spaeter: eigener Benutzer mit weniger Rechten (z. B. vm_app)
    "password": "root",
    "database": "vertragsverwaltung",   # Name deiner Datenbank in pgAdmin
}

if DB_TYPE == "mysql":
    import mysql.connector as dbapi
else:
    import psycopg as dbapi


# =====================================================
# PASSWORT-HASHING (nur Python-Standardbibliothek)
# =====================================================

ITERATIONEN = 200_000


def hash_passwort(passwort: str) -> str:
    """Erzeugt einen sicheren Hash mit zufaelligem Salt (PBKDF2-SHA256)."""
    salt = os.urandom(16)
    hash_wert = hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salt, ITERATIONEN)
    return f"pbkdf2_sha256${ITERATIONEN}${salt.hex()}${hash_wert.hex()}"


def pruefe_passwort(passwort: str, gespeicherter_hash: str) -> bool:
    """Prueft ein Passwort gegen einen gespeicherten Hash (fuer den spaeteren Login)."""
    try:
        _, iterationen, salt_hex, hash_hex = gespeicherter_hash.split("$")
    except ValueError:
        return False
    neu = hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"),
                              bytes.fromhex(salt_hex), int(iterationen))
    return hmac.compare_digest(neu.hex(), hash_hex)


# =====================================================
# EINGABEN LESEN UND FORMATIEREN
# =====================================================

def lese_datum(text: str) -> date:
    """TT.MM.JJJJ -> date. Wirft ValueError bei ungueltiger oder leerer Eingabe."""
    return datetime.strptime(text.strip(), "%d.%m.%Y").date()


def lese_betrag(text: str) -> Decimal:
    """1.234,56 / 1234,56 / 1234.56 -> Decimal. Wirft ValueError bei ungueltiger Eingabe."""
    wert = text.strip()
    if "," in wert:
        wert = wert.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", wert):   # 1.234 = Tausenderpunkt
        wert = wert.replace(".", "")
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", wert):
        raise ValueError(f"Ungueltiger Betrag: {text}")
    return Decimal(wert)


def formatiere_betrag(betrag: Decimal) -> str:
    """Decimal -> 1.234,56"""
    return f"{betrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# =====================================================
# DATENBANKVERBINDUNG
# =====================================================

class Datenbankverbindung:
    def __init__(self, config: dict, db_type: str):
        self.__config = config
        self.__db_type = db_type
        self.__verbindung = None
        self.__in_transaktion = False

    def verbinden(self):
        c = self.__config
        if self.__db_type == "mysql":
            self.__verbindung = dbapi.connect(
                host=c["host"], port=c["port"], user=c["user"],
                password=c["password"], database=c["database"])
        else:
            self.__verbindung = dbapi.connect(
                host=c["host"], port=c["port"], user=c["user"],
                password=c["password"], dbname=c["database"])

    def trennen(self):
        if self.__verbindung is not None:
            self.__verbindung.close()
            self.__verbindung = None

    @contextmanager
    def transaktion(self):
        """Alles oder nichts: Innerhalb von 'with db.transaktion():' wird erst am Ende
        gespeichert. Bei einem Fehler werden alle Aenderungen zurueckgenommen."""
        self.__in_transaktion = True
        try:
            yield
            self.__verbindung.commit()
        except Exception:
            self.__verbindung.rollback()
            raise
        finally:
            self.__in_transaktion = False

    def __bestaetigen(self):
        if not self.__in_transaktion:
            self.__verbindung.commit()

    def __zuruecknehmen(self):
        if not self.__in_transaktion:
            self.__verbindung.rollback()

    def abfragen(self, sql: str, parameter: tuple = ()) -> list:
        """Fuer SELECT: liefert alle Zeilen als Liste von Tupeln."""
        cursor = self.__verbindung.cursor()
        try:
            cursor.execute(sql, parameter)
            zeilen = cursor.fetchall()
            self.__bestaetigen()   # Lese-Transaktion beenden -> immer aktuelle Daten
            return zeilen
        except Exception:
            self.__zuruecknehmen()
            raise
        finally:
            cursor.close()

    def abfragen_als_dict(self, sql: str, parameter: tuple = ()) -> list:
        """Fuer SELECT: liefert alle Zeilen als Liste von Dicts {spalte: wert}."""
        cursor = self.__verbindung.cursor()
        try:
            cursor.execute(sql, parameter)
            spalten = [beschreibung[0] for beschreibung in cursor.description]
            zeilen = [dict(zip(spalten, zeile)) for zeile in cursor.fetchall()]
            self.__bestaetigen()
            return zeilen
        except Exception:
            self.__zuruecknehmen()
            raise
        finally:
            cursor.close()

    def ausfuehren(self, sql: str, parameter: tuple = ()) -> int:
        """Fuer UPDATE/DELETE: liefert die Anzahl betroffener Zeilen."""
        cursor = self.__verbindung.cursor()
        try:
            cursor.execute(sql, parameter)
            anzahl = cursor.rowcount
            self.__bestaetigen()
            return anzahl
        except Exception:
            self.__zuruecknehmen()
            raise
        finally:
            cursor.close()

    def einfuegen(self, sql: str, parameter: tuple, id_spalte: str) -> int:
        """Fuer INSERT: liefert die neue ID (AUTO_INCREMENT / IDENTITY)."""
        if self.__db_type == "postgres":
            sql += f" RETURNING {id_spalte}"
        cursor = self.__verbindung.cursor()
        try:
            cursor.execute(sql, parameter)
            if self.__db_type == "postgres":
                neue_id = cursor.fetchone()[0]
            else:
                neue_id = cursor.lastrowid
            self.__bestaetigen()
            return neue_id
        except Exception:
            self.__zuruecknehmen()
            raise
        finally:
            cursor.close()


# =====================================================
# REPOSITORIES (SQL pro Tabelle)
# =====================================================

class RolleRepository:
    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def finde_alle(self) -> list:
        return self.__db.abfragen(
            "SELECT id_rolle, bezeichnung FROM rolle ORDER BY id_rolle")

    def einfuegen(self, bezeichnung: str) -> int:
        return self.__db.einfuegen(
            "INSERT INTO rolle (bezeichnung) VALUES (%s)", (bezeichnung,), "id_rolle")

    def aktualisieren(self, id_rolle: int, bezeichnung: str) -> int:
        return self.__db.ausfuehren(
            "UPDATE rolle SET bezeichnung = %s WHERE id_rolle = %s", (bezeichnung, id_rolle))

    def loeschen(self, id_rolle: int) -> int:
        return self.__db.ausfuehren(
            "DELETE FROM rolle WHERE id_rolle = %s", (id_rolle,))


class BenutzerRepository:
    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def finde_alle(self) -> list:
        sql = """
            SELECT b.id_benutzer, b.id_rolle, r.bezeichnung, b.benutzername,
                   b.vorname, b.nachname, b.email, b.aktiv, b.erstellt_am
            FROM   benutzer b
            JOIN   rolle r ON b.id_rolle = r.id_rolle
            ORDER  BY b.id_benutzer
        """
        return self.__db.abfragen(sql)

    def finde_alle_als_dict(self) -> list:
        return self.__db.abfragen_als_dict(
            "SELECT id_benutzer, vorname, nachname, aktiv FROM benutzer ORDER BY nachname, vorname")

    def einfuegen(self, daten: dict, passwort: str) -> int:
        sql = """
            INSERT INTO benutzer
                (id_rolle, benutzername, passwort_hash, vorname, nachname, email, aktiv)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        parameter = (daten["id_rolle"], daten["benutzername"], hash_passwort(passwort),
                     daten["vorname"], daten["nachname"], daten["email"], daten["aktiv"])
        return self.__db.einfuegen(sql, parameter, "id_benutzer")

    def aktualisieren(self, id_benutzer: int, daten: dict, neues_passwort: str = "") -> int:
        if neues_passwort:
            sql = """
                UPDATE benutzer
                SET id_rolle = %s, benutzername = %s, vorname = %s, nachname = %s,
                    email = %s, aktiv = %s, passwort_hash = %s
                WHERE id_benutzer = %s
            """
            parameter = (daten["id_rolle"], daten["benutzername"], daten["vorname"],
                         daten["nachname"], daten["email"], daten["aktiv"],
                         hash_passwort(neues_passwort), id_benutzer)
        else:
            sql = """
                UPDATE benutzer
                SET id_rolle = %s, benutzername = %s, vorname = %s, nachname = %s,
                    email = %s, aktiv = %s
                WHERE id_benutzer = %s
            """
            parameter = (daten["id_rolle"], daten["benutzername"], daten["vorname"],
                         daten["nachname"], daten["email"], daten["aktiv"], id_benutzer)
        return self.__db.ausfuehren(sql, parameter)

    def loeschen(self, id_benutzer: int) -> int:
        return self.__db.ausfuehren(
            "DELETE FROM benutzer WHERE id_benutzer = %s", (id_benutzer,))


class VertragsartRepository:
    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def finde_oder_anlegen(self, bezeichnung: str) -> int:
        """Liefert die ID zur Vertragsart (ohne Gross-/Kleinschreibung), legt sie bei Bedarf an."""
        zeilen = self.__db.abfragen(
            "SELECT id_vertragsart FROM vertragsart WHERE LOWER(bezeichnung) = LOWER(%s)",
            (bezeichnung,))
        if zeilen:
            return zeilen[0][0]
        return self.__db.einfuegen(
            "INSERT INTO vertragsart (bezeichnung) VALUES (%s)", (bezeichnung,), "id_vertragsart")


class LaufzeitRepository:
    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def finde_oder_anlegen(self, monate: int) -> int:
        """Liefert die ID zur Laufzeit in Monaten, die Zeile wird bei Bedarf angelegt."""
        zeilen = self.__db.abfragen(
            "SELECT id_laufzeit FROM laufzeit WHERE bezeichnung = %s", (str(monate),))
        if zeilen:
            return zeilen[0][0]
        return self.__db.einfuegen(
            "INSERT INTO laufzeit (bezeichnung) VALUES (%s)", (str(monate),), "id_laufzeit")


class AbteilungRepository:
    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def finde_alle(self) -> list:
        return self.__db.abfragen_als_dict(
            "SELECT id_abteilung, bezeichnung, kostenstelle FROM abteilung ORDER BY bezeichnung")

    def einfuegen(self, bezeichnung: str, kostenstelle) -> int:
        return self.__db.einfuegen(
            "INSERT INTO abteilung (bezeichnung, kostenstelle) VALUES (%s, %s)",
            (bezeichnung, kostenstelle), "id_abteilung")

    def aktualisieren(self, id_abteilung: int, bezeichnung: str, kostenstelle) -> int:
        return self.__db.ausfuehren(
            "UPDATE abteilung SET bezeichnung = %s, kostenstelle = %s WHERE id_abteilung = %s",
            (bezeichnung, kostenstelle, id_abteilung))

    def loeschen(self, id_abteilung: int) -> int:
        return self.__db.ausfuehren(
            "DELETE FROM abteilung WHERE id_abteilung = %s", (id_abteilung,))


class VertragspartnerRepository:
    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def finde_alle(self) -> list:
        return self.__db.abfragen_als_dict(
            "SELECT id_vertragspartner, firmenname, ort FROM vertragspartner ORDER BY firmenname")

    def einfuegen(self, daten: dict) -> int:
        sql = """
            INSERT INTO vertragspartner (firmenname, strasse, plz, ort, land, email, telefon)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        parameter = (daten["firmenname"], daten["strasse"], daten["plz"], daten["ort"],
                     daten["land"], daten["email"], daten["telefon"])
        return self.__db.einfuegen(sql, parameter, "id_vertragspartner")


class AnsprechpartnerRepository:
    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def einfuegen(self, daten: dict) -> int:
        sql = """
            INSERT INTO ansprechpartner
                (id_vertragspartner, vorname, nachname, position, email, telefon)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        parameter = (daten["id_vertragspartner"], daten["vorname"], daten["nachname"],
                     daten["position"], daten["email"], daten["telefon"])
        return self.__db.einfuegen(sql, parameter, "id_ansprechpartner")


class VertragRepository:
    SPALTEN = ("id_vertragspartner", "id_benutzer", "id_vertragsart", "id_laufzeit", "id_abteilung",
               "vertragsnummer", "titel", "beschreibung", "beginn_datum", "end_datum",
               "kuendigungsfrist_tage", "auto_verlaengerung", "verlaengerung_monate",
               "kosten", "zahlungsintervall", "status")

    SQL_MIT_NAMEN = """
        SELECT v.*, p.firmenname, a.bezeichnung AS vertragsart, l.bezeichnung AS laufzeit,
               ab.bezeichnung AS abteilung, b.vorname, b.nachname
        FROM   vertrag v
        JOIN   vertragspartner p ON v.id_vertragspartner = p.id_vertragspartner
        JOIN   vertragsart a     ON v.id_vertragsart = a.id_vertragsart
        JOIN   laufzeit l        ON v.id_laufzeit = l.id_laufzeit
        JOIN   abteilung ab      ON v.id_abteilung = ab.id_abteilung
        JOIN   benutzer b        ON v.id_benutzer = b.id_benutzer
    """

    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def finde_alle(self) -> list:
        return self.__db.abfragen_als_dict(self.SQL_MIT_NAMEN + " ORDER BY v.id_vertrag DESC")

    def finde_nach_id(self, id_vertrag: int):
        """Liefert den Vertrag als Dict oder None, wenn es ihn nicht mehr gibt."""
        zeilen = self.__db.abfragen_als_dict(
            self.SQL_MIT_NAMEN + " WHERE v.id_vertrag = %s", (id_vertrag,))
        return zeilen[0] if zeilen else None

    def nummer_vergeben(self, vertragsnummer: str, ausser_id: int = None) -> bool:
        """ausser_id: Beim Bearbeiten darf ein Vertrag seine eigene Nummer behalten."""
        return bool(self.__db.abfragen(
            "SELECT 1 FROM vertrag WHERE vertragsnummer = %s AND id_vertrag <> %s",
            (vertragsnummer, -1 if ausser_id is None else ausser_id)))

    def vorschlag_nummer(self, jahr: int) -> str:
        """Naechste freie Nummer des Jahres, z. B. V-2026-001."""
        zeilen = self.__db.abfragen(
            "SELECT vertragsnummer FROM vertrag WHERE vertragsnummer LIKE %s", (f"V-{jahr}-%",))
        hoechste = 0
        for (nummer,) in zeilen:
            treffer = re.fullmatch(rf"V-{jahr}-(\d+)", nummer)
            if treffer:
                hoechste = max(hoechste, int(treffer.group(1)))
        return f"V-{jahr}-{hoechste + 1:03d}"

    def einfuegen(self, daten: dict) -> int:
        spalten = [spalte for spalte in self.SPALTEN if spalte in daten]
        sql = (f"INSERT INTO vertrag ({', '.join(spalten)}) "
               f"VALUES ({', '.join(['%s'] * len(spalten))})")
        return self.__db.einfuegen(sql, tuple(daten[spalte] for spalte in spalten), "id_vertrag")

    def aktualisieren(self, id_vertrag: int, daten: dict) -> int:
        spalten = [spalte for spalte in self.SPALTEN if spalte in daten]
        zuweisungen = ", ".join(f"{spalte} = %s" for spalte in spalten)
        sql = (f"UPDATE vertrag SET {zuweisungen}, geaendert_am = CURRENT_TIMESTAMP "
               "WHERE id_vertrag = %s")
        return self.__db.ausfuehren(sql, tuple(daten[spalte] for spalte in spalten) + (id_vertrag,))


class DokumentRepository:
    def __init__(self, db: Datenbankverbindung):
        self.__db = db

    def einfuegen(self, daten: dict) -> int:
        sql = """
            INSERT INTO dokument (id_vertrag, id_benutzer, dateiname, dateipfad)
            VALUES (%s, %s, %s, %s)
        """
        parameter = (daten["id_vertrag"], daten["id_benutzer"], daten["dateiname"], daten["dateipfad"])
        return self.__db.einfuegen(sql, parameter, "id_dokument")

    def dateinamen_zu_vertrag(self, id_vertrag: int) -> list:
        zeilen = self.__db.abfragen(
            "SELECT dateiname FROM dokument WHERE id_vertrag = %s ORDER BY id_dokument", (id_vertrag,))
        return [zeile[0] for zeile in zeilen]


# =====================================================
# REITER "ROLLEN"
# =====================================================

class RollenReiter(ttk.Frame):
    def __init__(self, eltern, repo: RolleRepository):
        super().__init__(eltern)
        self.repo = repo

        self._baue_tabelle()
        self._baue_formular()
        self._baue_buttons()
        self.lade_rollen()

    # ---------- Aufbau ----------

    def _baue_tabelle(self):
        rahmen = ttk.Frame(self, padding=10)
        rahmen.pack(fill="both", expand=True)

        self.tabelle = ttk.Treeview(rahmen, columns=("id", "bezeichnung"),
                                    show="headings", height=12)
        self.tabelle.heading("id", text="ID")
        self.tabelle.heading("bezeichnung", text="Bezeichnung")
        self.tabelle.column("id", width=60)
        self.tabelle.column("bezeichnung", width=300)

        scroll = ttk.Scrollbar(rahmen, orient="vertical", command=self.tabelle.yview)
        self.tabelle.configure(yscrollcommand=scroll.set)
        self.tabelle.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tabelle.bind("<<TreeviewSelect>>", self.zeile_gewaehlt)

    def _baue_formular(self):
        rahmen = ttk.LabelFrame(self, text="Rolle bearbeiten", padding=10)
        rahmen.pack(fill="x", padx=10)

        self.var_id = tk.StringVar()
        self.var_bezeichnung = tk.StringVar()

        ttk.Label(rahmen, text="ID:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(rahmen, textvariable=self.var_id).grid(row=0, column=1, sticky="w")

        ttk.Label(rahmen, text="Bezeichnung *:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(rahmen, textvariable=self.var_bezeichnung, width=40).grid(row=1, column=1, sticky="w")

    def _baue_buttons(self):
        rahmen = ttk.Frame(self, padding=10)
        rahmen.pack(fill="x")
        ttk.Button(rahmen, text="Neu (Formular leeren)", command=self.formular_leeren).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Einfuegen", command=self.einfuegen).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Aktualisieren", command=self.aktualisieren).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Loeschen", command=self.loeschen).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Liste neu laden", command=self.lade_rollen).pack(side="right", padx=5)

    # ---------- Daten ----------

    def lade_rollen(self):
        try:
            zeilen = self.repo.finde_alle()
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", f"Rollen konnten nicht geladen werden:\n{fehler}")
            return
        self.tabelle.delete(*self.tabelle.get_children())
        for id_rolle, bezeichnung in zeilen:
            self.tabelle.insert("", "end", iid=str(id_rolle), values=(id_rolle, bezeichnung))

    def zeile_gewaehlt(self, _event=None):
        auswahl = self.tabelle.selection()
        if not auswahl:
            return
        id_rolle, bezeichnung = self.tabelle.item(auswahl[0], "values")
        self.var_id.set(id_rolle)
        self.var_bezeichnung.set(bezeichnung)

    def formular_leeren(self):
        self.tabelle.selection_remove(self.tabelle.selection())
        self.var_id.set("")
        self.var_bezeichnung.set("")

    def bezeichnung_lesen(self):
        bezeichnung = self.var_bezeichnung.get().strip()
        if not bezeichnung:
            messagebox.showwarning("Eingabe fehlt", "Bitte eine Bezeichnung eingeben.")
            return None
        if len(bezeichnung) > 50:
            messagebox.showwarning("Zu lang", "Die Bezeichnung darf maximal 50 Zeichen haben.")
            return None
        return bezeichnung

    # ---------- Aktionen ----------

    def einfuegen(self):
        if self.var_id.get():
            messagebox.showinfo("Hinweis", "Es ist eine bestehende Rolle ausgewaehlt.\n"
                                           "Fuer eine neue Rolle zuerst 'Neu' klicken.")
            return
        bezeichnung = self.bezeichnung_lesen()
        if bezeichnung is None:
            return
        try:
            neue_id = self.repo.einfuegen(bezeichnung)
        except dbapi.IntegrityError:
            messagebox.showerror("Nicht gespeichert", f"Die Rolle '{bezeichnung}' existiert bereits.")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.lade_rollen()
        self.tabelle.selection_set(str(neue_id))
        messagebox.showinfo("Gespeichert", f"Rolle mit ID {neue_id} wurde angelegt.")

    def aktualisieren(self):
        if not self.var_id.get():
            messagebox.showwarning("Keine Auswahl", "Bitte zuerst eine Rolle in der Liste auswaehlen.")
            return
        bezeichnung = self.bezeichnung_lesen()
        if bezeichnung is None:
            return
        id_rolle = int(self.var_id.get())
        try:
            self.repo.aktualisieren(id_rolle, bezeichnung)
        except dbapi.IntegrityError:
            messagebox.showerror("Nicht gespeichert", f"Die Rolle '{bezeichnung}' existiert bereits.")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.lade_rollen()
        self.tabelle.selection_set(str(id_rolle))
        messagebox.showinfo("Gespeichert", "Rolle wurde aktualisiert.")

    def loeschen(self):
        if not self.var_id.get():
            messagebox.showwarning("Keine Auswahl", "Bitte zuerst eine Rolle in der Liste auswaehlen.")
            return
        id_rolle = int(self.var_id.get())
        bezeichnung = self.var_bezeichnung.get()
        if not messagebox.askyesno("Loeschen bestaetigen",
                                   f"Rolle '{bezeichnung}' (ID {id_rolle}) wirklich loeschen?"):
            return
        try:
            self.repo.loeschen(id_rolle)
        except dbapi.IntegrityError:
            messagebox.showerror("Loeschen nicht moeglich",
                                 "Diese Rolle ist noch Benutzern zugewiesen.\n\n"
                                 "Bitte den Benutzern zuerst eine andere Rolle geben.")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.formular_leeren()
        self.lade_rollen()


# =====================================================
# REITER "BENUTZER"
# =====================================================

class BenutzerReiter(ttk.Frame):
    def __init__(self, eltern, repo: BenutzerRepository, rollen_repo: RolleRepository):
        super().__init__(eltern)
        self.repo = repo
        self.rollen_repo = rollen_repo
        self.rollen = {}            # bezeichnung -> id_rolle
        self.benutzer_daten = {}    # id_benutzer -> Datenbankzeile

        self._baue_tabelle()
        self._baue_formular()
        self._baue_buttons()

        self.lade_rollen()
        self.lade_benutzer()

    # ---------- Aufbau ----------

    def _baue_tabelle(self):
        rahmen = ttk.Frame(self, padding=10)
        rahmen.pack(fill="both", expand=True)

        spalten = [("id", "ID", 50), ("rolle", "Rolle", 110), ("benutzername", "Benutzername", 130),
                   ("vorname", "Vorname", 120), ("nachname", "Nachname", 120),
                   ("email", "E-Mail", 220), ("aktiv", "Aktiv", 60), ("erstellt", "Erstellt am", 140)]

        self.tabelle = ttk.Treeview(rahmen, columns=[s[0] for s in spalten],
                                    show="headings", height=12)
        for schluessel, titel, breite in spalten:
            self.tabelle.heading(schluessel, text=titel)
            self.tabelle.column(schluessel, width=breite)

        scroll = ttk.Scrollbar(rahmen, orient="vertical", command=self.tabelle.yview)
        self.tabelle.configure(yscrollcommand=scroll.set)
        self.tabelle.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tabelle.bind("<<TreeviewSelect>>", self.zeile_gewaehlt)

    def _baue_formular(self):
        rahmen = ttk.LabelFrame(self, text="Benutzer bearbeiten", padding=10)
        rahmen.pack(fill="x", padx=10)

        self.var_id = tk.StringVar()
        self.var_rolle = tk.StringVar()
        self.var_benutzername = tk.StringVar()
        self.var_passwort = tk.StringVar()
        self.var_vorname = tk.StringVar()
        self.var_nachname = tk.StringVar()
        self.var_email = tk.StringVar()
        self.var_aktiv = tk.BooleanVar(value=True)

        # Linke Spalte
        ttk.Label(rahmen, text="ID:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(rahmen, textvariable=self.var_id).grid(row=0, column=1, sticky="w")

        ttk.Label(rahmen, text="Rolle *:").grid(row=1, column=0, sticky="w", pady=2)
        self.combo_rolle = ttk.Combobox(rahmen, textvariable=self.var_rolle,
                                        state="readonly", width=27)
        self.combo_rolle.grid(row=1, column=1, sticky="w")

        ttk.Label(rahmen, text="Benutzername *:").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(rahmen, textvariable=self.var_benutzername, width=30).grid(row=2, column=1, sticky="w")

        ttk.Label(rahmen, text="Passwort:").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Entry(rahmen, textvariable=self.var_passwort, show="*", width=30).grid(row=3, column=1, sticky="w")
        ttk.Label(rahmen, text="(Pflicht bei Neuanlage, beim Aktualisieren leer = unveraendert)",
                  foreground="gray").grid(row=4, column=0, columnspan=2, sticky="w")

        # Rechte Spalte
        ttk.Label(rahmen, text="Vorname *:").grid(row=1, column=2, sticky="w", padx=(30, 0))
        ttk.Entry(rahmen, textvariable=self.var_vorname, width=30).grid(row=1, column=3, sticky="w")

        ttk.Label(rahmen, text="Nachname *:").grid(row=2, column=2, sticky="w", padx=(30, 0))
        ttk.Entry(rahmen, textvariable=self.var_nachname, width=30).grid(row=2, column=3, sticky="w")

        ttk.Label(rahmen, text="E-Mail *:").grid(row=3, column=2, sticky="w", padx=(30, 0))
        ttk.Entry(rahmen, textvariable=self.var_email, width=30).grid(row=3, column=3, sticky="w")

        ttk.Checkbutton(rahmen, text="Aktiv", variable=self.var_aktiv).grid(
            row=4, column=3, sticky="w")

    def _baue_buttons(self):
        rahmen = ttk.Frame(self, padding=10)
        rahmen.pack(fill="x")
        ttk.Button(rahmen, text="Neu (Formular leeren)", command=self.formular_leeren).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Einfuegen", command=self.einfuegen).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Aktualisieren", command=self.aktualisieren).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Loeschen", command=self.loeschen).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Liste neu laden", command=self.neu_laden).pack(side="right", padx=5)

    # ---------- Daten laden ----------

    def neu_laden(self):
        """Wird auch beim Wechsel auf diesen Reiter aufgerufen."""
        self.lade_rollen()
        self.lade_benutzer()

    def lade_rollen(self):
        try:
            zeilen = self.rollen_repo.finde_alle()
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", f"Rollen konnten nicht geladen werden:\n{fehler}")
            return
        self.rollen = {bezeichnung: id_rolle for id_rolle, bezeichnung in zeilen}
        self.combo_rolle["values"] = list(self.rollen.keys())

    def lade_benutzer(self):
        try:
            zeilen = self.repo.finde_alle()
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", f"Benutzer konnten nicht geladen werden:\n{fehler}")
            return

        self.tabelle.delete(*self.tabelle.get_children())
        self.benutzer_daten.clear()
        for zeile in zeilen:
            (id_benutzer, _id_rolle, rolle, benutzername, vorname,
             nachname, email, aktiv, erstellt_am) = zeile
            self.benutzer_daten[id_benutzer] = zeile
            erstellt_text = erstellt_am.strftime("%d.%m.%Y %H:%M") if erstellt_am else ""
            self.tabelle.insert("", "end", iid=str(id_benutzer), values=(
                id_benutzer, rolle, benutzername, vorname, nachname, email,
                "ja" if aktiv else "nein", erstellt_text))

    # ---------- Formular ----------

    def zeile_gewaehlt(self, _event=None):
        auswahl = self.tabelle.selection()
        if not auswahl:
            return
        zeile = self.benutzer_daten[int(auswahl[0])]
        (id_benutzer, _id_rolle, rolle, benutzername, vorname,
         nachname, email, aktiv, _erstellt) = zeile
        self.var_id.set(str(id_benutzer))
        self.var_rolle.set(rolle)
        self.var_benutzername.set(benutzername)
        self.var_passwort.set("")
        self.var_vorname.set(vorname)
        self.var_nachname.set(nachname)
        self.var_email.set(email)
        self.var_aktiv.set(bool(aktiv))

    def formular_leeren(self):
        self.tabelle.selection_remove(self.tabelle.selection())
        for var in (self.var_id, self.var_rolle, self.var_benutzername, self.var_passwort,
                    self.var_vorname, self.var_nachname, self.var_email):
            var.set("")
        self.var_aktiv.set(True)

    def formular_lesen(self, passwort_pflicht: bool):
        """Liest und prueft das Formular. Gibt (daten, passwort) zurueck oder None bei Fehler."""
        rolle = self.var_rolle.get()
        daten = {
            "id_rolle": self.rollen.get(rolle),
            "benutzername": self.var_benutzername.get().strip(),
            "vorname": self.var_vorname.get().strip(),
            "nachname": self.var_nachname.get().strip(),
            "email": self.var_email.get().strip(),
            "aktiv": self.var_aktiv.get(),
        }
        passwort = self.var_passwort.get()

        if daten["id_rolle"] is None:
            messagebox.showwarning("Eingabe fehlt", "Bitte eine Rolle auswaehlen.\n"
                                                    "(Keine da? Zuerst im Reiter 'Rollen' anlegen.)")
            return None
        if not all([daten["benutzername"], daten["vorname"], daten["nachname"], daten["email"]]):
            messagebox.showwarning("Eingabe fehlt", "Bitte alle Pflichtfelder (*) ausfuellen.")
            return None
        if "@" not in daten["email"]:
            messagebox.showwarning("Ungueltige Eingabe", "Bitte eine gueltige E-Mail-Adresse eingeben.")
            return None
        if passwort_pflicht and not passwort:
            messagebox.showwarning("Eingabe fehlt", "Bei einem neuen Benutzer ist ein Passwort Pflicht.")
            return None
        return daten, passwort

    # ---------- Aktionen ----------

    def einfuegen(self):
        if self.var_id.get():
            messagebox.showinfo("Hinweis", "Es ist ein bestehender Benutzer ausgewaehlt.\n"
                                           "Fuer einen neuen Benutzer zuerst 'Neu' klicken.")
            return
        ergebnis = self.formular_lesen(passwort_pflicht=True)
        if ergebnis is None:
            return
        daten, passwort = ergebnis
        try:
            neue_id = self.repo.einfuegen(daten, passwort)
        except dbapi.IntegrityError as fehler:
            messagebox.showerror("Nicht gespeichert",
                                 f"Benutzername oder E-Mail existiert bereits.\n\nDetails: {fehler}")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.lade_benutzer()
        self.tabelle.selection_set(str(neue_id))
        messagebox.showinfo("Gespeichert", f"Benutzer mit ID {neue_id} wurde angelegt.")

    def aktualisieren(self):
        if not self.var_id.get():
            messagebox.showwarning("Keine Auswahl", "Bitte zuerst einen Benutzer in der Liste auswaehlen.")
            return
        ergebnis = self.formular_lesen(passwort_pflicht=False)
        if ergebnis is None:
            return
        daten, passwort = ergebnis
        id_benutzer = int(self.var_id.get())
        try:
            self.repo.aktualisieren(id_benutzer, daten, passwort)
        except dbapi.IntegrityError as fehler:
            messagebox.showerror("Nicht gespeichert",
                                 f"Benutzername oder E-Mail existiert bereits.\n\nDetails: {fehler}")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.lade_benutzer()
        self.tabelle.selection_set(str(id_benutzer))
        messagebox.showinfo("Gespeichert", "Benutzer wurde aktualisiert.")

    def loeschen(self):
        if not self.var_id.get():
            messagebox.showwarning("Keine Auswahl", "Bitte zuerst einen Benutzer in der Liste auswaehlen.")
            return
        id_benutzer = int(self.var_id.get())
        name = self.var_benutzername.get()
        if not messagebox.askyesno("Loeschen bestaetigen",
                                   f"Benutzer '{name}' (ID {id_benutzer}) wirklich loeschen?"):
            return
        try:
            self.repo.loeschen(id_benutzer)
        except dbapi.IntegrityError:
            messagebox.showerror(
                "Loeschen nicht moeglich",
                "Dieser Benutzer wird noch verwendet (z. B. als Verantwortlicher eines Vertrags "
                "oder beim Upload eines Dokuments).\n\n"
                "Tipp: Haken bei 'Aktiv' entfernen und 'Aktualisieren' klicken.")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.formular_leeren()
        self.lade_benutzer()


# =====================================================
# REITER "ABTEILUNGEN"
# =====================================================

class AbteilungenReiter(ttk.Frame):
    def __init__(self, eltern, repo: AbteilungRepository):
        super().__init__(eltern)
        self.repo = repo
        self.zeilen = {}    # id -> Zeile (Treeview wuerde z. B. "0100" zu 100 umwandeln)

        self._baue_tabelle()
        self._baue_formular()
        self._baue_buttons()
        self.lade_abteilungen()

    # ---------- Aufbau ----------

    def _baue_tabelle(self):
        rahmen = ttk.Frame(self, padding=10)
        rahmen.pack(fill="both", expand=True)

        self.tabelle = ttk.Treeview(rahmen, columns=("id", "bezeichnung", "kostenstelle"),
                                    show="headings", height=12)
        self.tabelle.heading("id", text="ID")
        self.tabelle.heading("bezeichnung", text="Bezeichnung")
        self.tabelle.heading("kostenstelle", text="Kostenstelle")
        self.tabelle.column("id", width=60)
        self.tabelle.column("bezeichnung", width=300)
        self.tabelle.column("kostenstelle", width=120)

        scroll = ttk.Scrollbar(rahmen, orient="vertical", command=self.tabelle.yview)
        self.tabelle.configure(yscrollcommand=scroll.set)
        self.tabelle.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tabelle.bind("<<TreeviewSelect>>", self.zeile_gewaehlt)

    def _baue_formular(self):
        rahmen = ttk.LabelFrame(self, text="Abteilung bearbeiten", padding=10)
        rahmen.pack(fill="x", padx=10)

        self.var_id = tk.StringVar()
        self.var_bezeichnung = tk.StringVar()
        self.var_kostenstelle = tk.StringVar()

        ttk.Label(rahmen, text="ID:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(rahmen, textvariable=self.var_id).grid(row=0, column=1, sticky="w")

        ttk.Label(rahmen, text="Bezeichnung *:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(rahmen, textvariable=self.var_bezeichnung, width=40).grid(row=1, column=1, sticky="w")

        ttk.Label(rahmen, text="Kostenstelle:").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(rahmen, textvariable=self.var_kostenstelle, width=40).grid(row=2, column=1, sticky="w")

    def _baue_buttons(self):
        rahmen = ttk.Frame(self, padding=10)
        rahmen.pack(fill="x")
        ttk.Button(rahmen, text="Neu (Formular leeren)", command=self.formular_leeren).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Einfuegen", command=self.einfuegen).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Aktualisieren", command=self.aktualisieren).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Loeschen", command=self.loeschen).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Liste neu laden", command=self.lade_abteilungen).pack(side="right", padx=5)

    # ---------- Daten ----------

    def lade_abteilungen(self):
        try:
            zeilen = self.repo.finde_alle()
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", f"Abteilungen konnten nicht geladen werden:\n{fehler}")
            return
        self.zeilen = {z["id_abteilung"]: z for z in zeilen}
        self.tabelle.delete(*self.tabelle.get_children())
        for z in zeilen:
            self.tabelle.insert("", "end", iid=str(z["id_abteilung"]),
                                values=(z["id_abteilung"], z["bezeichnung"], z["kostenstelle"] or ""))

    def zeile_gewaehlt(self, _event=None):
        auswahl = self.tabelle.selection()
        if not auswahl:
            return
        zeile = self.zeilen[int(auswahl[0])]
        self.var_id.set(zeile["id_abteilung"])
        self.var_bezeichnung.set(zeile["bezeichnung"])
        self.var_kostenstelle.set(zeile["kostenstelle"] or "")

    def formular_leeren(self):
        self.tabelle.selection_remove(self.tabelle.selection())
        self.var_id.set("")
        self.var_bezeichnung.set("")
        self.var_kostenstelle.set("")

    def formular_lesen(self):
        """Liefert (bezeichnung, kostenstelle) oder None bei ungueltiger Eingabe."""
        bezeichnung = self.var_bezeichnung.get().strip()
        kostenstelle = self.var_kostenstelle.get().strip()
        if not bezeichnung:
            messagebox.showwarning("Eingabe fehlt", "Bitte eine Bezeichnung eingeben.")
            return None
        if len(bezeichnung) > 100:
            messagebox.showwarning("Zu lang", "Die Bezeichnung darf maximal 100 Zeichen haben.")
            return None
        if len(kostenstelle) > 20:
            messagebox.showwarning("Zu lang", "Die Kostenstelle darf maximal 20 Zeichen haben.")
            return None
        return bezeichnung, kostenstelle or None

    # ---------- Aktionen ----------

    def einfuegen(self):
        if self.var_id.get():
            messagebox.showinfo("Hinweis", "Es ist eine bestehende Abteilung ausgewaehlt.\n"
                                           "Fuer eine neue Abteilung zuerst 'Neu' klicken.")
            return
        daten = self.formular_lesen()
        if daten is None:
            return
        try:
            neue_id = self.repo.einfuegen(*daten)
        except dbapi.IntegrityError:
            messagebox.showerror("Nicht gespeichert", f"Die Abteilung '{daten[0]}' existiert bereits.")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.lade_abteilungen()
        self.tabelle.selection_set(str(neue_id))
        messagebox.showinfo("Gespeichert", f"Abteilung mit ID {neue_id} wurde angelegt.")

    def aktualisieren(self):
        if not self.var_id.get():
            messagebox.showwarning("Keine Auswahl", "Bitte zuerst eine Abteilung in der Liste auswaehlen.")
            return
        daten = self.formular_lesen()
        if daten is None:
            return
        id_abteilung = int(self.var_id.get())
        try:
            self.repo.aktualisieren(id_abteilung, *daten)
        except dbapi.IntegrityError:
            messagebox.showerror("Nicht gespeichert", f"Die Abteilung '{daten[0]}' existiert bereits.")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.lade_abteilungen()
        self.tabelle.selection_set(str(id_abteilung))
        messagebox.showinfo("Gespeichert", "Abteilung wurde aktualisiert.")

    def loeschen(self):
        if not self.var_id.get():
            messagebox.showwarning("Keine Auswahl", "Bitte zuerst eine Abteilung in der Liste auswaehlen.")
            return
        id_abteilung = int(self.var_id.get())
        bezeichnung = self.var_bezeichnung.get()
        if not messagebox.askyesno("Loeschen bestaetigen",
                                   f"Abteilung '{bezeichnung}' (ID {id_abteilung}) wirklich loeschen?"):
            return
        try:
            self.repo.loeschen(id_abteilung)
        except dbapi.IntegrityError:
            messagebox.showerror("Loeschen nicht moeglich",
                                 "Diese Abteilung ist noch Vertraegen zugewiesen.\n\n"
                                 "Bitte den Vertraegen zuerst eine andere Abteilung geben.")
            return
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", str(fehler))
            return
        self.formular_leeren()
        self.lade_abteilungen()


# =====================================================
# HAUPTFENSTER MIT REITERN
# =====================================================

class Hauptfenster:
    def __init__(self, root: tk.Tk, db: Datenbankverbindung):
        self.root = root
        self.db = db

        root.title("Vertragsverwaltung")
        root.geometry("1000x620")
        root.protocol("WM_DELETE_WINDOW", self.beenden)

        rollen_repo = RolleRepository(db)
        benutzer_repo = BenutzerRepository(db)

        self.reiter = ttk.Notebook(root)
        self.reiter.pack(fill="both", expand=True)

        self.rollen_reiter = RollenReiter(self.reiter, rollen_repo)
        self.benutzer_reiter = BenutzerReiter(self.reiter, benutzer_repo, rollen_repo)
        self.abteilungen_reiter = AbteilungenReiter(self.reiter, AbteilungRepository(db))

        self.reiter.add(self.rollen_reiter, text="Rollen")
        self.reiter.add(self.benutzer_reiter, text="Benutzer")
        self.reiter.add(self.abteilungen_reiter, text="Abteilungen")
        # Neue Tabellen spaeter einfach hier als weiteren Reiter anhaengen.

        self.reiter.bind("<<NotebookTabChanged>>", self.reiter_gewechselt)

    def reiter_gewechselt(self, _event=None):
        # Beim Wechsel zu "Benutzer" die Rollenliste auffrischen,
        # damit neu angelegte Rollen sofort in der Auswahl stehen.
        if self.reiter.select() == str(self.benutzer_reiter):
            self.benutzer_reiter.neu_laden()

    def beenden(self):
        self.db.trennen()
        self.root.destroy()


# =====================================================
# START
# =====================================================

def main():
    root = tk.Tk()
    db = Datenbankverbindung(DB_CONFIG, DB_TYPE)
    try:
        db.verbinden()
    except dbapi.Error as fehler:
        messagebox.showerror("Verbindung fehlgeschlagen",
                             f"Keine Verbindung zur Datenbank moeglich:\n\n{fehler}\n\n"
                             "Bitte DB_CONFIG oben im Code pruefen.")
        root.destroy()
        return

    Hauptfenster(root, db)
    root.mainloop()


if __name__ == "__main__":
    main()

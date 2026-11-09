"""
Benutzerverwaltung - einfache Tkinter-GUI (erste Testversion)

Funktionen: Benutzer anzeigen, einfuegen, aktualisieren, loeschen.

Aufbau (wie im Klassendiagramm, vorerst alles in einer Datei):
    Datenbankverbindung  -> kuemmert sich nur um die Verbindung und SQL
    BenutzerRepository   -> alle SQL-Befehle fuer die Tabelle benutzer
    BenutzerFenster      -> die Oberflaeche (Tkinter)

Benoetigt:
    MySQL:    pip install mysql-connector-python
    Postgres: pip install "psycopg[binary]"
Tkinter ist bei Python unter Windows bereits dabei.
"""

import hashlib
import hmac
import os
import tkinter as tk
from tkinter import ttk, messagebox


# =====================================================
# KONFIGURATION - hier anpassen
# =====================================================

DB_TYPE = "postgres"       # "mysql" oder "postgres"

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
# DATENBANKVERBINDUNG
# =====================================================

class Datenbankverbindung:
    def __init__(self, config: dict, db_type: str):
        self.__config = config
        self.__db_type = db_type
        self.__verbindung = None

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

    def abfragen(self, sql: str, parameter: tuple = ()) -> list:
        """Fuer SELECT: liefert alle Zeilen als Liste von Tupeln."""
        cursor = self.__verbindung.cursor()
        try:
            cursor.execute(sql, parameter)
            zeilen = cursor.fetchall()
            self.__verbindung.commit()   # Lese-Transaktion beenden -> immer aktuelle Daten
            return zeilen
        finally:
            cursor.close()

    def ausfuehren(self, sql: str, parameter: tuple = ()) -> int:
        """Fuer UPDATE/DELETE: liefert die Anzahl betroffener Zeilen."""
        cursor = self.__verbindung.cursor()
        try:
            cursor.execute(sql, parameter)
            anzahl = cursor.rowcount
            self.__verbindung.commit()
            return anzahl
        except Exception:
            self.__verbindung.rollback()
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
            self.__verbindung.commit()
            return neue_id
        except Exception:
            self.__verbindung.rollback()
            raise
        finally:
            cursor.close()


# =====================================================
# REPOSITORY FUER DIE TABELLE benutzer
# =====================================================

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

    def finde_rollen(self) -> list:
        # Gehoert spaeter in ein eigenes RolleRepository
        return self.__db.abfragen("SELECT id_rolle, bezeichnung FROM rolle ORDER BY id_rolle")

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
        return self.__db.ausfuehren("DELETE FROM benutzer WHERE id_benutzer = %s", (id_benutzer,))


# =====================================================
# OBERFLAECHE
# =====================================================

class BenutzerFenster:
    def __init__(self, root: tk.Tk, repo: BenutzerRepository, db: Datenbankverbindung):
        self.root = root
        self.repo = repo
        self.db = db
        self.rollen = {}            # bezeichnung -> id_rolle
        self.benutzer_daten = {}    # id_benutzer -> Datenbankzeile

        root.title("Vertragsverwaltung - Benutzer")
        root.geometry("1000x600")
        root.protocol("WM_DELETE_WINDOW", self.beenden)

        self._baue_tabelle()
        self._baue_formular()
        self._baue_buttons()

        self.lade_rollen()
        self.lade_benutzer()

    # ---------- Aufbau ----------

    def _baue_tabelle(self):
        rahmen = ttk.Frame(self.root, padding=10)
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
        rahmen = ttk.LabelFrame(self.root, text="Benutzer bearbeiten", padding=10)
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
        rahmen = ttk.Frame(self.root, padding=10)
        rahmen.pack(fill="x")
        ttk.Button(rahmen, text="Neu (Formular leeren)", command=self.formular_leeren).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Einfuegen", command=self.einfuegen).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Aktualisieren", command=self.aktualisieren).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Loeschen", command=self.loeschen).pack(side="left", padx=5)
        ttk.Button(rahmen, text="Liste neu laden", command=self.lade_benutzer).pack(side="right", padx=5)

    # ---------- Daten laden ----------

    def lade_rollen(self):
        try:
            zeilen = self.repo.finde_rollen()
        except dbapi.Error as fehler:
            messagebox.showerror("Datenbankfehler", f"Rollen konnten nicht geladen werden:\n{fehler}")
            return
        self.rollen = {bezeichnung: id_rolle for id_rolle, bezeichnung in zeilen}
        self.combo_rolle["values"] = list(self.rollen.keys())
        if not self.rollen:
            messagebox.showwarning("Hinweis", "Es gibt noch keine Rollen in der Datenbank.\n"
                                              "Bitte zuerst Rollen anlegen.")

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
            messagebox.showwarning("Eingabe fehlt", "Bitte eine Rolle auswaehlen.")
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

    repo = BenutzerRepository(db)
    BenutzerFenster(root, repo, db)
    root.mainloop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Application GUI pour supprimer les doublons Archifiltre - Version 5.0
Corrections v5.0:
- Bug corrigé : résolution de chemin format Archifiltre (/NomRacine/subdir/fichier)
- Bug corrigé : détection flexible de la colonne de date (plusieurs noms possibles)
- Interface : Treeview avec sélection individuelle par case à cocher
- Interface : PanedWindow redimensionnable, scrollbar horizontale
- Interface : statut par fichier (✓/✗) mis à jour en temps réel pendant suppression
- Interface : fenêtre de diagnostic de correspondance chemin CSV ↔ disque
- Interface : sélection de rapport parmi plusieurs
- Suppression sélective : cocher/décocher chaque copie avant suppression
- Meilleure gestion des erreurs Windows (PermissionError, fichiers verrouillés)
- Rapport sauvegardé dans le dossier du script
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import csv
import os
import subprocess
from collections import defaultdict
from datetime import datetime
import threading
import hashlib
from pathlib import Path

try:
    from send2trash import send2trash
    SEND2TRASH_AVAILABLE = True
except ImportError:
    SEND2TRASH_AVAILABLE = False

COLONNES_REQUISES = {'fichier/répertoire', 'empreinte (MD5)', 'nom', 'chemin', 'poids (octets)'}

# Noms alternatifs de la colonne de date selon la version d'Archifiltre
DATE_COLONNES = [
    'date de première modification',
    'date de dernière modification',
    'dernière modification',
    'date de creation',
    'date de création',
    'date_modification',
    'date',
]

FORMATS_DATE = (
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d',
    '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y',
    '%Y/%m/%d %H:%M:%S', '%Y/%m/%d',
)

COLORS = {
    'primary':   '#EF7757',
    'secondary': '#292575',
    'accent1':   '#8E84AE',
    'accent2':   '#C6BFD8',
    'accent3':   '#E7E4EF',
    'bg':        '#F5F3F8',
    'text':      '#2C2C2C',
    'success':   '#4CAF50',
    'error':     '#F44336',
    'warning':   '#FF9800',
}

# Dossier du script (pour y stocker les rapports)
SCRIPT_DIR = Path(__file__).parent.resolve()


# ── Fonctions utilitaires ────────────────────────────────────────────────────

def to_int(valeur):
    try:
        return int(str(valeur).strip() or 0)
    except (ValueError, TypeError):
        return 0


def parse_date(valeur):
    s = (valeur or '').strip()
    if not s:
        return datetime.max
    for fmt in FORMATS_DATE:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.max


def calculer_md5(chemin, chunk=1 << 20):
    h = hashlib.md5()
    with open(chemin, 'rb') as f:
        for bloc in iter(lambda: f.read(chunk), b''):
            h.update(bloc)
    return h.hexdigest()


def format_size(octets):
    octets = max(0, octets)
    if octets >= 1024 ** 3:
        return f"{octets / (1024 ** 3):.2f} Go"
    if octets >= 1024 ** 2:
        return f"{octets / (1024 ** 2):.2f} Mo"
    if octets >= 1024:
        return f"{octets / 1024:.2f} Ko"
    return f"{octets} o"


def ouvrir_explorateur(chemin):
    """Ouvre l'Explorateur Windows sur le dossier du fichier."""
    try:
        cible = os.path.dirname(chemin) if os.path.isfile(chemin) else chemin
        if os.path.isdir(cible):
            subprocess.Popen(['explorer', os.path.normpath(cible)])
    except Exception:
        pass


# ── Classes de données ────────────────────────────────────────────────────────

class DoublonsStats:
    def __init__(self, doublons_dict):
        self.total_groupes = len(doublons_dict)
        self.total_copies  = sum(len(d['copies']) for d in doublons_dict.values())
        self.espace_total  = sum(
            to_int(f.get('poids', 0))
            for d in doublons_dict.values() for f in d['copies']
        )

    def get_formatted_size(self):
        return format_size(self.espace_total)


class FileIndex:
    """Index pré-calculé pour recherche rapide de fichiers.

    CORRECTION v5.0 : stocke les chemins sous plusieurs formats pour correspondre
    aux exports Archifiltre qui utilisent '/NomDossierRacine/sous-dossier/fichier.txt'.
    """

    def __init__(self):
        self.nom_to_path       = defaultdict(list)
        self.chemin_csv_to_real = {}
        self.total_files       = 0
        self.indexed           = False
        self._root_name        = ''

    def indexer_repertoire(self, repertoire_root, progress_callback=None):
        self.nom_to_path.clear()
        self.chemin_csv_to_real.clear()
        self.total_files = 0
        self.indexed     = False
        self._root_name  = os.path.basename(os.path.normpath(repertoire_root))

        try:
            current = 0
            for dirpath, _dirs, filenames in os.walk(repertoire_root):
                for fname in filenames:
                    full = os.path.join(dirpath, fname)
                    self.nom_to_path[fname].append(full)
                    try:
                        rel      = os.path.relpath(full, repertoire_root)
                        rel_unix = rel.replace('\\', '/')

                        # 4 formats stockés pour maximiser les correspondances
                        # 1) chemin relatif natif   ex: sous-dossier\fichier.txt
                        self.chemin_csv_to_real[rel] = full
                        # 2) séparateurs UNIX        ex: sous-dossier/fichier.txt
                        self.chemin_csv_to_real[rel_unix] = full
                        # 3) format Archifiltre      ex: /NomRacine/sous-dossier/fichier.txt
                        archi = '/' + self._root_name + '/' + rel_unix
                        self.chemin_csv_to_real[archi] = full
                        # 4) idem sans slash initial ex: NomRacine/sous-dossier/fichier.txt
                        self.chemin_csv_to_real[archi.lstrip('/')] = full
                    except ValueError:
                        pass
                    current += 1
                    if progress_callback and current % 1000 == 0:
                        progress_callback(current)
            self.total_files = current
            self.indexed     = True
        except Exception as e:
            print(f"Erreur indexation: {e}")
            self.indexed = False

    def resoudre_chemin_exact(self, chemin_csv):
        """Résout un chemin CSV en chemin réel. Essaie de nombreuses variantes."""
        chemin_csv = (chemin_csv or '').strip()
        if not chemin_csv:
            return None

        chemin_unix = chemin_csv.replace('\\', '/')
        chemin_os   = chemin_csv.replace('/', os.sep).replace('\\', os.sep)

        cles = [
            chemin_csv,
            chemin_unix,
            chemin_os,
            chemin_csv.lstrip('/\\'),
            chemin_unix.lstrip('/'),
        ]

        # Retirer le premier composant (nom du dossier racine inclus par Archifiltre)
        stripped = chemin_unix.lstrip('/')
        parts = stripped.split('/', 1)
        if len(parts) == 2:
            sans_racine = parts[1]
            cles.append(sans_racine)
            cles.append(sans_racine.replace('/', os.sep))

        for cle in cles:
            if cle and cle in self.chemin_csv_to_real:
                p = self.chemin_csv_to_real[cle]
                if os.path.isfile(p):
                    return p
        return None

    def candidats_par_nom(self, nom):
        result = []
        seen   = set()
        for p in self.nom_to_path.get(nom, []):
            key = os.path.normcase(os.path.abspath(p))
            if key not in seen and os.path.isfile(p):
                seen.add(key)
                result.append(p)
        return result

    def diagnostiquer_chemin(self, chemin_csv):
        """Retourne un message expliquant pourquoi un chemin n'a pas été résolu."""
        chemin_csv = (chemin_csv or '').strip()
        if not chemin_csv:
            return "Chemin vide dans le CSV"

        exact = self.resoudre_chemin_exact(chemin_csv)
        if exact:
            return f"Trouvé: {exact}"

        nom = os.path.basename(chemin_csv.replace('\\', '/').rstrip('/'))
        candidats = self.candidats_par_nom(nom)
        if not candidats:
            return f"Fichier '{nom}' absent du répertoire indexé"
        return (f"Fichier '{nom}' présent mais chemin non concordant.\n"
                f"  CSV    : {chemin_csv}\n"
                f"  Disque : {candidats[0]}"
                + (f"\n  ({len(candidats)} fichier(s) avec ce nom)" if len(candidats) > 1 else ""))


# ── Application principale ────────────────────────────────────────────────────

class ApplicationDoublons:
    _CB_ON  = '☑'
    _CB_OFF = '☐'

    def __init__(self, root):
        self.root = root
        self.root.title("Suppression des Doublons Archifiltre — v5.0")

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        ww = min(int(sw * 0.90), 1500)
        wh = min(int(sh * 0.90), 1000)
        self.root.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        self.root.minsize(900, 620)

        self.setup_style()

        self.csv_path          = None
        self.repertoire_source = None
        self.donnees           = []
        self.doublons          = {}
        self.doublons_stats    = None
        self.suppression_thread    = None
        self.cancellation_requested = False
        self._date_colonne     = None

        self._items_sel   = {}   # {item_id: bool}  copies Treeview
        self._copie_key   = {}   # {(hash, nom, chemin): item_id}

        self.file_index = FileIndex()

        self.verifier_md5 = tk.BooleanVar(value=True)
        self.use_trash    = tk.BooleanVar(value=SEND2TRASH_AVAILABLE)

        self._paned = None  # référence au PanedWindow pour sash
        self.setup_ui()

    # ── Style ────────────────────────────────────────────────────────────────

    def setup_style(self):
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('TFrame',        background=COLORS['bg'])
        s.configure('TLabel',        background=COLORS['bg'], foreground=COLORS['text'])
        s.configure('TCheckbutton',  background=COLORS['bg'], foreground=COLORS['text'])
        s.configure('Header.TLabel', background=COLORS['secondary'], foreground='white',
                    font=('Segoe UI', 13, 'bold'), padding=10)
        s.configure('Title.TLabel',  background=COLORS['bg'], foreground=COLORS['secondary'],
                    font=('Segoe UI', 10, 'bold'))
        s.configure('Subtitle.TLabel', background=COLORS['bg'], foreground=COLORS['accent1'],
                    font=('Segoe UI', 9))
        s.configure('Stat.TLabel',   background=COLORS['accent3'], foreground=COLORS['secondary'],
                    font=('Segoe UI', 10, 'bold'), padding=4, relief='solid', borderwidth=1)
        s.configure('TButton',       font=('Segoe UI', 9))
        s.map('TButton', background=[('active', COLORS['primary'])], foreground=[('active', 'white')])
        s.configure('Primary.TButton', background=COLORS['primary'])
        s.map('Primary.TButton', background=[('active', '#D96B4D'), ('pressed', '#B35A42')])
        s.configure('Cancel.TButton', background=COLORS['error'])
        s.map('Cancel.TButton', background=[('active', '#DA321C'), ('pressed', '#B52812')])
        s.configure('Warn.TButton', background=COLORS['warning'])
        s.map('Warn.TButton', background=[('active', '#E68900')])
        s.configure('TLabelframe',       background=COLORS['bg'], borderwidth=1, relief='solid')
        s.configure('TLabelframe.Label', background=COLORS['bg'], foreground=COLORS['secondary'],
                    font=('Segoe UI', 9, 'bold'))
        s.configure('TProgressbar', background=COLORS['primary'], troughcolor=COLORS['accent3'])
        s.configure('Treeview',         font=('Segoe UI', 9), rowheight=22, background='white')
        s.configure('Treeview.Heading', font=('Segoe UI', 9, 'bold'),
                    background=COLORS['secondary'], foreground='white')
        s.map('Treeview', background=[('selected', COLORS['accent2'])])
        self.root.configure(bg=COLORS['bg'])

    # ── Interface ─────────────────────────────────────────────────────────────

    def setup_ui(self):
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # En-tête
        ttk.Label(main, text="🗂️  Suppression des Doublons Archifiltre  —  v5.0",
                  style='Header.TLabel').pack(fill=tk.X, pady=(0, 8))

        # PanedWindow vertical : contrôles (haut) / liste doublons (bas)
        paned = tk.PanedWindow(main, orient=tk.VERTICAL, sashwidth=7,
                               sashrelief='raised', bg=COLORS['accent2'])
        paned.pack(fill=tk.BOTH, expand=True)
        self._paned = paned

        # ── Panneau haut ──
        top = ttk.Frame(paned, padding=4)
        paned.add(top, minsize=270)

        # Chargement
        lf_load = ttk.Labelframe(top, text="1. CHARGER LES FICHIERS", padding=8)
        lf_load.pack(fill=tk.X, pady=(0, 6))

        for label_txt, attr, cmd in [
            ("📋 CSV Archifiltre :", 'csv_label', self.charger_csv),
            ("📁 Répertoire source :", 'rep_label', self.charger_repertoire),
        ]:
            row = ttk.Frame(lf_load)
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=label_txt, style='Title.TLabel', width=22).pack(side=tk.LEFT)
            lbl = ttk.Label(row, text="❌ Aucun", foreground=COLORS['error'],
                            font=('Segoe UI', 9), wraplength=700, anchor=tk.W)
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 8))
            ttk.Button(row, text="Parcourir…", command=cmd).pack(side=tk.RIGHT)
            setattr(self, attr, lbl)

        # Stats + Options
        mid = ttk.Frame(top)
        mid.pack(fill=tk.X, pady=(0, 6))
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)

        lf_stats = ttk.Labelframe(mid, text="2. STATISTIQUES", padding=8)
        lf_stats.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        sg = ttk.Frame(lf_stats)
        sg.pack(fill=tk.X)
        sg.columnconfigure(0, weight=1)
        sg.columnconfigure(1, weight=1)
        for idx, (txt, attr, val) in enumerate([
            ("📊 Fichiers analysés",   'label_fichiers',    '0'),
            ("🔗 Groupes de doublons", 'label_groupes',     '0'),
            ("🗑️  Copies à supprimer", 'label_a_supprimer', '0'),
            ("💾 Espace à libérer",    'label_espace',      '0 o'),
        ]):
            fr = ttk.Frame(sg)
            fr.grid(row=idx // 2, column=idx % 2, sticky=tk.EW, padx=4, pady=4)
            ttk.Label(fr, text=txt, style='Subtitle.TLabel').pack(side=tk.LEFT, padx=(0, 6))
            lbl = ttk.Label(fr, text=val, style='Stat.TLabel')
            lbl.pack(side=tk.LEFT)
            setattr(self, attr, lbl)

        lf_opt = ttk.Labelframe(mid, text="OPTIONS", padding=8)
        lf_opt.grid(row=0, column=1, sticky='nsew')
        ttk.Checkbutton(lf_opt,
            text="🔐 Vérifier MD5 avant suppression\n   (recommandé, plus lent)",
            variable=self.verifier_md5).pack(anchor=tk.W, pady=4)
        trash_txt = "♻️  Corbeille (réversible)"
        if not SEND2TRASH_AVAILABLE:
            trash_txt += "\n   ⚠️ send2trash absent → DÉFINITIF"
        cb_trash = ttk.Checkbutton(lf_opt, text=trash_txt, variable=self.use_trash)
        cb_trash.pack(anchor=tk.W, pady=4)
        if not SEND2TRASH_AVAILABLE:
            cb_trash.configure(state=tk.DISABLED)

        # Progression
        lf_prog = ttk.Frame(top)
        lf_prog.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(lf_prog, text="Progression :", style='Subtitle.TLabel').pack(anchor=tk.W)
        self.progress_bar  = ttk.Progressbar(lf_prog, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(2, 2))
        self.progress_text = ttk.Label(lf_prog, text="Prêt", style='Subtitle.TLabel')
        self.progress_text.pack(anchor=tk.W)

        # ── Panneau bas : Treeview ──
        bot = ttk.Frame(paned, padding=4)
        paned.add(bot, minsize=180)

        lf_list = ttk.Labelframe(bot, text="3. DOUBLONS DÉTECTÉS", padding=6)
        lf_list.pack(fill=tk.BOTH, expand=True)

        # Barre d'outils du Treeview
        tvbar = ttk.Frame(lf_list)
        tvbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(tvbar, text="☑ Tout",   command=self._tout_sel).pack(side=tk.LEFT, padx=2)
        ttk.Button(tvbar, text="☐ Aucun",  command=self._tout_desel).pack(side=tk.LEFT, padx=2)
        ttk.Button(tvbar, text="🔍 Diagnostiquer chemins",
                   command=self.diagnostiquer_chemins,
                   style='Warn.TButton').pack(side=tk.LEFT, padx=10)
        self.lbl_sel = ttk.Label(tvbar, text="", style='Subtitle.TLabel')
        self.lbl_sel.pack(side=tk.RIGHT, padx=4)

        # Treeview
        tv_frame = ttk.Frame(lf_list)
        tv_frame.pack(fill=tk.BOTH, expand=True)
        tv_frame.rowconfigure(0, weight=1)
        tv_frame.columnconfigure(0, weight=1)

        cols = ('sel', 'nom', 'chemin', 'taille', 'statut')
        self.tree = ttk.Treeview(tv_frame, columns=cols, show='headings', selectmode='none')
        self.tree.heading('sel',    text='☑',             anchor=tk.CENTER)
        self.tree.heading('nom',    text='Nom',            anchor=tk.W)
        self.tree.heading('chemin', text='Chemin (CSV)',   anchor=tk.W)
        self.tree.heading('taille', text='Taille',         anchor=tk.E)
        self.tree.heading('statut', text='Statut',         anchor=tk.W)
        self.tree.column('sel',    width=32,  minwidth=30, stretch=False, anchor=tk.CENTER)
        self.tree.column('nom',    width=200, minwidth=100)
        self.tree.column('chemin', width=460, minwidth=150)
        self.tree.column('taille', width=80,  minwidth=60, anchor=tk.E, stretch=False)
        self.tree.column('statut', width=180, minwidth=80)

        vsb = ttk.Scrollbar(tv_frame, orient='vertical',   command=self.tree.yview)
        hsb = ttk.Scrollbar(tv_frame, orient='horizontal',  command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        # Tags de couleur
        self.tree.tag_configure('groupe',    background='#E3F2FD', font=('Segoe UI', 9, 'bold'))
        self.tree.tag_configure('sel',       background='#F1F8E9')
        self.tree.tag_configure('desel',     background='#FFF9C4')
        self.tree.tag_configure('ok',        background='#C8E6C9')
        self.tree.tag_configure('err',       background='#FFCDD2')
        self.tree.tag_configure('ignore',    background='#FFE0B2')

        self.tree.bind('<ButtonRelease-1>',       self._on_click)
        self.tree.bind('<Double-ButtonRelease-1>', self._on_dbl_click)

        # ── Actions ──
        act = ttk.Frame(main)
        act.pack(fill=tk.X, pady=(6, 0))
        self.btn_supprimer = ttk.Button(act, text="🗑️ Supprimer la sélection",
                                        command=self.supprimer_doublons,
                                        style='Primary.TButton')
        self.btn_supprimer.pack(side=tk.LEFT, padx=4)
        self.btn_annuler = ttk.Button(act, text="⛔ Annuler",
                                      command=self.annuler_suppression,
                                      style='Cancel.TButton', state=tk.DISABLED)
        self.btn_annuler.pack(side=tk.LEFT, padx=4)
        self.btn_rapport = ttk.Button(act, text="📄 Voir rapport", command=self.voir_rapport)
        self.btn_rapport.pack(side=tk.LEFT, padx=4)
        self.btn_reset   = ttk.Button(act, text="🔄 Réinitialiser", command=self.reinitialiser)
        self.btn_reset.pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="❌ Quitter", command=self.quitter).pack(side=tk.LEFT, padx=4)

        # Barre de statut
        self.status_var = tk.StringVar(value="Prêt — Chargez le CSV puis sélectionnez le répertoire source")
        ttk.Label(main, textvariable=self.status_var, relief=tk.SUNKEN,
                  style='Subtitle.TLabel', background=COLORS['accent3'],
                  padding=8).pack(fill=tk.X, pady=(6, 0))

        # Positionner le sash après rendu
        self.root.after(150, lambda: paned.sash_place(0, 0, 330))

    # ── Chargement ───────────────────────────────────────────────────────────

    def _lire_csv(self, chemin):
        derniere_erreur = None
        for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
            try:
                with open(chemin, 'r', encoding=enc, newline='') as f:
                    lecteur  = csv.DictReader(f, delimiter=';')
                    fieldnames = set(lecteur.fieldnames or [])
                    manquantes = COLONNES_REQUISES - fieldnames
                    if manquantes:
                        raise ValueError(
                            "Colonnes manquantes dans le CSV :\n  "
                            + "\n  ".join(sorted(manquantes))
                            + "\n\nCe fichier est-il un export Archifiltre (séparateur ';') ?"
                        )
                    self._date_colonne = next(
                        (c for c in DATE_COLONNES if c in fieldnames), None
                    )
                    return [
                        ligne for ligne in lecteur
                        if (ligne.get('fichier/répertoire') or '').strip() == 'fichier'
                    ]
            except UnicodeDecodeError as e:
                derniere_erreur = e
                continue
        raise ValueError(f"Encodage CSV non reconnu : {derniere_erreur}")

    def charger_csv(self):
        chemin = filedialog.askopenfilename(
            title="Ouvrir fichier CSV Archifiltre",
            filetypes=[("CSV", "*.csv"), ("Tous les fichiers", "*.*")]
        )
        if not chemin:
            return
        try:
            self.status_var.set("Chargement du CSV…")
            self.root.update_idletasks()
            self.donnees  = self._lire_csv(chemin)
            self.csv_path = chemin
            date_info = f"  |  date: «{self._date_colonne}»" if self._date_colonne \
                        else "  |  ⚠️ colonne de date absente (ordre CSV conservé)"
            self.csv_label.config(
                text=f"✓ {os.path.basename(chemin)}{date_info}",
                foreground=COLORS['success']
            )
            if self.repertoire_source:
                self.analyser_doublons()
            else:
                self.status_var.set(
                    f"CSV chargé ({len(self.donnees):,} fichiers) — Sélectionnez le répertoire source"
                )
        except Exception as e:
            messagebox.showerror("Erreur CSV", str(e))
            self.status_var.set("Erreur chargement CSV")

    def charger_repertoire(self):
        repertoire = filedialog.askdirectory(
            title="Sélectionner le répertoire source des archives"
        )
        if not repertoire:
            return
        try:
            self.status_var.set("Indexation du répertoire…")
            self.root.update_idletasks()
            self.repertoire_source = repertoire

            def _prog(n):
                self.progress_text.config(text=f"Indexation : {n:,} fichiers…")
                self.root.update_idletasks()

            self.file_index.indexer_repertoire(repertoire, progress_callback=_prog)
            self.progress_text.config(text="Indexation terminée")
            nom = os.path.basename(os.path.normpath(repertoire))
            self.rep_label.config(
                text=f"✓ {nom}  ({self.file_index.total_files:,} fichiers indexés)",
                foreground=COLORS['success']
            )
            if self.donnees:
                self.analyser_doublons()
            else:
                self.status_var.set(
                    f"Répertoire indexé ({self.file_index.total_files:,} fichiers) — Chargez le CSV"
                )
        except Exception as e:
            messagebox.showerror("Erreur répertoire", str(e))
            self.status_var.set("Erreur chargement répertoire")

    # ── Analyse ───────────────────────────────────────────────────────────────

    def analyser_doublons(self):
        if not self.donnees or not self.repertoire_source:
            return
        self.status_var.set("Analyse en cours…")
        self.progress_bar['value'] = 0
        self.progress_text.config(text="Regroupement par empreinte MD5…")
        self.root.update_idletasks()

        groupes = defaultdict(list)
        total   = len(self.donnees)
        for i, fichier in enumerate(self.donnees):
            h = (fichier.get('empreinte (MD5)') or '').strip()
            if h:
                date_val = fichier.get(self._date_colonne, '') if self._date_colonne else ''
                groupes[h].append({
                    'nom':   fichier.get('nom', '?'),
                    'chemin': fichier.get('chemin', '?'),
                    'poids': to_int(fichier.get('poids (octets)', 0)),
                    'date':  date_val,
                })
            if (i + 1) % 5000 == 0:
                self.progress_bar['value'] = int((i + 1) / total * 50)
                self.root.update_idletasks()

        self.doublons = {}
        for h, fichiers in groupes.items():
            if len(fichiers) > 1:
                tries = sorted(fichiers, key=lambda f: parse_date(f.get('date', '')))
                self.doublons[h] = {'original': tries[0], 'copies': tries[1:]}

        self.doublons_stats = DoublonsStats(self.doublons)
        self.label_fichiers.config(    text=f"{len(self.donnees):,}")
        self.label_groupes.config(     text=f"{self.doublons_stats.total_groupes:,}")
        self.label_a_supprimer.config( text=f"{self.doublons_stats.total_copies:,}")
        self.label_espace.config(      text=self.doublons_stats.get_formatted_size())
        self.progress_bar['value'] = 100
        self.progress_text.config(
            text=f"✓ {self.doublons_stats.total_groupes:,} groupes, "
                 f"{self.doublons_stats.total_copies:,} copies"
        )
        self.status_var.set(
            f"Analyse terminée — {self.doublons_stats.total_copies:,} fichiers à supprimer "
            f"dans {self.doublons_stats.total_groupes:,} groupes"
        )
        self._remplir_treeview()

    def _remplir_treeview(self):
        self.tree.delete(*self.tree.get_children())
        self._items_sel.clear()
        self._copie_key.clear()

        if not self.doublons:
            self.tree.insert('', 'end',
                values=('', '✨ Aucun doublon détecté', '', '', ''), tags=('groupe',))
            self._maj_lbl_sel()
            return

        # Au-delà de 200 groupes : replier les groupes par défaut pour la perf
        collapse = self.doublons_stats.total_groupes > 200

        for hash_md5, groupe in self.doublons.items():
            orig = groupe['original']
            gid  = self.tree.insert('', 'end', values=(
                '',
                f"📁 ORIGINAL : {orig.get('nom', '?')}",
                orig.get('chemin', '?'),
                format_size(to_int(orig.get('poids', 0))),
                f"Hash : {hash_md5[:16]}…",
            ), tags=('groupe',), open=not collapse)

            for copie in groupe['copies']:
                nom    = copie.get('nom', '?')
                chemin = copie.get('chemin', '?')
                iid    = self.tree.insert(gid, 'end', values=(
                    self._CB_ON,
                    nom,
                    chemin,
                    format_size(to_int(copie.get('poids', 0))),
                    'En attente',
                ), tags=('sel',))
                self._items_sel[iid]  = True
                self._copie_key[(hash_md5, nom, chemin)] = iid

        self._maj_lbl_sel()

    # ── Treeview interactions ────────────────────────────────────────────────

    def _on_click(self, event):
        col  = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)
        if item and col == '#1' and item in self._items_sel:
            self._toggle(item)

    def _on_dbl_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        vals = self.tree.item(item, 'values')
        if not vals or len(vals) < 3:
            return
        chemin_csv = vals[2]
        reel = self.file_index.resoudre_chemin_exact(chemin_csv)
        if reel:
            ouvrir_explorateur(reel)
        else:
            messagebox.showinfo(
                "Chemin non résolu",
                f"Chemin CSV :\n{chemin_csv}\n\n"
                "Ce fichier n'a pas été trouvé sur le disque.\n"
                "Utilisez 'Diagnostiquer chemins' pour plus d'informations."
            )

    def _toggle(self, iid):
        sel = not self._items_sel.get(iid, True)
        self._items_sel[iid] = sel
        vals    = list(self.tree.item(iid, 'values'))
        vals[0] = self._CB_ON if sel else self._CB_OFF
        self.tree.item(iid, values=vals, tags=('sel' if sel else 'desel',))
        self._maj_lbl_sel()

    def _tout_sel(self):
        for iid in self._items_sel:
            self._items_sel[iid] = True
            v    = list(self.tree.item(iid, 'values'))
            v[0] = self._CB_ON
            self.tree.item(iid, values=v, tags=('sel',))
        self._maj_lbl_sel()

    def _tout_desel(self):
        for iid in self._items_sel:
            self._items_sel[iid] = False
            v    = list(self.tree.item(iid, 'values'))
            v[0] = self._CB_OFF
            self.tree.item(iid, values=v, tags=('desel',))
        self._maj_lbl_sel()

    def _maj_lbl_sel(self):
        n   = sum(1 for v in self._items_sel.values() if v)
        tot = len(self._items_sel)
        self.lbl_sel.config(text=f"{n}/{tot} sélectionnés")

    # ── Diagnostic ───────────────────────────────────────────────────────────

    def diagnostiquer_chemins(self):
        if not self.doublons:
            messagebox.showinfo("Diagnostic", "Aucun doublon chargé.")
            return
        if not self.file_index.indexed:
            messagebox.showinfo("Diagnostic", "Répertoire non indexé.")
            return

        win = tk.Toplevel(self.root)
        win.title("Diagnostic de correspondance des chemins")
        win.geometry("950x620")
        win.geometry(f"+{self.root.winfo_x()+50}+{self.root.winfo_y()+50}")

        fr = ttk.Frame(win, padding=10)
        fr.pack(fill=tk.BOTH, expand=True)
        ttk.Label(fr,
            text="Vérification chemin CSV ↔ fichier sur disque (double-cliquez pour ouvrir dans l'explorateur)",
            font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W, pady=(0, 6))

        vsb = ttk.Scrollbar(fr)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb = ttk.Scrollbar(fr, orient=tk.HORIZONTAL)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt = tk.Text(fr, wrap=tk.NONE, yscrollcommand=vsb.set, xscrollcommand=hsb.set,
                      font=('Consolas', 8), bg='white', fg=COLORS['text'])
        txt.pack(fill=tk.BOTH, expand=True)
        vsb.config(command=txt.yview)
        hsb.config(command=txt.xview)

        ok_count = err_count = 0
        lines = []
        for hash_md5, groupe in self.doublons.items():
            for copie in groupe['copies']:
                chemin_csv = (copie.get('chemin') or '').strip()
                nom        = copie.get('nom', '?')
                exact      = self.file_index.resoudre_chemin_exact(chemin_csv)
                if exact:
                    ok_count += 1
                    lines.append(f"✓ {nom}\n  CSV : {chemin_csv}\n  → {exact}\n")
                else:
                    err_count += 1
                    diag = self.file_index.diagnostiquer_chemin(chemin_csv)
                    lines.append(f"✗ {nom}\n  CSV : {chemin_csv}\n  → {diag}\n")

        total = ok_count + err_count
        summary = (
            f"Résultat : {ok_count}/{total} fichiers trouvés par chemin exact.\n"
            f"Les {err_count} autres seront cherchés par nom + MD5 (si disponible).\n"
            f"Dossier racine indexé : «{self.file_index._root_name}»\n\n"
        )
        txt.insert('1.0', summary + '\n'.join(lines))
        txt.config(state=tk.DISABLED)

    # ── Suppression ──────────────────────────────────────────────────────────

    def supprimer_doublons(self):
        if self.suppression_thread and self.suppression_thread.is_alive():
            messagebox.showinfo("Info", "Une suppression est déjà en cours.")
            return
        if not self.doublons:
            messagebox.showwarning("Attention", "Aucun doublon à supprimer !")
            return
        if not self.repertoire_source:
            messagebox.showerror("Erreur", "Sélectionnez le répertoire source !")
            return

        copies = self._get_copies_sel()
        if not copies:
            messagebox.showwarning("Aucune sélection",
                                   "Aucun fichier coché pour suppression.")
            return

        n        = len(copies)
        corbeille = self.use_trash.get() and SEND2TRASH_AVAILABLE
        mode     = "CORBEILLE (réversible)" if corbeille else "suppression DÉFINITIVE ⚠️"

        ok = messagebox.askyesno(
            "⚠️  CONFIRMATION",
            f"Supprimer {n:,} fichier(s) ?\n\n"
            f"📁 Répertoire : {self.repertoire_source}\n"
            f"🔐 Vérification MD5 : {'OUI' if self.verifier_md5.get() else 'NON'}\n"
            f"🗑️  Mode : {mode}\n\n"
            "Assurez-vous d'avoir une sauvegarde !"
        )
        if not ok:
            self.status_var.set("Suppression annulée")
            return

        self.cancellation_requested = False
        self._set_actions(running=True)
        self.suppression_thread = threading.Thread(
            target=self._thread_suppression,
            args=(copies, self.verifier_md5.get(), corbeille),
            daemon=True
        )
        self.suppression_thread.start()

    def _get_copies_sel(self):
        """Retourne la liste des copies cochées avec leurs métadonnées."""
        result = []
        for hash_md5, groupe in self.doublons.items():
            originaux = self._resoudre_originaux(groupe['original'])
            for copie in groupe['copies']:
                nom    = copie.get('nom', '?')
                chemin = copie.get('chemin', '?')
                iid    = self._copie_key.get((hash_md5, nom, chemin))
                if iid and self._items_sel.get(iid, True):
                    result.append({
                        'hash':     hash_md5,
                        'nom':      nom,
                        'chemin':   chemin,
                        'poids':    to_int(copie.get('poids', 0)),
                        'originaux': originaux,
                        'iid':      iid,
                    })
        return result

    def annuler_suppression(self):
        if self.suppression_thread and self.suppression_thread.is_alive():
            self.cancellation_requested = True
            self.status_var.set("Annulation demandée… arrêt après le fichier en cours")
            self.btn_annuler.config(state=tk.DISABLED)

    def _set_actions(self, running):
        etat = tk.DISABLED if running else tk.NORMAL
        self.btn_supprimer.config(state=etat)
        self.btn_rapport.config(  state=etat)
        self.btn_reset.config(    state=etat)
        self.btn_annuler.config(  state=tk.NORMAL if running else tk.DISABLED)

    def _resoudre_originaux(self, original):
        exact = self.file_index.resoudre_chemin_exact(original.get('chemin', ''))
        if exact:
            return {os.path.normcase(os.path.abspath(exact))}
        return set()

    def _thread_suppression(self, copies, verifier_md5, corbeille):
        supprimes = []
        erreurs   = []
        total     = len(copies)
        try:
            for i, copie in enumerate(copies):
                if self.cancellation_requested:
                    break
                nom        = copie['nom']
                chemin_csv = copie['chemin']
                hash_md5   = copie['hash']
                originaux  = copie['originaux']
                iid        = copie['iid']

                cible, raison = self._selectionner_cible(
                    nom, chemin_csv, hash_md5, originaux, verifier_md5
                )

                if cible is not None:
                    try:
                        if corbeille:
                            send2trash(os.path.abspath(cible))
                        else:
                            os.remove(cible)
                        supprimes.append({'nom': nom, 'chemin': cible, 'poids': copie['poids']})
                        self.root.after(0, self._set_iid_statut, iid, '✓ Supprimé', 'ok')
                    except PermissionError as e:
                        msg = f"Accès refusé (fichier verrouillé ?) : {e}"
                        erreurs.append({'nom': nom, 'chemin': cible, 'erreur': msg})
                        self.root.after(0, self._set_iid_statut, iid, '⚠ Accès refusé', 'err')
                    except Exception as e:
                        erreurs.append({'nom': nom, 'chemin': cible, 'erreur': str(e)[:200]})
                        self.root.after(0, self._set_iid_statut, iid, '✗ Erreur', 'err')
                else:
                    erreurs.append({'nom': nom, 'chemin_csv': chemin_csv, 'erreur': raison})
                    self.root.after(0, self._set_iid_statut, iid, '— Ignoré', 'ignore')

                pct = int(((i + 1) / total) * 100) if total else 100
                self.root.after(0, self._update_progress, pct, i + 1, total, nom)
        finally:
            self.root.after(0, self._finaliser, supprimes, erreurs, corbeille)

    def _selectionner_cible(self, nom, chemin_csv, hash_md5, originaux, verifier_md5):
        """Retourne (chemin_réel, None) ou (None, raison_d'échec)."""
        if not chemin_csv:
            return None, "Chemin absent dans le CSV"

        attendu = (hash_md5 or '').lower()

        def est_original(p):
            return os.path.normcase(os.path.abspath(p)) in originaux

        def md5_ok(p, force=False):
            if not attendu:
                return True
            if not verifier_md5 and not force:
                return True
            try:
                return calculer_md5(p).lower() == attendu
            except OSError:
                return False

        # 1) Correspondance exacte de chemin
        exact = self.file_index.resoudre_chemin_exact(chemin_csv)
        if exact:
            if est_original(exact):
                return None, "Ce fichier est l'original (protégé)"
            if not md5_ok(exact):
                return None, f"MD5 incorrect pour '{os.path.basename(exact)}'"
            return exact, None

        # 2) Repli par nom + MD5 obligatoire (même si option désactivée)
        candidats = self.file_index.candidats_par_nom(nom)
        for c in candidats:
            if not est_original(c) and md5_ok(c, force=True):
                return c, None

        if not candidats:
            return None, (f"Fichier '{nom}' introuvable dans le répertoire.\n"
                          f"Chemin CSV : {chemin_csv}")
        return None, (f"Fichier '{nom}' trouvé ({len(candidats)}) mais MD5 différent "
                      f"(attendu : {attendu[:16]}…)")

    def _update_progress(self, pct, cur, total, nom):
        self.progress_bar['value'] = pct
        fn = nom[:65] + ('…' if len(nom) > 65 else '')
        self.progress_text.config(text=f"Suppression : {cur:,}/{total:,} — {fn}")
        self.status_var.set(f"Suppression en cours : {cur:,}/{total:,}")

    def _set_iid_statut(self, iid, texte, tag):
        try:
            v    = list(self.tree.item(iid, 'values'))
            v[4] = texte
            self.tree.item(iid, values=v, tags=(tag,))
        except tk.TclError:
            pass

    def _finaliser(self, supprimes, erreurs, corbeille):
        espace = sum(to_int(s.get('poids', 0)) for s in supprimes)
        self.generer_rapport(supprimes, erreurs, espace, corbeille)

        annule = self.cancellation_requested
        msg  = "⏹️  TRAITEMENT ANNULÉ\n\n" if annule else "✅ TRAITEMENT TERMINÉ\n\n"
        msg += f"Mode : {'Corbeille' if corbeille else 'Suppression définitive'}\n"
        msg += f"✅ Fichiers supprimés : {len(supprimes):,}\n"
        msg += f"⚠️  Erreurs / ignorés  : {len(erreurs):,}\n"
        msg += f"💾 Espace libéré       : {format_size(espace)}\n\n"
        msg += f"📋 Rapport : {SCRIPT_DIR / 'Rapports_Doublons'}"

        messagebox.showinfo("Résultat" + (" (annulé)" if annule else ""), msg)
        self.progress_bar['value'] = 100
        self.progress_text.config(
            text=f"✓ Terminé — {len(supprimes):,} supprimés, {len(erreurs):,} erreurs"
        )
        self.status_var.set(
            f"✓ Terminé — {len(supprimes):,} supprimés, {len(erreurs):,} erreurs/ignorés"
        )
        self._set_actions(running=False)

    # ── Rapport ──────────────────────────────────────────────────────────────

    def generer_rapport(self, supprimes, erreurs, espace, corbeille):
        dossier = SCRIPT_DIR / "Rapports_Doublons"
        dossier.mkdir(parents=True, exist_ok=True)
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        rapport = dossier / f"Rapport_{ts}.txt"

        with open(rapport, 'w', encoding='utf-8') as f:
            f.write("╔════════════════════════════════════════════════════════════════╗\n")
            f.write("║    RAPPORT DE SUPPRESSION DES DOUBLONS ARCHIFILTRE v5.0        ║\n")
            f.write("╚════════════════════════════════════════════════════════════════╝\n\n")
            f.write(f"Date       : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write(f"CSV        : {Path(self.csv_path).name if self.csv_path else 'N/A'}\n")
            f.write(f"Répertoire : {self.repertoire_source}\n")
            f.write(f"Mode       : {'Corbeille (réversible)' if corbeille else 'Suppression définitive'}\n")
            f.write(f"Vérif. MD5 : {'Oui' if self.verifier_md5.get() else 'Non'}\n\n")
            f.write("RÉSUMÉ\n" + "─" * 65 + "\n")
            if self.doublons_stats:
                f.write(f"Fichiers analysés             : {len(self.donnees):,}\n")
                f.write(f"Groupes de doublons           : {self.doublons_stats.total_groupes:,}\n")
                f.write(f"Copies théoriques             : {self.doublons_stats.total_copies:,}\n")
            f.write(f"Fichiers réellement supprimés : {len(supprimes):,}\n")
            f.write(f"Erreurs / ignorés             : {len(erreurs):,}\n")
            f.write(f"Espace libéré                 : {format_size(espace)}\n\n")

            if supprimes:
                f.write("FICHIERS SUPPRIMÉS\n" + "─" * 65 + "\n")
                for i, item in enumerate(supprimes, 1):
                    f.write(f"{i:4}. ✓ {item['nom']}\n      {item['chemin']}\n\n")
            if erreurs:
                f.write("ERREURS / IGNORÉS\n" + "─" * 65 + "\n")
                for i, item in enumerate(erreurs, 1):
                    f.write(f"{i:4}. ✗ {item['nom']}\n")
                    if 'chemin' in item:
                        f.write(f"      {item['chemin']}\n")
                    elif 'chemin_csv' in item:
                        f.write(f"      CSV : {item['chemin_csv']}\n")
                    f.write(f"      → {item['erreur']}\n\n")
            f.write("─" * 65 + "\nFin du rapport\n")

    # ── Voir rapport ─────────────────────────────────────────────────────────

    def voir_rapport(self):
        dossier = SCRIPT_DIR / "Rapports_Doublons"
        if not dossier.exists():
            messagebox.showinfo("Info", "Aucun rapport généré pour le moment.")
            return
        fichiers = sorted(dossier.glob('*.txt'), key=lambda p: p.name, reverse=True)
        if not fichiers:
            messagebox.showinfo("Info", "Aucun rapport trouvé.")
            return

        chemin = fichiers[0] if len(fichiers) == 1 else self._choisir_rapport(fichiers)
        if not chemin:
            return

        try:
            contenu = chemin.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            contenu = chemin.read_text(encoding='latin-1')

        win = tk.Toplevel(self.root)
        win.title(f"Rapport : {chemin.name}")
        win.geometry("1000x720")
        win.geometry(f"+{self.root.winfo_x()+50}+{self.root.winfo_y()+50}")

        fr = ttk.Frame(win, padding=8)
        fr.pack(fill=tk.BOTH, expand=True)
        ttk.Label(fr, text=str(chemin), font=('Segoe UI', 8),
                  foreground=COLORS['accent1']).pack(anchor=tk.W, pady=(0, 4))

        vsb = ttk.Scrollbar(fr)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb = ttk.Scrollbar(fr, orient=tk.HORIZONTAL)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt = tk.Text(fr, wrap=tk.NONE, yscrollcommand=vsb.set, xscrollcommand=hsb.set,
                      font=('Consolas', 9), bg='white', fg=COLORS['text'])
        txt.pack(fill=tk.BOTH, expand=True)
        vsb.config(command=txt.yview)
        hsb.config(command=txt.xview)
        txt.insert('1.0', contenu)
        txt.config(state=tk.DISABLED)

        ttk.Button(fr, text="📂 Ouvrir le dossier des rapports",
                   command=lambda: ouvrir_explorateur(str(dossier))
                   ).pack(anchor=tk.W, pady=(6, 0))

    def _choisir_rapport(self, fichiers):
        win = tk.Toplevel(self.root)
        win.title("Choisir un rapport")
        win.geometry("500x320")
        win.geometry(f"+{self.root.winfo_x()+80}+{self.root.winfo_y()+80}")
        win.grab_set()
        choix = [None]

        ttk.Label(win, text="Sélectionnez le rapport à ouvrir :",
                  font=('Segoe UI', 10, 'bold')).pack(padx=10, pady=(10, 4))
        lb = tk.Listbox(win, font=('Consolas', 9), height=12)
        lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        for f in fichiers:
            lb.insert(tk.END, f.name)
        lb.selection_set(0)

        def valider():
            sel = lb.curselection()
            if sel:
                choix[0] = fichiers[sel[0]]
            win.destroy()

        ttk.Button(win, text="Ouvrir", command=valider, style='Primary.TButton').pack(pady=8)
        win.wait_window()
        return choix[0]

    # ── Divers ────────────────────────────────────────────────────────────────

    def reinitialiser(self):
        if self.suppression_thread and self.suppression_thread.is_alive():
            messagebox.showinfo("Info", "Impossible de réinitialiser pendant une suppression.")
            return
        if not messagebox.askyesno("Réinitialiser", "Réinitialiser l'application ?"):
            return

        self.csv_path = self.repertoire_source = None
        self.donnees  = []
        self.doublons = {}
        self.doublons_stats = None
        self._date_colonne  = None
        self.file_index     = FileIndex()
        self._items_sel.clear()
        self._copie_key.clear()

        self.csv_label.config(text="❌ Aucun fichier",    foreground=COLORS['error'])
        self.rep_label.config(text="❌ Aucun répertoire", foreground=COLORS['error'])
        for attr, val in [('label_fichiers', '0'), ('label_groupes', '0'),
                          ('label_a_supprimer', '0'), ('label_espace', '0 o')]:
            getattr(self, attr).config(text=val)
        self.progress_bar['value'] = 0
        self.progress_text.config(text="Prêt")
        self.tree.delete(*self.tree.get_children())
        self.lbl_sel.config(text="")
        self.status_var.set("Prêt — Chargez le CSV puis sélectionnez le répertoire source")

    def quitter(self):
        if self.suppression_thread and self.suppression_thread.is_alive():
            if not messagebox.askyesno("Attention",
                                       "Une suppression est en cours. Quitter quand même ?"):
                return
            self.cancellation_requested = True
        self.root.destroy()


# ── Lancement ─────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    ApplicationDoublons(root)
    root.mainloop()


if __name__ == "__main__":
    main()

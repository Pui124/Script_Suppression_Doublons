#!/usr/bin/env python3
"""
Application GUI pour supprimer les doublons Archifiltre - Version 5.1
Nouveautés v5.1 (refonte ergonomique) :
- Interface modernisée : cartes à fond blanc, boutons plats avec survol,
  interrupteurs à bascule, tuiles de statistiques, barre d'état intégrée
- Champ de filtre instantané sur nom/chemin (Ctrl+F, Échap pour effacer)
- Chargement CSV et indexation du répertoire en arrière-plan (interface fluide)
- Groupes repliables/dépliables (colonne flèche) + case à cocher de groupe
- Sélection conservée lors du filtrage (état par fichier, plus par ligne)
- Options de suppression déplacées à côté du bouton d'action

Corrections v5.0 :
- Bug corrigé : résolution de chemin format Archifiltre (/NomRacine/subdir/fichier)
- Bug corrigé : détection flexible de la colonne de date (plusieurs noms possibles)
- Suppression sélective : cocher/décocher chaque copie avant suppression
- Statut par fichier (OK/erreur) mis à jour en temps réel pendant suppression
- Fenêtre de diagnostic de correspondance chemin CSV <-> disque
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
    'primary':     '#EF7757',   # orange — action principale
    'primary_h':   '#E2653F',   # orange survol
    'primary_p':   '#C9532F',   # orange enfoncé
    'secondary':   '#292575',   # bleu foncé — en-têtes, titres
    'secondary_h': '#3B36A0',
    'accent1':     '#8E84AE',
    'accent2':     '#C6BFD8',
    'accent3':     '#E7E4EF',
    'bg':          '#F4F3F9',   # fond général
    'card':        '#FFFFFF',   # fond des cartes
    'border':      '#DEDAEB',   # bordure des cartes
    'muted':       '#8A87A3',   # texte secondaire
    'text':        '#2C2C2C',
    'success':     '#3E9D4D',
    'error':       '#D64541',
    'warning':     '#E58900',
}

FONT       = 'Segoe UI'

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


# ── Widgets personnalisés ─────────────────────────────────────────────────────

class FlatButton(tk.Button):
    """Bouton plat moderne avec effet de survol et curseur main."""

    KINDS = {
        # kind: (fond, texte, survol, enfoncé)
        'primary':   (COLORS['primary'],   'white',              COLORS['primary_h'],   COLORS['primary_p']),
        'secondary': (COLORS['secondary'], 'white',              COLORS['secondary_h'], '#1E1B5C'),
        'ghost':     (COLORS['card'],      COLORS['secondary'],  COLORS['accent3'],     COLORS['accent2']),
        'danger':    (COLORS['error'],     'white',              '#C13A36',             '#A32F2B'),
    }

    def __init__(self, parent, text='', command=None, kind='ghost', small=False, **kw):
        bg, fg, hover, pressed = self.KINDS[kind]
        font = (FONT, 9) if small else (FONT, 10, 'bold' if kind == 'primary' else 'normal')
        padx, pady = (10, 4) if small else (16, 7)
        super().__init__(
            parent, text=text, command=command,
            bg=bg, fg=fg, activebackground=pressed, activeforeground=fg,
            disabledforeground='#A5A3B8',
            relief='flat', bd=0, cursor='hand2',
            font=font, padx=padx, pady=pady,
            highlightthickness=1 if kind == 'ghost' else 0,
            highlightbackground=COLORS['border'],
            **kw
        )
        self._bg, self._fg, self._hover = bg, fg, hover
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)

    def _on_enter(self, _):
        if str(self['state']) != 'disabled':
            self.config(bg=self._hover)

    def _on_leave(self, _):
        if str(self['state']) != 'disabled':
            self.config(bg=self._bg)

    def set_enabled(self, enabled):
        if enabled:
            self.config(state=tk.NORMAL, bg=self._bg, fg=self._fg, cursor='hand2')
        else:
            self.config(state=tk.DISABLED, bg='#DEDCE9', cursor='arrow')


class ToggleRow(tk.Frame):
    """Interrupteur à bascule dessiné (Canvas) avec libellé et sous-texte."""

    def __init__(self, parent, variable, text, subtext='', state='normal', bg=None):
        bg = bg or COLORS['bg']
        super().__init__(parent, bg=bg)
        self.var    = variable
        self._state = state
        self._bg    = bg

        self.canvas = tk.Canvas(self, width=40, height=22, bg=bg,
                                highlightthickness=0,
                                cursor='hand2' if state == 'normal' else 'arrow')
        self.canvas.pack(side=tk.LEFT)

        lblf = tk.Frame(self, bg=bg)
        lblf.pack(side=tk.LEFT, padx=(8, 0))
        self.lbl = tk.Label(lblf, text=text, bg=bg, fg=COLORS['text'],
                            font=(FONT, 9, 'bold'), anchor='w', cursor='hand2')
        self.lbl.pack(anchor='w')
        self.sub = None
        if subtext:
            self.sub = tk.Label(lblf, text=subtext, bg=bg, fg=COLORS['muted'],
                                font=(FONT, 8), anchor='w')
            self.sub.pack(anchor='w')

        self.canvas.bind('<Button-1>', self._toggle)
        self.lbl.bind('<Button-1>', self._toggle)
        self._draw()

    def _toggle(self, _=None):
        if self._state == 'disabled':
            return
        self.var.set(not self.var.get())
        self._draw()

    def set_state(self, state):
        self._state = state
        cursor = 'hand2' if state == 'normal' else 'arrow'
        self.canvas.config(cursor=cursor)
        self.lbl.config(cursor=cursor,
                        fg=COLORS['text'] if state == 'normal' else COLORS['muted'])
        self._draw()

    def _draw(self):
        c = self.canvas
        c.delete('all')
        on    = bool(self.var.get())
        track = COLORS['primary'] if on else COLORS['accent2']
        if self._state == 'disabled':
            track = '#DDDBE8'
        # Piste arrondie : deux disques + rectangle central
        c.create_oval(1, 3, 19, 21, fill=track, outline=track)
        c.create_oval(21, 3, 39, 21, fill=track, outline=track)
        c.create_rectangle(10, 3, 30, 21, fill=track, outline=track)
        x = 24 if on else 3
        c.create_oval(x, 5, x + 14, 19, fill='white', outline='#EDEBF4')


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
    _CB_ON      = '☑'
    _CB_OFF     = '☐'
    _CB_PARTIEL = '▬'
    _STATUS_DEFAUT = ("Prêt — chargez le CSV puis le répertoire source.  "
                      "Astuce : double-clic sur une ligne pour l'ouvrir dans l'explorateur")

    def __init__(self, root):
        self.root = root
        self.root.title("Suppression des Doublons Archifiltre — v5.1")

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        ww = min(int(sw * 0.90), 1500)
        wh = min(int(sh * 0.90), 1000)
        self.root.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        self.root.minsize(940, 640)

        self.setup_style()

        self.csv_path          = None
        self.repertoire_source = None
        self.donnees           = []
        self.doublons          = {}
        self.doublons_stats    = None
        self.suppression_thread     = None
        self.cancellation_requested = False
        self._date_colonne     = None

        # État de sélection par copie, indépendant de l'affichage (survit au filtre)
        self._all_keys = []   # [(hash, nom, chemin), ...] toutes les copies
        self._sel      = {}   # {key: bool}
        self._statut   = {}   # {key: (texte, tag)} statut de suppression
        self._key_iid  = {}   # {key: item_id}  vue courante du Treeview
        self._iid_key  = {}   # {item_id: key}

        self._busy    = False   # chargement CSV / indexation en cours
        self._running = False   # suppression en cours
        self._filtre_job = None

        self.file_index = FileIndex()

        self.verifier_md5 = tk.BooleanVar(value=True)
        self.use_trash    = tk.BooleanVar(value=SEND2TRASH_AVAILABLE)

        self.setup_ui()
        self.root.protocol('WM_DELETE_WINDOW', self.quitter)

    # ── Style ────────────────────────────────────────────────────────────────

    def setup_style(self):
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('TFrame', background=COLORS['bg'])
        s.configure('Horizontal.TProgressbar',
                    background=COLORS['primary'], troughcolor=COLORS['accent3'],
                    borderwidth=0, thickness=8)
        s.configure('Treeview',
                    font=(FONT, 9), rowheight=26,
                    background=COLORS['card'], fieldbackground=COLORS['card'],
                    borderwidth=0, relief='flat')
        s.configure('Treeview.Heading',
                    font=(FONT, 9, 'bold'),
                    background=COLORS['secondary'], foreground='white',
                    relief='flat', padding=6)
        s.map('Treeview.Heading', background=[('active', COLORS['secondary_h'])])
        s.map('Treeview', background=[('selected', COLORS['accent3'])],
                          foreground=[('selected', COLORS['text'])])
        s.configure('TScrollbar',
                    background=COLORS['accent2'], troughcolor=COLORS['bg'],
                    borderwidth=0, arrowsize=12)
        s.map('TScrollbar', background=[('active', COLORS['accent1'])])
        self.root.configure(bg=COLORS['bg'])

    # ── Aides de construction ─────────────────────────────────────────────────

    def _carte(self, parent):
        """Carte à fond blanc avec bordure fine."""
        return tk.Frame(parent, bg=COLORS['card'],
                        highlightbackground=COLORS['border'], highlightthickness=1)

    def _carte_fichier(self, parent, icone, titre, action, texte_vide='Aucun fichier chargé'):
        """Carte de sélection de fichier/répertoire. Retourne (carte, label_état, bouton)."""
        card  = self._carte(parent)
        inner = tk.Frame(card, bg=COLORS['card'])
        inner.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        top = tk.Frame(inner, bg=COLORS['card'])
        top.pack(fill=tk.X)
        tk.Label(top, text=icone, bg=COLORS['card'],
                 font=(FONT, 13)).pack(side=tk.LEFT)
        tk.Label(top, text=titre, bg=COLORS['card'], fg=COLORS['secondary'],
                 font=(FONT, 10, 'bold')).pack(side=tk.LEFT, padx=(6, 0))
        btn = FlatButton(top, text='Parcourir…', command=action, kind='ghost', small=True)
        btn.pack(side=tk.RIGHT)

        lbl = tk.Label(inner, text=f'●  {texte_vide}', bg=COLORS['card'],
                       fg=COLORS['muted'], font=(FONT, 9),
                       anchor='w', justify=tk.LEFT, wraplength=560)
        lbl.pack(fill=tk.X, pady=(6, 0))
        return card, lbl, btn

    def _tuile_stat(self, parent, caption):
        """Tuile de statistique : liseré orange, grande valeur, légende."""
        card = self._carte(parent)
        tk.Frame(card, bg=COLORS['primary'], height=3).pack(fill=tk.X)
        val = tk.Label(card, text='0', bg=COLORS['card'], fg=COLORS['secondary'],
                       font=(FONT, 16, 'bold'))
        val.pack(pady=(8, 0), padx=12)
        tk.Label(card, text=caption, bg=COLORS['card'], fg=COLORS['muted'],
                 font=(FONT, 8)).pack(pady=(0, 8), padx=12)
        return card, val

    # ── Interface ─────────────────────────────────────────────────────────────

    def setup_ui(self):
        # ── Bandeau d'en-tête ──
        header = tk.Frame(self.root, bg=COLORS['secondary'])
        header.pack(fill=tk.X)
        hin = tk.Frame(header, bg=COLORS['secondary'])
        hin.pack(fill=tk.X, padx=18, pady=12)
        tk.Label(hin, text='Suppression des Doublons', bg=COLORS['secondary'],
                 fg='white', font=(FONT, 15, 'bold')).pack(side=tk.LEFT)
        tk.Label(hin, text=' v5.1 ', bg=COLORS['primary'], fg='white',
                 font=(FONT, 8, 'bold')).pack(side=tk.LEFT, padx=(10, 0), pady=(4, 0))
        tk.Label(hin, text='Nettoyage des fichiers dupliqués détectés par Archifiltre',
                 bg=COLORS['secondary'], fg=COLORS['accent2'],
                 font=(FONT, 9)).pack(side=tk.RIGHT, pady=(4, 0))
        tk.Frame(self.root, bg=COLORS['primary'], height=3).pack(fill=tk.X)

        body = tk.Frame(self.root, bg=COLORS['bg'])
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        # ── Rangée 1 : sources ──
        row1 = tk.Frame(body, bg=COLORS['bg'])
        row1.pack(fill=tk.X)
        row1.columnconfigure(0, weight=1, uniform='src')
        row1.columnconfigure(1, weight=1, uniform='src')

        card_csv, self.csv_label, self.btn_csv = self._carte_fichier(
            row1, '📋', 'Export CSV Archifiltre', self.charger_csv)
        card_csv.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        card_rep, self.rep_label, self.btn_rep = self._carte_fichier(
            row1, '📁', 'Répertoire source', self.charger_repertoire,
            texte_vide='Aucun répertoire chargé')
        card_rep.grid(row=0, column=1, sticky='nsew', padx=(5, 0))

        # ── Rangée 2 : statistiques ──
        row2 = tk.Frame(body, bg=COLORS['bg'])
        row2.pack(fill=tk.X, pady=(10, 0))
        for i in range(4):
            row2.columnconfigure(i, weight=1, uniform='stat')
        for i, (caption, attr) in enumerate([
            ('Fichiers analysés',   'label_fichiers'),
            ('Groupes de doublons', 'label_groupes'),
            ('Copies à supprimer',  'label_a_supprimer'),
            ('Espace à libérer',    'label_espace'),
        ]):
            card, val = self._tuile_stat(row2, caption)
            card.grid(row=0, column=i, sticky='nsew',
                      padx=(0 if i == 0 else 5, 0 if i == 3 else 5))
            setattr(self, attr, val)
        self.label_espace.config(text='0 o')

        # ── Rangée 3 : liste des doublons ──
        card_list = self._carte(body)
        card_list.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        list_in = tk.Frame(card_list, bg=COLORS['card'])
        list_in.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        tvbar = tk.Frame(list_in, bg=COLORS['card'])
        tvbar.pack(fill=tk.X, pady=(0, 6))
        tk.Label(tvbar, text='Doublons détectés', bg=COLORS['card'],
                 fg=COLORS['secondary'], font=(FONT, 11, 'bold')).pack(side=tk.LEFT)

        # Champ de filtre avec placeholder
        self._filtre_placeholder = '🔍  Filtrer par nom ou chemin…  (Ctrl+F)'
        self.filtre_entry = tk.Entry(
            tvbar, width=34, relief='flat', font=(FONT, 9),
            bg=COLORS['bg'], fg=COLORS['muted'],
            highlightthickness=1, highlightbackground=COLORS['border'],
            highlightcolor=COLORS['primary'], insertbackground=COLORS['text'])
        self.filtre_entry.pack(side=tk.LEFT, padx=(14, 0), ipady=4)
        self.filtre_entry.insert(0, self._filtre_placeholder)
        self._filtre_vide = True
        self.filtre_entry.bind('<FocusIn>',  self._filtre_focus_in)
        self.filtre_entry.bind('<FocusOut>', self._filtre_focus_out)
        self.filtre_entry.bind('<KeyRelease>', self._on_filtre)
        self.filtre_entry.bind('<Escape>', self._filtre_effacer)

        self.lbl_sel = tk.Label(tvbar, text='', bg=COLORS['card'],
                                fg=COLORS['muted'], font=(FONT, 9))
        self.lbl_sel.pack(side=tk.RIGHT)
        FlatButton(tvbar, text='🔍 Diagnostiquer les chemins',
                   command=self.diagnostiquer_chemins,
                   kind='ghost', small=True).pack(side=tk.RIGHT, padx=(0, 12))
        FlatButton(tvbar, text='☐ Aucun', command=self._tout_desel,
                   kind='ghost', small=True).pack(side=tk.RIGHT, padx=(0, 4))
        FlatButton(tvbar, text='☑ Tout', command=self._tout_sel,
                   kind='ghost', small=True).pack(side=tk.RIGHT, padx=(0, 4))

        # Treeview : colonne #0 = flèche de repli/dépli des groupes
        tv_frame = tk.Frame(list_in, bg=COLORS['card'])
        tv_frame.pack(fill=tk.BOTH, expand=True)
        tv_frame.rowconfigure(0, weight=1)
        tv_frame.columnconfigure(0, weight=1)

        cols = ('sel', 'nom', 'chemin', 'taille', 'statut')
        self.tree = ttk.Treeview(tv_frame, columns=cols, show='tree headings',
                                 selectmode='none')
        self.tree.heading('#0',     text='',              anchor=tk.W)
        self.tree.heading('sel',    text='☑',             anchor=tk.CENTER,
                          command=self._toggle_entete)
        self.tree.heading('nom',    text='Nom',           anchor=tk.W)
        self.tree.heading('chemin', text='Chemin (CSV)',  anchor=tk.W)
        self.tree.heading('taille', text='Taille',        anchor=tk.E)
        self.tree.heading('statut', text='Statut',        anchor=tk.W)
        self.tree.column('#0',     width=28,  minwidth=28, stretch=False)
        self.tree.column('sel',    width=36,  minwidth=32, stretch=False, anchor=tk.CENTER)
        self.tree.column('nom',    width=210, minwidth=100)
        self.tree.column('chemin', width=470, minwidth=150)
        self.tree.column('taille', width=100, minwidth=70, anchor=tk.E, stretch=False)
        self.tree.column('statut', width=170, minwidth=80)

        vsb = ttk.Scrollbar(tv_frame, orient='vertical',   command=self.tree.yview)
        hsb = ttk.Scrollbar(tv_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        # Tags de couleur
        self.tree.tag_configure('groupe', background='#EAECF8',
                                foreground=COLORS['secondary'], font=(FONT, 9, 'bold'))
        self.tree.tag_configure('sel',    background=COLORS['card'])
        self.tree.tag_configure('desel',  background='#F5F4F8', foreground=COLORS['muted'])
        self.tree.tag_configure('ok',     background='#DFF2E0')
        self.tree.tag_configure('err',    background='#FBE2DE')
        self.tree.tag_configure('ignore', background='#FFF0DC')

        self.tree.bind('<ButtonRelease-1>',        self._on_click)
        self.tree.bind('<Double-ButtonRelease-1>', self._on_dbl_click)
        self.tree.bind('<Control-a>', lambda e: (self._tout_sel(), 'break')[1])
        self.tree.bind('<Control-d>', lambda e: (self._tout_desel(), 'break')[1])
        self.root.bind('<Control-f>', lambda e: self.filtre_entry.focus_set())

        # ── Barre d'actions : options à gauche, boutons à droite ──
        act = tk.Frame(body, bg=COLORS['bg'])
        act.pack(fill=tk.X, pady=(10, 0))

        self.tg_md5 = ToggleRow(act, self.verifier_md5,
                                'Vérification MD5',
                                'contrôle du contenu avant suppression')
        self.tg_md5.pack(side=tk.LEFT, padx=(0, 18))
        trash_sub = 'suppression réversible' if SEND2TRASH_AVAILABLE \
                    else 'module send2trash absent → suppression DÉFINITIVE'
        self.tg_trash = ToggleRow(act, self.use_trash,
                                  'Envoyer à la corbeille', trash_sub,
                                  state='normal' if SEND2TRASH_AVAILABLE else 'disabled')
        self.tg_trash.pack(side=tk.LEFT)

        self.btn_supprimer = FlatButton(act, text='🗑  Supprimer la sélection',
                                        command=self.supprimer_doublons, kind='primary')
        self.btn_supprimer.pack(side=tk.RIGHT)
        self.btn_annuler = FlatButton(act, text='⛔ Annuler',
                                      command=self.annuler_suppression, kind='danger')
        self.btn_annuler.pack(side=tk.RIGHT, padx=(0, 8))
        self.btn_annuler.set_enabled(False)
        self.btn_rapport = FlatButton(act, text='📄 Voir rapport',
                                      command=self.voir_rapport, kind='ghost')
        self.btn_rapport.pack(side=tk.RIGHT, padx=(0, 8))
        self.btn_reset = FlatButton(act, text='🔄 Réinitialiser',
                                    command=self.reinitialiser, kind='ghost')
        self.btn_reset.pack(side=tk.RIGHT, padx=(0, 8))

        # ── Barre d'état : statut à gauche, progression à droite ──
        status = tk.Frame(self.root, bg=COLORS['card'])
        status.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Frame(status, bg=COLORS['border'], height=1).pack(fill=tk.X)
        sin = tk.Frame(status, bg=COLORS['card'])
        sin.pack(fill=tk.X, padx=14, pady=6)

        self.status_var = tk.StringVar(value=self._STATUS_DEFAUT)
        tk.Label(sin, text='●', bg=COLORS['card'], fg=COLORS['primary'],
                 font=(FONT, 9)).pack(side=tk.LEFT)
        tk.Label(sin, textvariable=self.status_var, bg=COLORS['card'],
                 fg=COLORS['text'], font=(FONT, 9),
                 anchor='w').pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)

        self.progress_bar = ttk.Progressbar(sin, mode='determinate', length=240)
        self.progress_bar.pack(side=tk.RIGHT, padx=(10, 0))
        self.progress_text = tk.Label(sin, text='Prêt', bg=COLORS['card'],
                                      fg=COLORS['muted'], font=(FONT, 9))
        self.progress_text.pack(side=tk.RIGHT)

    # ── États des contrôles ───────────────────────────────────────────────────

    def _actualiser_etats(self):
        libre = not self._busy and not self._running
        for b in (self.btn_csv, self.btn_rep, self.btn_supprimer,
                  self.btn_rapport, self.btn_reset):
            b.set_enabled(libre)
        self.btn_annuler.set_enabled(self._running)
        self.tg_md5.set_state('normal' if libre else 'disabled')
        self.tg_trash.set_state(
            'normal' if libre and SEND2TRASH_AVAILABLE else 'disabled')

    def _progress_anim(self, actif):
        """Bascule la barre de progression en mode animation indéterminée."""
        if actif:
            self.progress_bar.config(mode='indeterminate')
            self.progress_bar.start(14)
        else:
            self.progress_bar.stop()
            self.progress_bar.config(mode='determinate')

    # ── Chargement ───────────────────────────────────────────────────────────

    def _lire_csv(self, chemin):
        """Retourne (lignes_fichiers, nom_colonne_date). Exécuté hors thread UI."""
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
                    date_colonne = next(
                        (c for c in DATE_COLONNES if c in fieldnames), None
                    )
                    lignes = [
                        ligne for ligne in lecteur
                        if (ligne.get('fichier/répertoire') or '').strip() == 'fichier'
                    ]
                    return lignes, date_colonne
            except UnicodeDecodeError as e:
                derniere_erreur = e
                continue
        raise ValueError(f"Encodage CSV non reconnu : {derniere_erreur}")

    def charger_csv(self):
        if self._busy or self._running:
            return
        chemin = filedialog.askopenfilename(
            title="Ouvrir fichier CSV Archifiltre",
            filetypes=[("CSV", "*.csv"), ("Tous les fichiers", "*.*")]
        )
        if not chemin:
            return
        self._busy = True
        self._actualiser_etats()
        self.status_var.set("Chargement du CSV…")
        self.progress_text.config(text="Lecture du CSV…")
        self._progress_anim(True)
        threading.Thread(target=self._thread_csv, args=(chemin,), daemon=True).start()

    def _thread_csv(self, chemin):
        try:
            donnees, date_colonne = self._lire_csv(chemin)
            self.root.after(0, self._csv_charge, chemin, donnees, date_colonne)
        except Exception as e:
            self.root.after(0, self._csv_erreur, str(e))

    def _csv_charge(self, chemin, donnees, date_colonne):
        self._progress_anim(False)
        self._busy = False
        self._actualiser_etats()
        self.donnees       = donnees
        self.csv_path      = chemin
        self._date_colonne = date_colonne
        date_info = f"   |   date : « {date_colonne} »" if date_colonne \
                    else "   |   ⚠ colonne de date absente (ordre CSV conservé)"
        self.csv_label.config(
            text=f"●  {os.path.basename(chemin)}  —  {len(donnees):,} fichiers{date_info}",
            foreground=COLORS['success']
        )
        self.progress_text.config(text="CSV chargé")
        if self.repertoire_source:
            self.analyser_doublons()
        else:
            self.status_var.set(
                f"CSV chargé ({len(donnees):,} fichiers) — sélectionnez le répertoire source"
            )

    def _csv_erreur(self, message):
        self._progress_anim(False)
        self._busy = False
        self._actualiser_etats()
        self.progress_text.config(text="Erreur CSV")
        self.status_var.set("Erreur chargement CSV")
        messagebox.showerror("Erreur CSV", message)

    def charger_repertoire(self):
        if self._busy or self._running:
            return
        repertoire = filedialog.askdirectory(
            title="Sélectionner le répertoire source des archives"
        )
        if not repertoire:
            return
        self._busy = True
        self._actualiser_etats()
        self.status_var.set("Indexation du répertoire en cours…")
        self.progress_text.config(text="Indexation…")
        self._progress_anim(True)
        threading.Thread(target=self._thread_indexation,
                         args=(repertoire,), daemon=True).start()

    def _thread_indexation(self, repertoire):
        def _prog(n):
            self.root.after(0, lambda n=n: self.progress_text.config(
                text=f"Indexation : {n:,} fichiers…"))
        self.file_index.indexer_repertoire(repertoire, progress_callback=_prog)
        self.root.after(0, self._fin_indexation, repertoire)

    def _fin_indexation(self, repertoire):
        self._progress_anim(False)
        self._busy = False
        self._actualiser_etats()
        if not self.file_index.indexed:
            self.progress_text.config(text="Erreur indexation")
            self.status_var.set("Erreur lors de l'indexation du répertoire")
            messagebox.showerror("Erreur répertoire",
                                 "L'indexation du répertoire a échoué.")
            return
        self.repertoire_source = repertoire
        nom = os.path.basename(os.path.normpath(repertoire))
        self.rep_label.config(
            text=f"●  {nom}  —  {self.file_index.total_files:,} fichiers indexés",
            foreground=COLORS['success']
        )
        self.progress_text.config(text="Indexation terminée")
        if self.donnees:
            self.analyser_doublons()
        else:
            self.status_var.set(
                f"Répertoire indexé ({self.file_index.total_files:,} fichiers) — chargez le CSV"
            )

    # ── Analyse ───────────────────────────────────────────────────────────────

    def analyser_doublons(self):
        if not self.donnees or not self.repertoire_source:
            return
        self.status_var.set("Analyse en cours…")
        self.progress_bar['value'] = 0
        self.progress_text.config(text="Regroupement par MD5…")
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
        self._initialiser_selection()
        self.label_fichiers.config(    text=f"{len(self.donnees):,}")
        self.label_groupes.config(     text=f"{self.doublons_stats.total_groupes:,}")
        self.label_a_supprimer.config( text=f"{self.doublons_stats.total_copies:,}")
        self.label_espace.config(      text=self.doublons_stats.get_formatted_size())
        self.progress_bar['value'] = 100
        self.progress_text.config(
            text=f"{self.doublons_stats.total_groupes:,} groupes, "
                 f"{self.doublons_stats.total_copies:,} copies"
        )
        self.status_var.set(
            f"Analyse terminée — {self.doublons_stats.total_copies:,} fichiers à supprimer "
            f"dans {self.doublons_stats.total_groupes:,} groupes"
        )
        self._filtre_effacer()
        self._remplir_treeview()

    def _initialiser_selection(self):
        """Construit l'état de sélection (tout coché) pour les doublons courants."""
        self._all_keys = [
            (h, c.get('nom', '?'), c.get('chemin', '?'))
            for h, groupe in self.doublons.items()
            for c in groupe['copies']
        ]
        self._sel    = {k: True for k in self._all_keys}
        self._statut = {}

    def _remplir_treeview(self, filtre=''):
        self.tree.delete(*self.tree.get_children())
        self._key_iid.clear()
        self._iid_key.clear()
        f = (filtre or '').strip().lower()

        if not self.doublons:
            self.tree.insert('', 'end',
                values=('', '✨ Aucun doublon détecté', '', '', ''), tags=('groupe',))
            self._maj_lbl_sel()
            return

        # Au-delà de 200 groupes : replier par défaut (flèche pour déplier)
        ouvert   = bool(f) or self.doublons_stats.total_groupes <= 200
        visibles = 0

        for hash_md5, groupe in self.doublons.items():
            orig = groupe['original']
            if f:
                textes = [orig.get('nom', ''), orig.get('chemin', '')]
                for c in groupe['copies']:
                    textes += [c.get('nom', ''), c.get('chemin', '')]
                if not any(f in (t or '').lower() for t in textes):
                    continue
            visibles += 1

            gid = self.tree.insert('', 'end', values=(
                '',
                f"ORIGINAL : {orig.get('nom', '?')}",
                orig.get('chemin', '?'),
                format_size(to_int(orig.get('poids', 0))),
                f"Hash : {hash_md5[:16]}…",
            ), tags=('groupe',), open=ouvert)

            for copie in groupe['copies']:
                nom    = copie.get('nom', '?')
                chemin = copie.get('chemin', '?')
                key    = (hash_md5, nom, chemin)
                sel    = self._sel.get(key, True)
                statut, stag = self._statut.get(key, ('En attente', None))
                tag    = stag or ('sel' if sel else 'desel')
                iid    = self.tree.insert(gid, 'end', values=(
                    self._CB_ON if sel else self._CB_OFF,
                    nom,
                    chemin,
                    format_size(to_int(copie.get('poids', 0))),
                    statut,
                ), tags=(tag,))
                self._key_iid[key] = iid
                self._iid_key[iid] = key
            self._maj_case_groupe(gid)

        if f and not visibles:
            self.tree.insert('', 'end',
                values=('', f"Aucun résultat pour « {filtre.strip()} »", '', '', ''),
                tags=('groupe',))
        self._maj_lbl_sel()

    # ── Filtre ────────────────────────────────────────────────────────────────

    def _filtre_texte(self):
        if self._filtre_vide:
            return ''
        return self.filtre_entry.get()

    def _filtre_focus_in(self, _=None):
        if self._filtre_vide:
            self.filtre_entry.delete(0, tk.END)
            self.filtre_entry.config(fg=COLORS['text'])
            self._filtre_vide = False

    def _filtre_focus_out(self, _=None):
        if not self.filtre_entry.get().strip():
            self.filtre_entry.delete(0, tk.END)
            self.filtre_entry.insert(0, self._filtre_placeholder)
            self.filtre_entry.config(fg=COLORS['muted'])
            self._filtre_vide = True

    def _filtre_effacer(self, _=None):
        self.filtre_entry.delete(0, tk.END)
        self._filtre_vide = False
        self._filtre_focus_out()
        self.tree.focus_set()
        if self.doublons:
            self._remplir_treeview()

    def _on_filtre(self, _=None):
        if self._filtre_job:
            self.root.after_cancel(self._filtre_job)
        self._filtre_job = self.root.after(250, self._appliquer_filtre)

    def _appliquer_filtre(self):
        self._filtre_job = None
        if self.doublons:
            self._remplir_treeview(self._filtre_texte())

    # ── Treeview interactions ────────────────────────────────────────────────

    def _on_click(self, event):
        col  = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)
        if not item or col != '#1':
            return
        if item in self._iid_key:
            self._toggle(item)
        elif self.tree.get_children(item):
            # Case du groupe : (dé)coche toutes ses copies
            self._toggle_groupe(item)

    def _on_dbl_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item or self.tree.identify_column(event.x) == '#1':
            return
        vals = self.tree.item(item, 'values')
        if not vals or len(vals) < 3 or not vals[2]:
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
                "Utilisez 'Diagnostiquer les chemins' pour plus d'informations."
            )

    def _appliquer_sel(self, iid, sel):
        key = self._iid_key.get(iid)
        if key is None:
            return
        self._sel[key] = sel
        vals    = list(self.tree.item(iid, 'values'))
        vals[0] = self._CB_ON if sel else self._CB_OFF
        statut, stag = self._statut.get(key, (None, None))
        tag = stag or ('sel' if sel else 'desel')
        self.tree.item(iid, values=vals, tags=(tag,))

    def _toggle(self, iid):
        if self._running:
            return
        key = self._iid_key.get(iid)
        if key is None:
            return
        self._appliquer_sel(iid, not self._sel.get(key, True))
        self._maj_case_groupe(self.tree.parent(iid))
        self._maj_lbl_sel()

    def _toggle_groupe(self, gid):
        if self._running:
            return
        enfants = [i for i in self.tree.get_children(gid) if i in self._iid_key]
        if not enfants:
            return
        tous_coches = all(self._sel.get(self._iid_key[i], True) for i in enfants)
        for i in enfants:
            self._appliquer_sel(i, not tous_coches)
        self._maj_case_groupe(gid)
        self._maj_lbl_sel()

    def _toggle_entete(self):
        """Clic sur l'en-tête ☑ : (dé)coche toutes les lignes visibles."""
        if self._running or not self._iid_key:
            return
        tous_coches = all(self._sel.get(k, True) for k in self._iid_key.values())
        if tous_coches:
            self._tout_desel()
        else:
            self._tout_sel()

    def _tout_sel(self):
        self._sel_visibles(True)

    def _tout_desel(self):
        self._sel_visibles(False)

    def _sel_visibles(self, sel):
        if self._running:
            return
        parents = set()
        for iid in self._iid_key:
            self._appliquer_sel(iid, sel)
            parents.add(self.tree.parent(iid))
        for gid in parents:
            self._maj_case_groupe(gid)
        self._maj_lbl_sel()

    def _maj_case_groupe(self, gid):
        """Affiche sur la ligne de groupe l'état agrégé de ses copies."""
        if not gid:
            return
        etats = [self._sel.get(self._iid_key[i], True)
                 for i in self.tree.get_children(gid) if i in self._iid_key]
        if not etats:
            return
        car = self._CB_ON if all(etats) else (self._CB_OFF if not any(etats)
                                              else self._CB_PARTIEL)
        vals = list(self.tree.item(gid, 'values'))
        vals[0] = car
        self.tree.item(gid, values=vals)

    def _maj_lbl_sel(self):
        tot = len(self._all_keys)
        n   = sum(1 for k in self._all_keys if self._sel.get(k, True))
        self.lbl_sel.config(text=f"{n:,} cochés sur {tot:,}" if tot else '')

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
        win.configure(bg=COLORS['bg'])

        fr = tk.Frame(win, bg=COLORS['bg'])
        fr.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        tk.Label(fr, text="Vérification chemin CSV ↔ fichier sur disque",
                 bg=COLORS['bg'], fg=COLORS['secondary'],
                 font=(FONT, 11, 'bold')).pack(anchor=tk.W, pady=(0, 6))

        vsb = ttk.Scrollbar(fr)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb = ttk.Scrollbar(fr, orient=tk.HORIZONTAL)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt = tk.Text(fr, wrap=tk.NONE, yscrollcommand=vsb.set, xscrollcommand=hsb.set,
                      font=('Consolas', 8), bg=COLORS['card'], fg=COLORS['text'],
                      relief='flat', highlightthickness=1,
                      highlightbackground=COLORS['border'])
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

        n         = len(copies)
        corbeille = self.use_trash.get() and SEND2TRASH_AVAILABLE
        mode      = "CORBEILLE (réversible)" if corbeille else "suppression DÉFINITIVE ⚠️"

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
                key    = (hash_md5, nom, chemin)
                if self._sel.get(key, True):
                    result.append({
                        'hash':      hash_md5,
                        'nom':       nom,
                        'chemin':    chemin,
                        'poids':     to_int(copie.get('poids', 0)),
                        'originaux': originaux,
                        'key':       key,
                    })
        return result

    def annuler_suppression(self):
        if self.suppression_thread and self.suppression_thread.is_alive():
            self.cancellation_requested = True
            self.status_var.set("Annulation demandée… arrêt après le fichier en cours")
            self.btn_annuler.set_enabled(False)

    def _set_actions(self, running):
        self._running = running
        self._actualiser_etats()

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
                key        = copie['key']

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
                        self.root.after(0, self._set_statut, key, '✓ Supprimé', 'ok')
                    except PermissionError as e:
                        msg = f"Accès refusé (fichier verrouillé ?) : {e}"
                        erreurs.append({'nom': nom, 'chemin': cible, 'erreur': msg})
                        self.root.after(0, self._set_statut, key, '⚠ Accès refusé', 'err')
                    except Exception as e:
                        erreurs.append({'nom': nom, 'chemin': cible, 'erreur': str(e)[:200]})
                        self.root.after(0, self._set_statut, key, '✗ Erreur', 'err')
                else:
                    erreurs.append({'nom': nom, 'chemin_csv': chemin_csv, 'erreur': raison})
                    self.root.after(0, self._set_statut, key, '— Ignoré', 'ignore')

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
        fn = nom[:40] + ('…' if len(nom) > 40 else '')
        self.progress_text.config(text=f"{cur:,}/{total:,} — {fn}")
        self.status_var.set(f"Suppression en cours : {cur:,}/{total:,}")

    def _set_statut(self, key, texte, tag):
        """Enregistre le statut d'une copie et met à jour la ligne si visible."""
        self._statut[key] = (texte, tag)
        iid = self._key_iid.get(key)
        if not iid:
            return
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
            text=f"{len(supprimes):,} supprimés, {len(erreurs):,} erreurs"
        )
        self.status_var.set(
            f"Terminé — {len(supprimes):,} supprimés, {len(erreurs):,} erreurs/ignorés"
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
            f.write("║    RAPPORT DE SUPPRESSION DES DOUBLONS ARCHIFILTRE v5.1        ║\n")
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
        win.configure(bg=COLORS['bg'])

        fr = tk.Frame(win, bg=COLORS['bg'])
        fr.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        tk.Label(fr, text=str(chemin), bg=COLORS['bg'], font=(FONT, 8),
                 fg=COLORS['muted']).pack(anchor=tk.W, pady=(0, 4))

        btns = tk.Frame(fr, bg=COLORS['bg'])
        btns.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))
        FlatButton(btns, text='📂 Ouvrir le dossier des rapports',
                   command=lambda: ouvrir_explorateur(str(dossier)),
                   kind='ghost', small=True).pack(side=tk.LEFT)

        vsb = ttk.Scrollbar(fr)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb = ttk.Scrollbar(fr, orient=tk.HORIZONTAL)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt = tk.Text(fr, wrap=tk.NONE, yscrollcommand=vsb.set, xscrollcommand=hsb.set,
                      font=('Consolas', 9), bg=COLORS['card'], fg=COLORS['text'],
                      relief='flat', highlightthickness=1,
                      highlightbackground=COLORS['border'])
        txt.pack(fill=tk.BOTH, expand=True)
        vsb.config(command=txt.yview)
        hsb.config(command=txt.xview)
        txt.insert('1.0', contenu)
        txt.config(state=tk.DISABLED)

    def _choisir_rapport(self, fichiers):
        win = tk.Toplevel(self.root)
        win.title("Choisir un rapport")
        win.geometry("500x340")
        win.geometry(f"+{self.root.winfo_x()+80}+{self.root.winfo_y()+80}")
        win.configure(bg=COLORS['bg'])
        win.grab_set()
        choix = [None]

        tk.Label(win, text="Sélectionnez le rapport à ouvrir :", bg=COLORS['bg'],
                 fg=COLORS['secondary'],
                 font=(FONT, 10, 'bold')).pack(padx=12, pady=(12, 4))
        lb = tk.Listbox(win, font=('Consolas', 9), height=12, relief='flat',
                        bg=COLORS['card'], highlightthickness=1,
                        highlightbackground=COLORS['border'],
                        selectbackground=COLORS['accent2'],
                        selectforeground=COLORS['text'])
        lb.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        for f in fichiers:
            lb.insert(tk.END, f.name)
        lb.selection_set(0)

        def valider():
            sel = lb.curselection()
            if sel:
                choix[0] = fichiers[sel[0]]
            win.destroy()

        lb.bind('<Double-Button-1>', lambda e: valider())
        FlatButton(win, text='Ouvrir', command=valider, kind='primary').pack(pady=10)
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
        self._all_keys = []
        self._sel      = {}
        self._statut   = {}
        self._key_iid.clear()
        self._iid_key.clear()

        self.csv_label.config(text='●  Aucun fichier chargé',    foreground=COLORS['muted'])
        self.rep_label.config(text='●  Aucun répertoire chargé', foreground=COLORS['muted'])
        for attr, val in [('label_fichiers', '0'), ('label_groupes', '0'),
                          ('label_a_supprimer', '0'), ('label_espace', '0 o')]:
            getattr(self, attr).config(text=val)
        self.progress_bar['value'] = 0
        self.progress_text.config(text="Prêt")
        self.tree.delete(*self.tree.get_children())
        self.lbl_sel.config(text="")
        self._filtre_effacer()
        self.status_var.set(self._STATUS_DEFAUT)

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

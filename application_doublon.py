#!/usr/bin/env python3
"""
Application GUI pour supprimer les doublons Archifiltre - Version 4.1
Fonctionnalités:
- Charger CSV Archifiltre (validation des colonnes, encodage robuste)
- Sélectionner répertoire source (indexation O(n) en un seul passage)
- Analyse et suppression sécurisée des doublons
- Vérification MD5 du fichier réel avant suppression (option)
- Envoi à la corbeille via send2trash (option, réversible)
- L'original n'est jamais supprimé (exclusion explicite)
- Barre de progression en temps réel + annulation
- Optimisé pour les gros volumes (70k+ fichiers)
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import csv
import os
from collections import defaultdict
from datetime import datetime
import threading
import hashlib
from pathlib import Path

# Dépendance optionnelle : corbeille (suppression réversible)
try:
    from send2trash import send2trash
    SEND2TRASH_AVAILABLE = True
except ImportError:
    SEND2TRASH_AVAILABLE = False


# Colonnes attendues dans l'export CSV Archifiltre
COLONNES_REQUISES = {
    'fichier/répertoire', 'empreinte (MD5)', 'nom', 'chemin', 'poids (octets)'
}

# Formats de date tentés pour identifier l'original (le plus ancien)
FORMATS_DATE = (
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d',
    '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y',
    '%Y/%m/%d %H:%M:%S', '%Y/%m/%d',
)


# Palette de couleurs personnalisée
COLORS = {
    'primary': '#EF7757',      # Orange principal
    'secondary': '#292575',     # Bleu foncé
    'accent1': '#8E84AE',      # Gris-bleu
    'accent2': '#C6BFD8',      # Gris clair
    'accent3': '#E7E4EF',      # Très clair
    'bg': '#F5F3F8',           # Fond principal
    'text': '#2C2C2C',         # Texte foncé
    'success': '#4CAF50',       # Vert succès
    'error': '#F44336',         # Rouge erreur
    'warning': '#FF9800'        # Orange avertissement
}


def to_int(valeur):
    """Convertit une valeur CSV en entier, 0 si invalide/vide."""
    try:
        return int(str(valeur).strip() or 0)
    except (ValueError, TypeError):
        return 0


def parse_date(valeur):
    """Parse une date Archifiltre. Renvoie datetime.max si inconnue,
    afin que les dates non reconnues ne soient jamais choisies comme original."""
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
    """Calcule le MD5 d'un fichier par blocs (faible empreinte mémoire)."""
    h = hashlib.md5()
    with open(chemin, 'rb') as f:
        for bloc in iter(lambda: f.read(chunk), b''):
            h.update(bloc)
    return h.hexdigest()


def format_size(octets):
    """Formate une taille en octets de façon lisible."""
    octets = max(0, octets)
    if octets >= 1024 ** 3:
        return f"{octets / (1024 ** 3):.2f} GB"
    elif octets >= 1024 ** 2:
        return f"{octets / (1024 ** 2):.2f} MB"
    else:
        return f"{octets / 1024:.2f} KB"


class DoublonsStats:
    """Statistiques pré-calculées (un seul passage O(n))."""
    def __init__(self, doublons_dict):
        self.total_groupes = len(doublons_dict)
        self.total_copies = sum(len(d['copies']) for d in doublons_dict.values())
        self.espace_total = sum(
            to_int(f.get('poids', 0))
            for d in doublons_dict.values() for f in d['copies']
        )

    def get_formatted_size(self):
        return format_size(self.espace_total)


class FileIndex:
    """Index pré-calculé pour recherche rapide de fichiers.

    nom_to_path est une liste par nom : plusieurs fichiers peuvent partager
    le même nom dans des dossiers différents (cas courant). On ne perd donc
    aucun candidat, ce qui évite de supprimer le mauvais fichier.
    """
    def __init__(self):
        self.nom_to_path = defaultdict(list)   # {nom_fichier: [chemins...]}
        self.chemin_csv_to_real = {}           # {chemin_relatif: chemin_réel}
        self.total_files = 0
        self.indexed = False

    def indexer_repertoire(self, repertoire_root, progress_callback=None):
        """Indexe tous les fichiers du répertoire en un seul passage (os.walk)."""
        self.nom_to_path.clear()
        self.chemin_csv_to_real.clear()
        self.total_files = 0
        self.indexed = False

        try:
            current = 0
            for dirpath, _dirnames, filenames in os.walk(repertoire_root):
                for fname in filenames:
                    full = os.path.join(dirpath, fname)
                    self.nom_to_path[fname].append(full)
                    try:
                        rel = os.path.relpath(full, repertoire_root)
                        self.chemin_csv_to_real[rel] = full
                    except ValueError:
                        pass
                    current += 1
                    if progress_callback and current % 1000 == 0:
                        progress_callback(current)
            self.total_files = current
            self.indexed = True
        except Exception as e:
            print(f"Erreur indexation: {e}")
            self.indexed = False

    def resoudre_chemin_exact(self, chemin_csv):
        """Résout le chemin CSV vers un chemin réel par correspondance EXACTE
        du chemin relatif. Renvoie None si aucune correspondance fiable.

        Ne fait jamais de repli par nom : sert à identifier précisément un
        fichier (notamment l'original, qu'il ne faut surtout pas confondre
        avec un homonyme situé ailleurs)."""
        chemin_csv = (chemin_csv or '').strip()
        cles = (
            chemin_csv,
            chemin_csv.lstrip('\\').lstrip('/'),
            chemin_csv.replace('/', os.sep).replace('\\', os.sep),
        )
        for cle in cles:
            if cle and cle in self.chemin_csv_to_real:
                p = self.chemin_csv_to_real[cle]
                if os.path.isfile(p):
                    return p
        return None

    def candidats_par_nom(self, nom):
        """Renvoie tous les fichiers existants portant ce nom (repli de dernier
        recours, à n'utiliser qu'avec une vérification de contenu)."""
        result = []
        seen = set()
        for p in self.nom_to_path.get(nom, []):
            key = os.path.normcase(os.path.abspath(p))
            if key not in seen and os.path.isfile(p):
                seen.add(key)
                result.append(p)
        return result


class ApplicationDoublons:
    def __init__(self, root):
        self.root = root
        self.root.title("Suppression des Doublons Archifiltre - 4.1")

        # Configuration responsive
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.window_width = min(int(self.screen_width * 0.85), 1400)
        self.window_height = min(int(self.screen_height * 0.80), 950)
        self.root.geometry(f"{self.window_width}x{self.window_height}")

        # Centrer la fenêtre
        x = (self.screen_width - self.window_width) // 2
        y = (self.screen_height - self.window_height) // 2
        self.root.geometry(f"+{x}+{y}")

        self.setup_style()

        self.csv_path = None
        self.repertoire_source = None
        self.donnees = []
        self.doublons = {}
        self.suppression_thread = None
        self.cancellation_requested = False

        # Index pré-calculé et cache des stats
        self.file_index = FileIndex()
        self.doublons_stats = None

        # Options de suppression
        self.verifier_md5 = tk.BooleanVar(value=True)
        self.use_trash = tk.BooleanVar(value=SEND2TRASH_AVAILABLE)

        self.setup_ui()

    def setup_style(self):
        """Configurer le style personnalisé"""
        style = ttk.Style()
        style.theme_use('clam')

        style.configure('TFrame', background=COLORS['bg'])
        style.configure('TLabel', background=COLORS['bg'], foreground=COLORS['text'])
        style.configure('TCheckbutton', background=COLORS['bg'], foreground=COLORS['text'])
        style.configure('Header.TLabel', background=COLORS['secondary'], foreground='white',
                        font=('Segoe UI', 14, 'bold'), padding=10)
        style.configure('Title.TLabel', background=COLORS['bg'], foreground=COLORS['secondary'],
                        font=('Segoe UI', 12, 'bold'))
        style.configure('Subtitle.TLabel', background=COLORS['bg'], foreground=COLORS['accent1'],
                        font=('Segoe UI', 10))
        style.configure('Stat.TLabel', background=COLORS['accent3'], foreground=COLORS['secondary'],
                        font=('Segoe UI', 11, 'bold'), padding=5, relief='solid', borderwidth=1)

        style.configure('TButton', font=('Segoe UI', 9))
        style.map('TButton',
                  background=[('active', COLORS['primary'])],
                  foreground=[('active', 'white')])

        style.configure('Primary.TButton', background=COLORS['primary'])
        style.map('Primary.TButton',
                  background=[('active', '#D96B4D'), ('pressed', '#B35A42')])

        style.configure('Success.TButton', background=COLORS['success'])
        style.map('Success.TButton',
                  background=[('active', '#45A049'), ('pressed', '#3B8B40')])

        style.configure('Cancel.TButton', background=COLORS['error'])
        style.map('Cancel.TButton',
                  background=[('active', '#DA321C'), ('pressed', '#B52812')])

        style.configure('TLabelframe', background=COLORS['bg'], borderwidth=1, relief='solid')
        style.configure('TLabelframe.Label', background=COLORS['bg'], foreground=COLORS['secondary'],
                        font=('Segoe UI', 10, 'bold'))

        style.configure('TProgressbar', background=COLORS['primary'], troughcolor=COLORS['accent3'])

        self.root.configure(bg=COLORS['bg'])

    def setup_ui(self):
        """Créer l'interface"""
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(main_container, bg=COLORS['bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, padding="15")

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # En-tête
        header_frame = ttk.Frame(scrollable_frame)
        header_frame.pack(fill=tk.X, pady=(0, 20))

        header_label = ttk.Label(header_frame, text="🗂️  Suppression des Doublons Archifiltre",
                                 style='Header.TLabel')
        header_label.pack(fill=tk.X, padx=0, pady=0)

        subtitle = ttk.Label(header_frame, text="v4.1", style='Subtitle.TLabel')
        subtitle.pack(anchor=tk.W, padx=10, pady=(5, 0))

        # Section chargement
        load_frame = ttk.Labelframe(scrollable_frame, text="1. CHARGER LES FICHIERS", padding="15")
        load_frame.pack(fill=tk.X, pady=10)

        csv_row = ttk.Frame(load_frame)
        csv_row.pack(fill=tk.X, pady=8)
        ttk.Label(csv_row, text="📋 Fichier CSV Archifiltre:", style='Title.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.csv_label = ttk.Label(csv_row, text="❌ Aucun fichier", foreground=COLORS['error'],
                                   font=('Segoe UI', 9))
        self.csv_label.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Button(csv_row, text="Parcourir CSV", command=self.charger_csv).pack(side=tk.LEFT)

        rep_row = ttk.Frame(load_frame)
        rep_row.pack(fill=tk.X, pady=8)
        ttk.Label(rep_row, text="📁 Répertoire source:", style='Title.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.rep_label = ttk.Label(rep_row, text="❌ Aucun répertoire", foreground=COLORS['error'],
                                   font=('Segoe UI', 9))
        self.rep_label.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Button(rep_row, text="Parcourir dossier", command=self.charger_repertoire).pack(side=tk.LEFT)

        # Section analyse
        analysis_frame = ttk.Labelframe(scrollable_frame, text="2. ANALYSE", padding="15")
        analysis_frame.pack(fill=tk.X, pady=10)

        stats_grid = ttk.Frame(analysis_frame)
        stats_grid.pack(fill=tk.X)

        stats_data = [
            ("📊 Fichiers analysés", "label_fichiers", "0"),
            ("🔗 Groupes de doublons", "label_groupes", "0"),
            ("🗑️  Fichiers à supprimer", "label_a_supprimer", "0"),
            ("💾 Espace à libérer", "label_espace", "0 MB")
        ]

        for idx, (label_text, attr_name, default_val) in enumerate(stats_data):
            stat_frame = ttk.Frame(stats_grid)
            stat_frame.grid(row=idx // 2, column=idx % 2, sticky=tk.EW, padx=5, pady=8)
            ttk.Label(stat_frame, text=label_text, style='Subtitle.TLabel').pack(side=tk.LEFT, padx=(0, 8))
            label = ttk.Label(stat_frame, text=default_val, style='Stat.TLabel')
            setattr(self, attr_name, label)
            label.pack(side=tk.LEFT)

        stats_grid.columnconfigure(0, weight=1)
        stats_grid.columnconfigure(1, weight=1)

        # Section options
        options_frame = ttk.Labelframe(scrollable_frame, text="OPTIONS DE SUPPRESSION", padding="10")
        options_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Checkbutton(
            options_frame,
            text="🔐 Vérifier le MD5 du fichier réel avant suppression (recommandé, plus lent)",
            variable=self.verifier_md5
        ).pack(anchor=tk.W, pady=2)

        trash_text = "♻️  Envoyer à la corbeille (réversible)"
        if not SEND2TRASH_AVAILABLE:
            trash_text += "  —  send2trash non installé : suppression DÉFINITIVE"
        trash_cb = ttk.Checkbutton(
            options_frame, text=trash_text, variable=self.use_trash
        )
        trash_cb.pack(anchor=tk.W, pady=2)
        if not SEND2TRASH_AVAILABLE:
            trash_cb.configure(state=tk.DISABLED)

        # Barre de progression
        progress_frame = ttk.Frame(scrollable_frame)
        progress_frame.pack(fill=tk.X, pady=10)
        ttk.Label(progress_frame, text="Progression:", style='Subtitle.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=400)
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))
        self.progress_text = ttk.Label(progress_frame, text="Prêt", style='Subtitle.TLabel')
        self.progress_text.pack(anchor=tk.W)

        # Section doublons
        doublons_frame = ttk.Labelframe(scrollable_frame, text="3. DOUBLONS DÉTECTÉS", padding="10")
        doublons_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        scrollbar_text = ttk.Scrollbar(doublons_frame)
        scrollbar_text.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_doublons = tk.Text(doublons_frame, height=12, wrap=tk.WORD,
                                     yscrollcommand=scrollbar_text.set,
                                     bg='white', fg=COLORS['text'],
                                     font=('Consolas', 9), padx=10, pady=10)
        self.text_doublons.pack(fill=tk.BOTH, expand=True)
        scrollbar_text.config(command=self.text_doublons.yview)

        # Section actions
        action_frame = ttk.Frame(scrollable_frame)
        action_frame.pack(fill=tk.X, pady=20)

        self.btn_supprimer = ttk.Button(action_frame, text="🗑️  Supprimer les doublons",
                                        command=self.supprimer_doublons)
        self.btn_supprimer.pack(side=tk.LEFT, padx=5)

        self.btn_annuler = ttk.Button(action_frame, text="⛔ Annuler", style='Cancel.TButton',
                                      command=self.annuler_suppression, state=tk.DISABLED)
        self.btn_annuler.pack(side=tk.LEFT, padx=5)

        self.btn_rapport = ttk.Button(action_frame, text="📄 Voir rapport", command=self.voir_rapport)
        self.btn_rapport.pack(side=tk.LEFT, padx=5)

        self.btn_reset = ttk.Button(action_frame, text="🔄 Réinitialiser", command=self.reinitialiser)
        self.btn_reset.pack(side=tk.LEFT, padx=5)

        self.btn_quitter = ttk.Button(action_frame, text="❌ Quitter", command=self.quitter)
        self.btn_quitter.pack(side=tk.LEFT, padx=5)

        # Barre de statut
        self.status_var = tk.StringVar(value="Prêt - Chargez le CSV et sélectionnez le répertoire source")
        status_bar = ttk.Label(scrollable_frame, textvariable=self.status_var,
                               relief=tk.SUNKEN, style='Subtitle.TLabel',
                               background=COLORS['accent3'], padding=10)
        status_bar.pack(fill=tk.X, pady=(10, 0))

    # ----------------------------------------------------------------- chargement

    def _lire_csv(self, chemin):
        """Lit le CSV avec encodage robuste et valide les colonnes.

        Renvoie la liste des lignes de type 'fichier'. Lève ValueError si
        des colonnes requises manquent ou si l'encodage est illisible.
        """
        derniere_erreur = None
        for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
            try:
                with open(chemin, 'r', encoding=enc, newline='') as f:
                    lecteur = csv.DictReader(f, delimiter=';')
                    fieldnames = set(lecteur.fieldnames or [])
                    manquantes = COLONNES_REQUISES - fieldnames
                    if manquantes:
                        raise ValueError(
                            "Colonnes manquantes dans le CSV : "
                            + ", ".join(sorted(manquantes))
                            + "\n\nCe fichier est-il bien un export Archifiltre (séparateur ';') ?"
                        )
                    return [
                        ligne for ligne in lecteur
                        if (ligne.get('fichier/répertoire') or '').strip() == 'fichier'
                    ]
            except UnicodeDecodeError as e:
                derniere_erreur = e
                continue
        raise ValueError(f"Impossible de décoder le CSV (encodage non reconnu) : {derniere_erreur}")

    def charger_csv(self):
        """Charger un fichier CSV (optimisé pour gros volumes)"""
        chemin = filedialog.askopenfilename(
            title="Ouvrir fichier CSV Archifiltre",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not chemin:
            return

        try:
            self.status_var.set("Chargement du CSV en cours...")
            self.root.update_idletasks()

            self.donnees = self._lire_csv(chemin)
            self.csv_path = chemin

            self.csv_label.config(text=f"✓ {os.path.basename(chemin)}", foreground=COLORS['success'])

            if self.repertoire_source:
                self.analyser_doublons()
                self.afficher_doublons()
                self.status_var.set(f"✓ CSV chargé: {len(self.donnees):,} fichiers")
            else:
                self.status_var.set(f"CSV chargé ({len(self.donnees):,} fichiers) - Sélectionnez le répertoire")
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur lecture CSV:\n{str(e)[:300]}")
            self.status_var.set("Erreur lors du chargement du CSV")

    def charger_repertoire(self):
        """Charger un répertoire source"""
        repertoire = filedialog.askdirectory(title="Sélectionner le répertoire source des archives")
        if not repertoire:
            return

        try:
            self.status_var.set("Indexation du répertoire en cours...")
            self.root.update_idletasks()

            self.repertoire_source = repertoire

            def _progress(n):
                self.progress_text.config(text=f"Indexation: {n:,} fichiers...")
                self.root.update_idletasks()

            self.file_index.indexer_repertoire(repertoire, progress_callback=_progress)
            self.progress_text.config(text="Indexation terminée")

            nom_rep = os.path.basename(repertoire) or repertoire
            self.rep_label.config(
                text=f"✓ {nom_rep} ({self.file_index.total_files:,} fichiers indexés)",
                foreground=COLORS['success']
            )

            if self.donnees:
                self.analyser_doublons()
                self.afficher_doublons()
                self.status_var.set("✓ Répertoire et CSV chargés - Prêt à analyser")
            else:
                self.status_var.set(f"Répertoire chargé ({self.file_index.total_files:,} fichiers) - Chargez le CSV")
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur sélection répertoire:\n{str(e)[:300]}")
            self.status_var.set("Erreur lors du chargement du répertoire")

    # ----------------------------------------------------------------- analyse

    def analyser_doublons(self):
        """Analyser et identifier les doublons (optimisé pour gros volumes)"""
        if not self.donnees or not self.repertoire_source:
            return

        self.status_var.set("Analyse en cours...")
        self.progress_bar['value'] = 0
        self.progress_text.config(text="Regroupement des empreintes MD5...")
        self.root.update_idletasks()

        groupes = defaultdict(list)
        total = len(self.donnees)
        batch_size = 5000

        for i, fichier in enumerate(self.donnees):
            hash_md5 = (fichier.get('empreinte (MD5)') or '').strip()
            if hash_md5:
                groupes[hash_md5].append({
                    'nom': fichier.get('nom', '?'),
                    'chemin': fichier.get('chemin', '?'),
                    'poids': to_int(fichier.get('poids (octets)', 0)),
                    'date': fichier.get('date de première modification', ''),
                })

            if (i + 1) % batch_size == 0:
                progress = int((i + 1) / total * 100)
                self.progress_bar['value'] = progress
                self.progress_text.config(text=f"Analyse: {i + 1:,}/{total:,} fichiers")
                self.root.update_idletasks()

        self.doublons = {}
        for hash_md5, fichiers in groupes.items():
            if len(fichiers) > 1:
                # Trier par DATE RÉELLE (parsée) : le plus ancien = original conservé
                fichiers_tries = sorted(fichiers, key=lambda f: parse_date(f.get('date', '')))
                self.doublons[hash_md5] = {
                    'original': fichiers_tries[0],
                    'copies': fichiers_tries[1:],
                }

        self.doublons_stats = DoublonsStats(self.doublons)

        self.label_fichiers.config(text=f"{len(self.donnees):,}")
        self.label_groupes.config(text=f"{self.doublons_stats.total_groupes:,}")
        self.label_a_supprimer.config(text=f"{self.doublons_stats.total_copies:,}")
        self.label_espace.config(text=self.doublons_stats.get_formatted_size())

        self.progress_bar['value'] = 100
        self.progress_text.config(text=f"✓ Analyse complète: {self.doublons_stats.total_groupes:,} groupes détectés")
        self.status_var.set(f"Analyse terminée - {self.doublons_stats.total_copies:,} fichiers à supprimer")

    def afficher_doublons(self):
        """Afficher la liste des doublons (optimisé)"""
        self.text_doublons.config(state=tk.NORMAL)
        self.text_doublons.delete('1.0', tk.END)

        if not self.doublons:
            self.text_doublons.insert('1.0', "✨ Aucun doublon détecté!\n\nVos fichiers sont uniques.")
            self.text_doublons.config(state=tk.DISABLED)
            return

        total_copies = self.doublons_stats.total_copies

        if total_copies > 100:
            texte = "📊 RÉSUMÉ\n"
            texte += f"{'=' * 60}\n"
            texte += f"Répertoire: {self.repertoire_source}\n"
            texte += f"Groupes de doublons: {self.doublons_stats.total_groupes:,}\n"
            texte += f"Fichiers à supprimer: {total_copies:,}\n\n"
            texte += "⚠️  Trop de doublons pour afficher la liste complète.\n"
            texte += "Un rapport détaillé sera généré après suppression.\n\n"
            texte += "📋 PREMIER GROUPE (exemple):\n"
            texte += f"{'-' * 60}\n"

            first_group = next(iter(self.doublons.values()))
            texte += f"Original conservé: {first_group['original'].get('nom', '?')}\n"
            texte += f"Chemin: {first_group['original'].get('chemin', '?')}\n"
            texte += f"Taille: {to_int(first_group['original'].get('poids', 0)) / 1024:.2f} KB\n\n"
            texte += f"À supprimer ({len(first_group['copies'])} copies):\n"
            for i, copie in enumerate(first_group['copies'][:5], 1):
                texte += f"  {i}. {copie.get('nom', '?')} ({to_int(copie.get('poids', 0)) / 1024:.2f} KB)\n"
            if len(first_group['copies']) > 5:
                texte += f"  ... et {len(first_group['copies']) - 5} autres fichiers\n"
        else:
            texte = f"📋 DOUBLONS DÉTECTÉS ({self.doublons_stats.total_groupes:,} groupes)\n"
            texte += f"{'=' * 60}\n"
            texte += f"Répertoire: {self.repertoire_source}\n\n"

            for i, (hash_md5, groupe) in enumerate(self.doublons.items(), 1):
                texte += f"{i}. Groupe (Hash: {hash_md5[:16]}...)\n"
                texte += f"   ✓ Original conservé: {groupe['original'].get('nom', '?')}\n"
                texte += f"     Chemin: {groupe['original'].get('chemin', '?')}\n"
                texte += f"     Taille: {to_int(groupe['original'].get('poids', 0)) / 1024:.2f} KB\n"
                texte += f"   À supprimer ({len(groupe['copies'])} copie(s)):\n"
                for copie in groupe['copies']:
                    texte += f"     ❌ {copie.get('nom', '?')}\n"
                    texte += f"        {copie.get('chemin', '?')}\n"
                    texte += f"        {to_int(copie.get('poids', 0)) / 1024:.2f} KB\n"
                texte += "\n"

        self.text_doublons.insert('1.0', texte)
        self.text_doublons.config(state=tk.DISABLED)

    # ----------------------------------------------------------------- suppression

    def supprimer_doublons(self):
        """Lancer la suppression avec progress bar (threading)"""
        if self.suppression_thread and self.suppression_thread.is_alive():
            messagebox.showinfo("Info", "Une suppression est déjà en cours.")
            return

        if not self.doublons:
            messagebox.showwarning("Attention", "Aucun doublon à supprimer!")
            return

        if not self.repertoire_source:
            messagebox.showerror("Erreur", "Sélectionnez le répertoire source!")
            return

        total = self.doublons_stats.total_copies
        corbeille = self.use_trash.get() and SEND2TRASH_AVAILABLE
        mode = "envoyés à la CORBEILLE (réversible)" if corbeille else "supprimés DÉFINITIVEMENT (irréversible)"

        dialog = messagebox.askyesno(
            "⚠️  CONFIRMATION IMPORTANTE",
            f"Êtes-vous ABSOLUMENT CERTAIN de vouloir traiter {total:,} fichiers?\n\n"
            f"📁 Répertoire: {self.repertoire_source}\n"
            f"🔗 Groupes: {self.doublons_stats.total_groupes:,}\n"
            f"🔐 Vérification MD5: {'OUI' if self.verifier_md5.get() else 'NON'}\n\n"
            f"Les fichiers seront {mode}.\n"
            f"Assurez-vous d'avoir une sauvegarde."
        )
        if not dialog:
            self.status_var.set("Suppression annulée par l'utilisateur")
            return

        self.cancellation_requested = False
        self._set_actions_state(running=True)

        self.suppression_thread = threading.Thread(
            target=self._thread_suppression,
            args=(total, self.verifier_md5.get(), corbeille),
        )
        self.suppression_thread.daemon = True
        self.suppression_thread.start()

    def annuler_suppression(self):
        """Demander l'arrêt de la suppression en cours."""
        if self.suppression_thread and self.suppression_thread.is_alive():
            self.cancellation_requested = True
            self.status_var.set("Annulation demandée... arrêt après le fichier en cours")
            self.btn_annuler.config(state=tk.DISABLED)

    def _set_actions_state(self, running):
        """Active/désactive les boutons selon qu'une suppression tourne."""
        etat_normal = tk.DISABLED if running else tk.NORMAL
        self.btn_supprimer.config(state=etat_normal)
        self.btn_rapport.config(state=etat_normal)
        self.btn_reset.config(state=etat_normal)
        self.btn_annuler.config(state=tk.NORMAL if running else tk.DISABLED)

    def _resoudre_originaux(self, original):
        """Renvoie le chemin réel (normalisé) de l'original, par correspondance
        EXACTE de chemin, pour ne jamais le supprimer.

        On n'utilise PAS le repli par nom ici : sinon tous les homonymes de
        l'original (très fréquents entre doublons) seraient protégés et plus
        aucune copie ne serait supprimée."""
        exact = self.file_index.resoudre_chemin_exact(original.get('chemin', ''))
        if exact:
            return {os.path.normcase(os.path.abspath(exact))}
        return set()

    def _thread_suppression(self, total, verifier_md5, corbeille):
        """Thread de suppression sécurisée avec rapport en temps réel."""
        supprimes = []
        erreurs = []
        current = 0

        try:
            for hash_md5, groupe in self.doublons.items():
                if self.cancellation_requested:
                    break

                originaux = self._resoudre_originaux(groupe['original'])

                for fichier in groupe['copies']:
                    if self.cancellation_requested:
                        break

                    current += 1
                    nom = fichier.get('nom', '?')
                    chemin_csv = (fichier.get('chemin') or '').strip()

                    cible = self._selectionner_cible(
                        nom, chemin_csv, hash_md5, originaux, verifier_md5, erreurs
                    )
                    if cible is not None:
                        try:
                            if corbeille:
                                send2trash(os.path.abspath(cible))
                            else:
                                os.remove(cible)
                            supprimes.append({
                                'nom': nom, 'chemin': cible,
                                'poids': to_int(fichier.get('poids', 0)),
                            })
                        except Exception as e:
                            erreurs.append({'nom': nom, 'chemin': cible, 'erreur': str(e)[:120]})

                    progress = int((current / total) * 100) if total else 100
                    self.root.after(0, self._update_progress, progress, current, total, nom)
        finally:
            self.root.after(0, self._finaliser_suppression, supprimes, erreurs, corbeille)

    def _selectionner_cible(self, nom, chemin_csv, hash_md5, originaux, verifier_md5, erreurs):
        """Choisit le fichier à supprimer, en excluant l'original et (option)
        en vérifiant le MD5. Renvoie None si rien de sûr.

        Stratégie : chemin EXACT d'abord (cas normal et le plus sûr), puis
        repli par nom en dernier recours, toujours filtré par contenu."""
        if not chemin_csv:
            erreurs.append({'nom': nom, 'erreur': 'Pas de chemin dans le CSV'})
            return None

        attendu = (hash_md5 or '').lower()

        def est_original(p):
            return os.path.normcase(os.path.abspath(p)) in originaux

        def md5_ok(p):
            if not verifier_md5:
                return True
            try:
                return calculer_md5(p).lower() == attendu
            except OSError:
                return False

        # 1) Correspondance exacte de chemin (cas normal)
        exact = self.file_index.resoudre_chemin_exact(chemin_csv)
        if exact and not est_original(exact) and md5_ok(exact):
            return exact

        # 2) Repli par nom : seulement les fichiers au bon contenu, jamais l'original
        for c in self.file_index.candidats_par_nom(nom):
            if not est_original(c) and md5_ok(c):
                return c

        message = ('Aucun fichier correspondant (chemin/MD5) - ignoré par sécurité'
                   if verifier_md5 else 'Introuvable (ou seul l\'original existe)')
        erreurs.append({'nom': nom, 'chemin_csv': chemin_csv, 'erreur': message})
        return None

    def _update_progress(self, progress, current, total, current_file):
        """Mettre à jour la barre de progression (appelée sur le thread principal)."""
        self.progress_bar['value'] = progress
        self.progress_text.config(text=f"Suppression: {current:,}/{total:,} - {current_file[:40]}...")

    def _finaliser_suppression(self, supprimes, erreurs, corbeille):
        """Finaliser la suppression et afficher les résultats."""
        # Espace réellement libéré = somme des fichiers effectivement supprimés
        espace_libere = sum(to_int(s.get('poids', 0)) for s in supprimes)
        self.generer_rapport(supprimes, erreurs, espace_libere, corbeille)

        annule = self.cancellation_requested
        titre = "Résultat" + (" (annulé)" if annule else "")
        mode = "Corbeille" if corbeille else "Suppression définitive"

        message = "✓ TRAITEMENT TERMINÉ!\n\n"
        if annule:
            message = "⏹️  TRAITEMENT ANNULÉ\n\n"
        message += f"Mode: {mode}\n"
        message += f"✅ Fichiers traités: {len(supprimes):,}\n"
        message += f"⚠️  Erreurs/ignorés: {len(erreurs):,}\n"
        message += f"💾 Espace libéré: {format_size(espace_libere)}\n\n"
        message += "📋 Rapport: Rapports_Doublons/\n"

        messagebox.showinfo(titre, message)

        self.progress_bar['value'] = 100
        self.progress_text.config(text=f"✓ Terminé - {len(supprimes):,} fichiers traités")
        self.status_var.set(f"✓ Terminé - {len(supprimes):,} traités, {len(erreurs)} erreurs/ignorés")
        self._set_actions_state(running=False)

    def generer_rapport(self, supprimes, erreurs, espace_libere, corbeille):
        """Générer le rapport de suppression."""
        dossier = Path("Rapports_Doublons")
        dossier.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        chemin_rapport = dossier / f"Rapport_{timestamp}.txt"

        with open(chemin_rapport, 'w', encoding='utf-8') as f:
            f.write("╔════════════════════════════════════════════════════════════════╗\n")
            f.write("║    RAPPORT DE SUPPRESSION DES DOUBLONS ARCHIFILTRE v4.1        ║\n")
            f.write("╚════════════════════════════════════════════════════════════════╝\n\n")

            f.write(f"Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write(f"CSV: {Path(self.csv_path).name if self.csv_path else 'N/A'}\n")
            f.write(f"Répertoire: {self.repertoire_source}\n")
            f.write(f"Mode: {'Corbeille (réversible)' if corbeille else 'Suppression définitive'}\n")
            f.write(f"Vérification MD5: {'Oui' if self.verifier_md5.get() else 'Non'}\n\n")

            f.write("RÉSUMÉ\n")
            f.write("─────────────────────────────────────────────────────────────────\n")
            f.write(f"Fichiers analysés: {len(self.donnees):,}\n")
            f.write(f"Groupes doublons détectés: {self.doublons_stats.total_groupes:,}\n")
            f.write(f"Fichiers à supprimer (théorique): {self.doublons_stats.total_copies:,}\n")
            f.write(f"Fichiers réellement traités: {len(supprimes):,}\n")
            f.write(f"Erreurs/ignorés: {len(erreurs):,}\n")
            f.write(f"Espace réellement libéré: {format_size(espace_libere)}\n\n")

            if supprimes:
                f.write("FICHIERS TRAITÉS\n")
                f.write("─────────────────────────────────────────────────────────────────\n")
                for i, item in enumerate(supprimes, 1):
                    f.write(f"{i}. ✓ {item['nom']}\n")
                    f.write(f"   {item['chemin']}\n\n")

            if erreurs:
                f.write("ERREURS / IGNORÉS\n")
                f.write("─────────────────────────────────────────────────────────────────\n")
                for i, item in enumerate(erreurs, 1):
                    f.write(f"{i}. ❌ {item['nom']}\n")
                    if 'chemin' in item:
                        f.write(f"   {item['chemin']}\n")
                    elif 'chemin_csv' in item:
                        f.write(f"   CSV: {item['chemin_csv']}\n")
                    f.write(f"   Erreur: {item['erreur']}\n\n")

            f.write("─────────────────────────────────────────────────────────────────\n")
            f.write("Fin du rapport\n")

    # ----------------------------------------------------------------- divers

    def voir_rapport(self):
        """Ouvrir le dernier rapport"""
        dossier = Path("Rapports_Doublons")
        if not dossier.exists():
            messagebox.showinfo("Info", "Aucun rapport généré pour le moment")
            return

        fichiers = sorted([f.name for f in dossier.glob('*.txt')], reverse=True)
        if not fichiers:
            messagebox.showinfo("Info", "Aucun rapport trouvé")
            return

        chemin = dossier / fichiers[0]
        try:
            contenu = chemin.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            contenu = chemin.read_text(encoding='latin-1')

        win = tk.Toplevel(self.root)
        win.title(f"Rapport: {chemin.name}")
        win.geometry("900x700")
        x = self.root.winfo_x() + 50
        y = self.root.winfo_y() + 50
        win.geometry(f"+{x}+{y}")

        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text = tk.Text(frame, wrap=tk.WORD, yscrollcommand=scrollbar.set,
                       font=('Consolas', 9), bg='white', fg=COLORS['text'])
        text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=text.yview)

        text.insert('1.0', contenu)
        text.config(state=tk.DISABLED)

    def reinitialiser(self):
        """Réinitialiser l'application"""
        if self.suppression_thread and self.suppression_thread.is_alive():
            messagebox.showinfo("Info", "Impossible de réinitialiser pendant une suppression.")
            return

        reponse = messagebox.askyesno(
            "Réinitialiser",
            "Êtes-vous sûr de vouloir réinitialiser l'application?\n\n"
            "Les données actuelles seront perdues."
        )
        if not reponse:
            return

        self.csv_path = None
        self.repertoire_source = None
        self.donnees = []
        self.doublons = {}
        self.doublons_stats = None
        self.file_index = FileIndex()

        self.csv_label.config(text="❌ Aucun fichier", foreground=COLORS['error'])
        self.rep_label.config(text="❌ Aucun répertoire", foreground=COLORS['error'])

        self.label_fichiers.config(text="0")
        self.label_groupes.config(text="0")
        self.label_a_supprimer.config(text="0")
        self.label_espace.config(text="0 MB")

        self.progress_bar['value'] = 0
        self.progress_text.config(text="Prêt")

        self.text_doublons.config(state=tk.NORMAL)
        self.text_doublons.delete('1.0', tk.END)
        self.text_doublons.insert('1.0', "Chargez un CSV et sélectionnez un répertoire pour commencer")
        self.text_doublons.config(state=tk.DISABLED)

        self.status_var.set("Prêt - Chargez le CSV et sélectionnez le répertoire source")

    def quitter(self):
        """Quitter l'application"""
        if self.suppression_thread and self.suppression_thread.is_alive():
            reponse = messagebox.askyesno(
                "Attention",
                "Une suppression est en cours.\nÊtes-vous sûr de vouloir quitter?"
            )
            if not reponse:
                return
            self.cancellation_requested = True

        self.root.destroy()


def main():
    root = tk.Tk()
    ApplicationDoublons(root)
    root.mainloop()


if __name__ == "__main__":
    main()

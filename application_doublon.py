#!/usr/bin/env python3
"""
Application GUI pour supprimer les doublons Archifiltre - Version 4.0
Fonctionnalités:
- Charger CSV Archifiltre
- Sélectionner répertoire source
- Analyse et suppression intelligente des doublons
- Barre de progression en temps réel
- Optimisé pour les gros volumes (70k+ fichiers)
- Interface responsive et moderne
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import csv
import os
from collections import defaultdict
from datetime import datetime
import threading
from queue import Queue
import hashlib
from pathlib import Path
import json


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


class DoublonsStats:
    """Cache des statistiques pour éviter les recalculs O(n²)"""
    def __init__(self, doublons_dict):
        self.total_groupes = len(doublons_dict)
        self.total_copies = sum(len(d['copies']) for d in doublons_dict.values())
        self.espace_total = sum(int(f.get('poids', 0)) for d in doublons_dict.values() for f in d['copies'])
        self._cached = True
    
    def get_formatted_size(self):
        """Retourne l'espace formaté"""
        if self.espace_total > 1024**3:
            return f"{self.espace_total / (1024**3):.2f} GB"
        elif self.espace_total > 1024**2:
            return f"{self.espace_total / (1024**2):.2f} MB"
        else:
            return f"{self.espace_total / 1024:.2f} KB"


class FileIndex:
    """Index pré-calculé pour recherche ultra-rapide de fichiers"""
    def __init__(self):
        self.nom_to_path = {}      # {nom_fichier: chemin_complet}
        self.chemin_csv_to_real = {} # {chemin_csv: chemin_réel}
        self.indexed = False
    
    def indexer_repertoire(self, repertoire_root, progress_callback=None):
        """Indexe TOUS les fichiers du répertoire (O(n) une seule fois)"""
        self.nom_to_path.clear()
        self.chemin_csv_to_real.clear()
        
        try:
            root_path = Path(repertoire_root)
            total_files = sum(1 for _ in root_path.rglob('*') if _.is_file())
            
            current = 0
            for fichier_path in root_path.rglob('*'):
                if fichier_path.is_file():
                    nom = fichier_path.name
                    chemin_str = str(fichier_path)
                    
                    # Index par nom
                    self.nom_to_path[nom] = chemin_str
                    
                    # Index par chemin relatif
                    try:
                        rel_path = fichier_path.relative_to(root_path)
                        self.chemin_csv_to_real[str(rel_path)] = chemin_str
                    except ValueError:
                        pass
                    
                    current += 1
                    if progress_callback and current % 1000 == 0:
                        progress_callback(current, total_files)
            
            self.indexed = True
        except Exception as e:
            print(f"Erreur indexation: {e}")
            self.indexed = False
    
    def trouver_fichier(self, nom, chemin_csv):
        """Retrouve fichier en O(1) depuis l'index"""
        # Essayer d'abord le chemin CSV exact
        if chemin_csv in self.chemin_csv_to_real:
            path = self.chemin_csv_to_real[chemin_csv]
            if Path(path).exists():
                return path
        
        # Nettoyer le chemin CSV et réessayer
        chemin_clean = chemin_csv.lstrip('\\').lstrip('/')
        if chemin_clean in self.chemin_csv_to_real:
            path = self.chemin_csv_to_real[chemin_clean]
            if Path(path).exists():
                return path
        
        # Fallback sur nom de fichier
        if nom in self.nom_to_path:
            path = self.nom_to_path[nom]
            if Path(path).exists():
                return path
        
        return None


class ApplicationDoublons:
    def __init__(self, root):
        self.root = root
        self.root.title("Suppression des Doublons Archifiltre - 4.0")
        
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
        
        # Configurer le style
        self.setup_style()
        
        self.csv_path = None
        self.repertoire_source = None
        self.donnees = []
        self.doublons = {}
        self.suppression_queue = Queue()
        self.suppression_thread = None
        self.cancellation_requested = False
        
        # ===== OPTIMISATIONS =====
        self.file_index = FileIndex()  # Index pré-calculé
        self.doublons_stats = None      # Cache des stats
        self.csv_hash = None            # Hash du CSV pour détecter changements
        self.repertoire_hash = None     # Hash du répertoire pour détecter changements
        
        self.setup_ui()
    
    def setup_style(self):
        """Configurer le style personnalisé"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Couleurs de base
        style.configure('TFrame', background=COLORS['bg'])
        style.configure('TLabel', background=COLORS['bg'], foreground=COLORS['text'])
        style.configure('Header.TLabel', background=COLORS['secondary'], foreground='white', 
                       font=('Segoe UI', 14, 'bold'), padding=10)
        style.configure('Title.TLabel', background=COLORS['bg'], foreground=COLORS['secondary'],
                       font=('Segoe UI', 12, 'bold'))
        style.configure('Subtitle.TLabel', background=COLORS['bg'], foreground=COLORS['accent1'],
                       font=('Segoe UI', 10))
        style.configure('Stat.TLabel', background=COLORS['accent3'], foreground=COLORS['secondary'],
                       font=('Segoe UI', 11, 'bold'), padding=5, relief='solid', borderwidth=1)
        
        # Boutons
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
        
        # LabelFrames
        style.configure('TLabelframe', background=COLORS['bg'], borderwidth=1, relief='solid')
        style.configure('TLabelframe.Label', background=COLORS['bg'], foreground=COLORS['secondary'],
                       font=('Segoe UI', 10, 'bold'))
        
        # Progress bar
        style.configure('TProgressbar', background=COLORS['primary'], troughcolor=COLORS['accent3'])
        
        self.root.configure(bg=COLORS['bg'])

    def setup_ui(self):
        """Créer l'interface"""
        # Frame principal avec scrollbar
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Canvas avec scrollbar pour responsiveness
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
        header_frame.configure(style='TFrame')
        
        header_label = ttk.Label(header_frame, text="🗂️  Suppression des Doublons Archifiltre",
                                style='Header.TLabel')
        header_label.pack(fill=tk.X, padx=0, pady=0)
        
        subtitle = ttk.Label(header_frame, text="v4.0",
                           style='Subtitle.TLabel')
        subtitle.pack(anchor=tk.W, padx=10, pady=(5, 0))
        
        # Section chargement
        load_frame = ttk.Labelframe(scrollable_frame, text="1. CHARGER LES FICHIERS", padding="15")
        load_frame.pack(fill=tk.X, pady=10)
        
        # Row 1: CSV
        csv_row = ttk.Frame(load_frame)
        csv_row.pack(fill=tk.X, pady=8)
        
        ttk.Label(csv_row, text="📋 Fichier CSV Archifiltre:", style='Title.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.csv_label = ttk.Label(csv_row, text="❌ Aucun fichier", foreground=COLORS['error'], 
                                  font=('Segoe UI', 9))
        self.csv_label.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Button(csv_row, text="Parcourir CSV", command=self.charger_csv).pack(side=tk.LEFT)
        
        # Row 2: Répertoire
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
        
        # Statistiques en grille responsive
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
        
        ttk.Button(action_frame, text="🗑️  Supprimer les doublons", 
                  command=self.supprimer_doublons).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="📄 Voir rapport", 
                  command=self.voir_rapport).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="🔄 Réinitialiser", 
                  command=self.reinitialiser).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="❌ Quitter", 
                  command=self.quitter).pack(side=tk.LEFT, padx=5)
        
        # Barre de statut
        self.status_var = tk.StringVar(value="Prêt - Chargez le CSV et sélectionnez le répertoire source")
        status_bar = ttk.Label(scrollable_frame, textvariable=self.status_var, 
                              relief=tk.SUNKEN, style='Subtitle.TLabel', 
                              background=COLORS['accent3'], padding=10)
        status_bar.pack(fill=tk.X, pady=(10, 0))
    
    def charger_csv(self):
        """Charger un fichier CSV (optimisé pour gros volumes)"""
        chemin = filedialog.askopenfilename(title="Ouvrir fichier CSV Archifiltre", 
                                           filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not chemin:
            return
        
        try:
            self.status_var.set("Chargement du CSV en cours...")
            self.root.update()
            
            self.csv_path = chemin
            self.donnees = []
            
            # Lecture optimisée avec encodage robuste
            try:
                with open(chemin, 'r', encoding='utf-8') as f:
                    lecteur = csv.DictReader(f, delimiter=';')
                    for ligne in lecteur:
                        if ligne.get('fichier/répertoire', '').strip() == 'fichier':
                            self.donnees.append(ligne)
            except UnicodeDecodeError:
                # Fallback sur latin-1
                with open(chemin, 'r', encoding='latin-1') as f:
                    lecteur = csv.DictReader(f, delimiter=';')
                    for ligne in lecteur:
                        if ligne.get('fichier/répertoire', '').strip() == 'fichier':
                            self.donnees.append(ligne)
            
            self.csv_label.config(text=f"✓ {os.path.basename(chemin)}", 
                                 foreground=COLORS['success'])
            
            if self.repertoire_source:
                self.analyser_doublons()
                self.afficher_doublons()
                self.status_var.set(f"✓ CSV chargé: {len(self.donnees):,} fichiers")
            else:
                self.status_var.set(f"CSV chargé ({len(self.donnees):,} fichiers) - Sélectionnez le répertoire")
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur lecture CSV:\n{str(e)[:200]}")
            self.status_var.set("Erreur lors du chargement du CSV")
    
    def charger_repertoire(self):
        """Charger un répertoire source"""
        repertoire = filedialog.askdirectory(title="Sélectionner le répertoire source des archives")
        if not repertoire:
            return
        
        try:
            self.status_var.set("Indexation du répertoire en cours...")
            self.root.update()
            
            self.repertoire_source = repertoire
            
            # Indexer TOUS les fichiers une seule fois (optimisation CRITIQUE)
            self.file_index.indexer_repertoire(repertoire)
            
            nom_rep = os.path.basename(repertoire) if repertoire != "/" else repertoire
            self.rep_label.config(text=f"✓ {nom_rep} ({len(self.file_index.nom_to_path):,} fichiers indexés)", 
                                 foreground=COLORS['success'])
            
            if self.donnees:
                self.analyser_doublons()
                self.afficher_doublons()
                self.status_var.set(f"✓ Répertoire et CSV chargés - Prêt à analyser")
            else:
                self.status_var.set(f"Répertoire chargé ({len(self.file_index.nom_to_path):,} fichiers) - Chargez le CSV")
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur sélection répertoire:\n{str(e)[:200]}")
            self.status_var.set("Erreur lors du chargement du répertoire")
    
    def analyser_doublons(self):
        """Analyser et identifier les doublons (optimisé pour gros volumes)"""
        if not self.donnees or not self.repertoire_source:
            return
        
        self.status_var.set("Analyse en cours...")
        self.progress_bar['value'] = 0
        self.progress_text.config(text="Analyse des empreintes MD5...")
        self.root.update()
        
        groupes = defaultdict(list)
        total = len(self.donnees)
        
        # Traiter par batch pour éviter les pics de mémoire
        batch_size = 5000
        for i, fichier in enumerate(self.donnees):
            hash_md5 = fichier.get('empreinte (MD5)', '').strip()
            if hash_md5:
                # ===== OPTIMISATION: Stocker SEULEMENT les métadonnées essentielles =====
                metadata = {
                    'nom': fichier.get('nom', '?'),
                    'chemin': fichier.get('chemin', '?'),
                    'poids': int(fichier.get('poids (octets)', 0)),
                    'date': fichier.get('date de première modification', '')
                }
                groupes[hash_md5].append(metadata)
            
            # Mise à jour de la progression tous les 5000 fichiers
            if (i + 1) % batch_size == 0:
                progress = int((i + 1) / total * 100)
                self.progress_bar['value'] = progress
                self.progress_text.config(text=f"Analyse: {i+1:,}/{total:,} fichiers")
                self.root.update()
        
        self.doublons = {}
        for hash_md5, fichiers in groupes.items():
            if len(fichiers) > 1:
                # Trier par date pour identifier le plus ancien comme original
                fichiers_tries = sorted(fichiers, 
                                       key=lambda f: f.get('date', ''),
                                       reverse=False)
                self.doublons[hash_md5] = {
                    'original': fichiers_tries[0],
                    'copies': fichiers_tries[1:]
                }
        
        # ===== OPTIMISATION: Créer un cache des statistiques (évite O(n²)) =====
        self.doublons_stats = DoublonsStats(self.doublons)
        
        # Utiliser le cache au lieu de recalculer
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
        
        # ===== OPTIMISATION: Utiliser le cache de stats au lieu de recalculer =====
        total_copies = self.doublons_stats.total_copies
        
        # Pour les gros volumes, afficher un résumé
        if total_copies > 100:
            texte = f"📊 RÉSUMÉ\n"
            texte += f"{'='*60}\n"
            texte += f"Répertoire: {self.repertoire_source}\n"
            texte += f"Groupes de doublons: {self.doublons_stats.total_groupes:,}\n"
            texte += f"Fichiers à supprimer: {total_copies:,}\n\n"
            texte += f"⚠️  Trop de doublons pour afficher la liste complète.\n"
            texte += f"Un rapport détaillé sera généré après suppression.\n\n"
            texte += f"📋 PREMIER GROUPE (exemple):\n"
            texte += f"{'-'*60}\n"
            
            # Afficher seulement le premier groupe en exemple
            first_group = next(iter(self.doublons.values()))
            texte += f"Original conservé: {first_group['original'].get('nom', '?')}\n"
            texte += f"Chemin: {first_group['original'].get('chemin', '?')}\n"
            texte += f"Taille: {first_group['original'].get('poids', 0)/1024:.2f} KB\n\n"
            texte += f"À supprimer ({len(first_group['copies'])} copies):\n"
            for i, copie in enumerate(first_group['copies'][:5], 1):
                texte += f"  {i}. {copie.get('nom', '?')} ({copie.get('poids', 0)/1024:.2f} KB)\n"
            if len(first_group['copies']) > 5:
                texte += f"  ... et {len(first_group['copies']) - 5} autres fichiers\n"
        else:
            texte = f"📋 DOUBLONS DÉTECTÉS ({self.doublons_stats.total_groupes:,} groupes)\n"
            texte += f"{'='*60}\n"
            texte += f"Répertoire: {self.repertoire_source}\n\n"
            
            for i, (hash_md5, groupe) in enumerate(self.doublons.items(), 1):
                texte += f"{i}. Groupe (Hash: {hash_md5[:16]}...)\n"
                texte += f"   ✓ Original conservé: {groupe['original'].get('nom', '?')}\n"
                texte += f"     Chemin: {groupe['original'].get('chemin', '?')}\n"
                texte += f"     Taille: {groupe['original'].get('poids', 0)/1024:.2f} KB\n"
                texte += f"   À supprimer ({len(groupe['copies'])} copie(s)):\n"
                for copie in groupe['copies']:
                    texte += f"     ❌ {copie.get('nom', '?')}\n"
                    texte += f"        {copie.get('chemin', '?')}\n"
                    texte += f"        {copie.get('poids', 0)/1024:.2f} KB\n"
                texte += "\n"
        
        self.text_doublons.insert('1.0', texte)
        self.text_doublons.config(state=tk.DISABLED)
    
    def supprimer_doublons(self):
        """Lancer la suppression avec progress bar (threading)"""
        if not self.doublons:
            messagebox.showwarning("Attention", "Aucun doublon à supprimer!")
            return
        
        if not self.repertoire_source:
            messagebox.showerror("Erreur", "Sélectionnez le répertoire source!")
            return
        
        # ===== OPTIMISATION: Utiliser le cache au lieu de recalculer =====
        total = self.doublons_stats.total_copies
        
        # Dialog de confirmation avec plus de détails
        dialog = messagebox.askyesno("⚠️  CONFIRMATION IMPORTANTE",
            f"Êtes-vous ABSOLUMENT CERTAIN de vouloir supprimer {total:,} fichiers?\n\n"
            f"📁 Répertoire: {self.repertoire_source}\n"
            f"🔗 Groupes: {self.doublons_stats.total_groupes:,}\n\n"
            f"⚠️  Cette action est IRRÉVERSIBLE!\n"
            f"     Assurez-vous d'avoir une sauvegarde.")
        
        if not dialog:
            self.status_var.set("Suppression annulée par l'utilisateur")
            return
        
        # Désactiver les boutons pendant la suppression
        self.cancellation_requested = False
        
        # Lancer la suppression en thread
        self.suppression_thread = threading.Thread(target=self._thread_suppression, args=(total,))
        self.suppression_thread.daemon = True
        self.suppression_thread.start()
    
    def _format_size(self, octets):
        """Formate une taille en octets"""
        if octets > 1024**3:
            return f"{octets / (1024**3):.2f} GB"
        elif octets > 1024**2:
            return f"{octets / (1024**2):.2f} MB"
        else:
            return f"{octets / 1024:.2f} KB"
    
    def _thread_suppression(self, total):
        """Thread de suppression avec rapport en temps réel"""
        supprimes = []
        erreurs = []
        
        current = 0
        for groupe in self.doublons.values():
            for fichier in groupe['copies']:
                if self.cancellation_requested:
                    break
                
                chemin_csv = fichier.get('chemin', '').strip()
                nom = fichier.get('nom', '?')
                
                if not chemin_csv:
                    erreurs.append({'nom': nom, 'erreur': 'Pas de chemin dans CSV'})
                    current += 1
                    continue
                
                # Chercher le fichier
                chemin_fichier = self.trouver_fichier(nom, chemin_csv)
                
                if not chemin_fichier:
                    erreurs.append({'nom': nom, 'chemin_csv': chemin_csv, 'erreur': 'Introuvable'})
                    current += 1
                    continue
                
                if not os.path.isfile(chemin_fichier):
                    erreurs.append({'nom': nom, 'chemin': chemin_fichier, 'erreur': 'Pas un fichier'})
                    current += 1
                    continue
                
                try:
                    os.remove(chemin_fichier)
                    supprimes.append({'nom': nom, 'chemin': chemin_fichier})
                except Exception as e:
                    erreurs.append({'nom': nom, 'chemin': chemin_fichier, 'erreur': str(e)[:100]})
                
                # Mise à jour de la progress bar
                current += 1
                progress = int((current / total) * 100)
                self.root.after(0, self._update_progress, progress, current, total, nom)
            
            if self.cancellation_requested:
                break
        
        # Générer le rapport
        self.root.after(0, self._finaliser_suppression, supprimes, erreurs)
    
    def _update_progress(self, progress, current, total, current_file):
        """Mettre à jour la barre de progression (appelée depuis le thread)"""
        self.progress_bar['value'] = progress
        self.progress_text.config(text=f"Suppression: {current:,}/{total:,} - {current_file[:40]}...")
        self.root.update_idletasks()
    
    def _finaliser_suppression(self, supprimes, erreurs):
        """Finaliser la suppression et afficher les résultats"""
        self.generer_rapport(supprimes, erreurs)
        
        # ===== OPTIMISATION: Utiliser le cache au lieu de recalculer =====
        espace_libere = self.doublons_stats.espace_total if self.doublons_stats else 0
        size_text = self._format_size(espace_libere)
        
        message = f"✓ SUPPRESSION TERMINÉE!\n\n"
        message += f"✅ Suppressions réussies: {len(supprimes):,}\n"
        message += f"⚠️  Erreurs: {len(erreurs):,}\n"
        message += f"💾 Espace libéré: {size_text}\n\n"
        message += f"📋 Rapport: Rapports_Doublons/\n"
        
        messagebox.showinfo("Résultat", message)
        
        self.progress_bar['value'] = 100
        self.progress_text.config(text=f"✓ Suppression terminée - {len(supprimes):,} fichiers supprimés")
        self.status_var.set(f"✓ Suppression terminée - {len(supprimes):,} fichiers supprimés, {len(erreurs)} erreurs")
    
    def trouver_fichier(self, nom, chemin_csv):
        """Chercher le fichier dans le répertoire source (OPTIMISÉ - O(1) avec index)"""
        # ===== OPTIMISATION CRITIQUE: Utiliser l'index au lieu de os.walk() =====
        return self.file_index.trouver_fichier(nom, chemin_csv)
    
    def generer_rapport(self, supprimes, erreurs):
        """Générer le rapport de suppression"""
        dossier = "Rapports_Doublons"
        if not Path(dossier).exists():
            Path(dossier).mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        chemin_rapport = Path(dossier) / f"Rapport_{timestamp}.txt"
        
        # ===== OPTIMISATION: Utiliser le cache de stats =====
        with open(chemin_rapport, 'w', encoding='utf-8') as f:
            f.write("╔════════════════════════════════════════════════════════════════╗\n")
            f.write("║    RAPPORT DE SUPPRESSION DES DOUBLONS ARCHIFILTRE v4.0+       ║\n")
            f.write("╚════════════════════════════════════════════════════════════════╝\n\n")
            
            f.write(f"Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write(f"CSV: {Path(self.csv_path).name if self.csv_path else 'N/A'}\n")
            f.write(f"Répertoire: {self.repertoire_source}\n\n")
            
            f.write("RÉSUMÉ\n")
            f.write("─────────────────────────────────────────────────────────────────\n")
            f.write(f"Fichiers analysés: {len(self.donnees):,}\n")
            f.write(f"Groupes doublons détectés: {self.doublons_stats.total_groupes:,}\n")
            f.write(f"Fichiers à supprimer: {self.doublons_stats.total_copies:,}\n")
            f.write(f"Fichiers supprimés: {len(supprimes):,}\n")
            f.write(f"Erreurs: {len(erreurs):,}\n")
            f.write(f"Espace libéré: {self.doublons_stats.get_formatted_size()}\n\n")
            
            if supprimes:
                f.write("FICHIERS SUPPRIMÉS\n")
                f.write("─────────────────────────────────────────────────────────────────\n")
                for i, item in enumerate(supprimes, 1):
                    f.write(f"{i}. ✓ {item['nom']}\n")
                    f.write(f"   {item['chemin']}\n\n")
            
            if erreurs:
                f.write("ERREURS\n")
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
        
        # Positionner la fenêtre
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
        reponse = messagebox.askyesno("Réinitialiser", 
                                     "Êtes-vous sûr de vouloir réinitialiser l'application?\n\n"
                                     "Les données actuelles seront perdues.")
        if not reponse:
            return
        
        self.csv_path = None
        self.repertoire_source = None
        self.donnees = []
        self.doublons = {}
        self.doublons_stats = None
        self.file_index = FileIndex()  # Reset l'index
        
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
            reponse = messagebox.askyesno("Attention",
                                         "Une suppression est en cours.\n"
                                         "Êtes-vous sûr de vouloir quitter?")
            if not reponse:
                return
            self.cancellation_requested = True
        
        self.root.destroy()


def main():
    root = tk.Tk()
    app = ApplicationDoublons(root)
    root.mainloop()


if __name__ == "__main__":
    main()

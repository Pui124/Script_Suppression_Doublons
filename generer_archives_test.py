#!/usr/bin/env python3
"""
Generateur d'archives de test pour l'application Suppression des Doublons Archifiltre.

Cree un dossier d'archives avec des fichiers reels (dont des doublons)
ET le fichier CSV au format Archifiltre correspondant, pret a charger dans l'appli.

Usage :
    py generer_archives_test.py                    <- sans argument : ouvre le menu graphique
    py generer_archives_test.py --defaut           <- generation directe avec les valeurs par defaut
    py generer_archives_test.py --fichiers 2500 --taux-doublons 45 --taille-cible 5
    py generer_archives_test.py --dossier MonTest --fichiers 500 --profondeur 2
    py generer_archives_test.py --extensions bureautique,images
    py generer_archives_test.py --extensions .pdf,.txt,texte
    py generer_archives_test.py --defaut --sans-csv     <- archives seules, sans CSV

Le CSV genere reproduit l'export officiel Archifiltre « CSV avec empreinte »
(memes colonnes, memes libelles, meme format de cellules) d'apres le code
source de SocialGouv/archifiltre-docs.
"""

import argparse
import hashlib
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── Parametres par defaut ─────────────────────────────────────────────────────

DEFAUT_DOSSIER       = "Archives_Test"
DEFAUT_NB_FICHIERS   = 200
DEFAUT_TAUX_DOUBLON  = 25    # % de fichiers qui auront un doublon
DEFAUT_TAILLE_CIBLE  = 0     # 0 = pas de cible (petits fichiers texte)
DEFAUT_PROFONDEUR    = 4     # niveau max de sous-dossiers (0 = tout a la racine)
DEFAUT_TAILLE_MIN_KB = 10    # Ko min par fichier (mode sans cible)
DEFAUT_TAILLE_MAX_KB = 200   # Ko max par fichier (mode sans cible)

FILLER_SIZE = 512 * 1024     # 512 Ko de donnees de remplissage

# Typologies d'extensions : selectionnables individuellement (menu ou --extensions)
EXT_TYPOLOGIES = {
    'bureautique': ['.pdf', '.docx', '.xlsx', '.pptx', '.odt'],
    'texte':       ['.txt', '.md', '.log'],
    'donnees':     ['.csv', '.xml', '.json', '.dat'],
    'images':      ['.jpg', '.png', '.tif', '.gif'],
    'web':         ['.html', '.htm'],
    'systeme':     ['.bin', '.bak', '.tmp'],
}

# Jeu par defaut (comportement historique du generateur)
EXTS = [".txt", ".csv", ".xml", ".html", ".md", ".log", ".json", ".dat", ".bin", ".bak"]


def parse_extensions(spec):
    """Transforme 'bureautique,images' ou '.pdf,.txt,texte' en liste d'extensions.

    Accepte un melange de noms de typologies et d'extensions brutes (prefixees
    par un point), separes par des virgules. Vide -> jeu par defaut EXTS.
    """
    exts = []
    for tok in (spec or '').split(','):
        tok = tok.strip().lower()
        if not tok:
            continue
        if tok.startswith('.'):
            exts.append(tok)
        elif tok in EXT_TYPOLOGIES:
            exts.extend(EXT_TYPOLOGIES[tok])
        else:
            raise ValueError(
                f"Typologie inconnue : '{tok}' "
                f"(choix : {', '.join(EXT_TYPOLOGIES)} ou extensions '.xxx')"
            )
    return list(dict.fromkeys(exts)) or list(EXTS)

NOMS_DOSSIERS = [
    "Administratif", "Comptabilite", "RH", "Juridique", "Direction",
    "Projets", "Archives_2019", "Archives_2020", "Archives_2021",
    "Archives_2022", "Archives_2023", "Correspondance", "Contrats",
    "Rapports_annuels", "Deliberations", "Actes", "Registres",
    "Factures", "Marches_publics", "Communication",
]
SOUS_DOSSIERS = [
    "Entrant", "Sortant", "Interne", "Valide", "En_cours",
    "Archive", "Original", "Copie", "Scan", "Version_finale",
]
MOTS = [
    "archive", "document", "rapport", "note", "decision", "deliberation",
    "arrete", "convention", "contrat", "correspondance", "courrier", "acte",
    "registre", "inventaire", "bordereau", "dossier", "fiche", "bilan",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def date_aleatoire(rng, debut, fin):
    delta = fin - debut
    return debut + timedelta(seconds=rng.randint(0, int(delta.total_seconds())))


def nom_fichier(rng, ext=None):
    motifs = [
        lambda: "_".join([rng.choice(MOTS).capitalize() for _ in range(rng.randint(1, 3))]),
        lambda: f"{rng.choice(MOTS).capitalize()}_{rng.randint(2015, 2024)}",
        lambda: f"{''.join([str(rng.randint(0,9)) for _ in range(6)])}_{rng.choice(MOTS)}",
        lambda: f"CR_{rng.randint(1,99):03d}_{rng.choice(MOTS).capitalize()}",
        lambda: f"NOTE_{rng.randint(2015,2024)}_{rng.randint(1,999):04d}",
        lambda: f"RAPPORT_{rng.randint(2015, 2024)}",
        lambda: f"DOC_{rng.randint(1, 9999):05d}",
    ]
    base = rng.choice(motifs)()
    if ext is None:
        ext = rng.choice(EXTS)
    return base + ext


def chemin_archifiltre(root_name, chemin_absolu, root_absolu):
    rel = os.path.relpath(chemin_absolu, root_absolu).replace('\\', '/')
    return '/' + root_name + '/' + rel


def format_size(octets):
    if octets >= 1024 ** 3:
        return f"{octets / 1024**3:.2f} Go"
    if octets >= 1024 ** 2:
        return f"{octets / 1024**2:.2f} Mo"
    return f"{octets / 1024:.1f} Ko"


# ── Generation du contenu ─────────────────────────────────────────────────────

def generer_filler(seed):
    """Bloc de remplissage deterministe de 512 Ko (partage entre tous les fichiers)."""
    rng = random.Random(seed ^ 0xCAFEBABE)
    return bytes(rng.randint(0, 255) for _ in range(FILLER_SIZE))


def ecrire_fichier(chemin, file_seed, taille_octets, filler):
    """
    Ecrit un fichier de taille exacte de maniere efficace (streaming).
    Le contenu est deterministe : meme seed + meme taille = meme MD5.
    Renvoie le MD5 du fichier ecrit.
    """
    header = f"SEED:{file_seed:016d}|SZ:{taille_octets:016d}|".encode('ascii')
    h = hashlib.md5()
    with open(chemin, 'wb') as f:
        f.write(header)
        h.update(header)
        reste = taille_octets - len(header)
        while reste > 0:
            bloc = filler[:min(len(filler), reste)]
            f.write(bloc)
            h.update(bloc)
            reste -= len(bloc)
    return h.hexdigest()


def generer_contenu_texte(rng):
    """Contenu textuel pour les petits fichiers (mode sans taille cible)."""
    nb = rng.randint(30, 200)
    mots = [rng.choice(MOTS) for _ in range(nb)]
    return " ".join(mots).encode('utf-8')


# ── Construction de l'arborescence ────────────────────────────────────────────

def creer_arborescence(rng, racine, nb_fichiers, profondeur_max=DEFAUT_PROFONDEUR):
    """Cree l'arborescence ; profondeur_max = niveau max de sous-dossiers
    (0 = tous les fichiers a la racine)."""
    racine.mkdir(parents=True, exist_ok=True)
    dossiers = [racine]
    if profondeur_max <= 0:
        return dossiers
    nb_sous = max(6, nb_fichiers // 12)
    for _ in range(nb_sous):
        parent = rng.choice(dossiers)
        profondeur = len(parent.relative_to(racine).parts)
        if profondeur < profondeur_max:
            nom = (rng.choice(NOMS_DOSSIERS) if profondeur < 2
                   else rng.choice(SOUS_DOSSIERS))
            d = parent / f"{nom}_{rng.randint(1, 9)}"
            d.mkdir(exist_ok=True)
            dossiers.append(d)
    return dossiers


# ── Generation principale ─────────────────────────────────────────────────────

def generer_structure(racine, nb_fichiers, taux_doublon, taille_cible_go, seed, verbose,
                      profondeur_max=DEFAUT_PROFONDEUR, extensions=None):
    rng        = random.Random(seed)
    filler     = generer_filler(seed)
    extensions = list(extensions) if extensions else list(EXTS)

    dossiers   = creer_arborescence(rng, racine, nb_fichiers, profondeur_max)
    nb_uniques = max(1, int(nb_fichiers * (1 - taux_doublon / 100)))
    nb_copies  = nb_fichiers - nb_uniques

    # Taille par fichier
    if taille_cible_go > 0:
        taille_cible_octets = int(taille_cible_go * 1024 ** 3)
        taille_moy = taille_cible_octets // nb_fichiers
        taille_moy = max(taille_moy, len(f"SEED:{0:016d}|SZ:{0:016d}|") + 1)
        def taille_aleatoire():
            # Distribution realiste autour de la moyenne
            return max(1024, int(taille_moy * rng.uniform(0.3, 2.5)))
        mode_grand = True
    else:
        mode_grand = False

    print(f"  Mode          : {'grands fichiers (streaming)' if mode_grand else 'petits fichiers texte'}")
    print(f"  Fichiers      : {nb_uniques} uniques + {nb_copies} copies")
    if mode_grand:
        print(f"  Taille cible  : {taille_cible_go} Go (~{format_size(taille_moy)} / fichier)")
    print()

    # Pool unique: list de (file_seed, taille_octets, ext)
    pool = []
    for i in range(nb_uniques):
        ext   = rng.choice(extensions)
        taille = taille_aleatoire() if mode_grand else None
        pool.append((i, taille, ext))

    # Plan: (dossier, pool_entry, nom)
    plan = []
    chemins_vus = set()

    def ajouter(dossier, entry, force_nom=None):
        _, _, ext = entry
        nom = force_nom or nom_fichier(rng, ext)
        chemin = dossier / nom
        # Eviter les collisions de chemin
        tentatives = 0
        while str(chemin) in chemins_vus and tentatives < 10:
            nom = nom_fichier(rng, ext)
            chemin = dossier / nom
            tentatives += 1
        if str(chemin) in chemins_vus:
            nom = nom_fichier(rng, ext) + f"_{rng.randint(100,999)}"
            chemin = dossier / (nom + ext)
        chemins_vus.add(str(chemin))
        plan.append((chemin, entry))

    # Placer les uniques
    for entry in pool:
        ajouter(rng.choice(dossiers), entry)

    # Placer les copies dans des dossiers differents (ou meme nom, dossier different)
    for _ in range(nb_copies):
        entry  = rng.choice(pool)
        _, _, ext = entry
        # Choisir un dossier different du premier placement si possible
        d = rng.choice(dossiers)
        # 30% de chance : meme nom de fichier (cas difficile pour l'appli)
        if rng.random() < 0.30:
            # Trouver le nom deja utilise pour ce seed
            nom_orig = next(
                (c.name for c, e in plan if e is entry and c.parent != d), None
            )
            force = nom_orig
        else:
            force = None
        ajouter(d, entry, force_nom=force)

    # Ecriture sur disque
    fichiers_info = []
    debut_date = datetime(2015, 1, 1)
    fin_date   = datetime(2024, 12, 31)
    t0         = time.time()
    taille_totale = 0
    md5_cache  = {}  # {(seed, taille): md5}

    for idx, (chemin, entry) in enumerate(plan):
        file_seed, taille, _ = entry

        if mode_grand:
            # Verifier si on a deja le MD5 (meme seed+taille = meme contenu)
            cle = (file_seed, taille)
            if cle in md5_cache:
                # Fichier identique deja ecrit : copier depuis le cache MD5
                md5 = md5_cache[cle]
                # Ecrire le fichier avec le meme contenu
                ecrire_fichier(chemin, file_seed, taille, filler)
            else:
                md5 = ecrire_fichier(chemin, file_seed, taille, filler)
                md5_cache[cle] = md5
            poids = taille
        else:
            # Petits fichiers texte
            cle = (file_seed, None)
            if cle in md5_cache:
                contenu = md5_cache[cle]
                chemin.write_bytes(contenu)
                md5 = hashlib.md5(contenu).hexdigest()
            else:
                rng2 = random.Random(file_seed)
                contenu = generer_contenu_texte(rng2)
                chemin.write_bytes(contenu)
                md5 = hashlib.md5(contenu).hexdigest()
                md5_cache[cle] = contenu
            poids = len(contenu)

        taille_totale += poids

        # Horodatage aleatoire
        dt = date_aleatoire(rng, debut_date, fin_date)
        ts = dt.timestamp()
        os.utime(chemin, (ts, ts))

        fichiers_info.append({
            'chemin_absolu': str(chemin),
            'nom':           chemin.name,
            'md5':           md5,
            'poids':         poids,
            'date':          dt.strftime('%Y-%m-%d %H:%M:%S'),
        })

        # Progression
        if verbose or (idx + 1) % 50 == 0 or idx == len(plan) - 1:
            elapsed = time.time() - t0
            pct = (idx + 1) / len(plan) * 100
            vitesse = taille_totale / elapsed / (1024**2) if elapsed > 0 else 0
            print(f"  [{pct:5.1f}%] {idx+1:5}/{len(plan)}  "
                  f"{format_size(taille_totale):>10}  "
                  f"{vitesse:5.1f} Mo/s", end='\r', flush=True)

    elapsed_total = time.time() - t0
    print(f"\n  Termine en {elapsed_total:.1f}s  —  {format_size(taille_totale)} ecrits")
    return fichiers_info


# ── Generation du CSV Archifiltre « avec empreinte » ─────────────────────────
#
# Reproduit fidelement l'export CSV d'Archifiltre Docs (option "avec empreinte")
# d'apres le code source SocialGouv/archifiltre-docs (branche dev) :
#   - colonnes : make-array-export-config.ts (makeRowConfig)
#   - libelles : translations/fr.json (csvHeader.*)
#   - format   : common/utils/csv.ts (arrayToCsv) -> toutes les cellules entre
#     guillemets doubles ("" pour echapper), separateur ';', lignes '\n'
#   - chemin   : formatPathForUserSystem = path.normalize('/racine/...')
#     -> antislashs sous Windows, ex: \Archives\dossier\fichier.txt
#   - dates    : JJ/MM/AAAA
#   - profondeur : id.split('/').length - 2
#   - type     : sous-type MIME du fichier (lookup mime-types), sinon 'inconnu'

ENTETES_ARCHIFILTRE = [
    '', 'chemin', 'longueur du chemin', 'nom', 'extension', 'poids (octets)',
    'date de première modification', 'date de dernière modification',
    'nouvelle date de première modification', 'nouvelle date de dernière modification',
    'nouveau chemin', 'nouveau nom', 'description', 'fichier/répertoire',
    'profondeur', 'nombre de fichiers', 'type', 'empreinte (MD5)', 'redondance',
]

# Sous-types MIME comme les renvoie `mime-types.lookup().split('/').pop()`
MIME_SOUS_TYPES = {
    '.pdf':  'pdf',
    '.docx': 'vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.pptx': 'vnd.openxmlformats-officedocument.presentationml.presentation',
    '.odt':  'vnd.oasis.opendocument.text',
    '.txt':  'plain',
    '.md':   'markdown',
    '.csv':  'csv',
    '.xml':  'xml',
    '.json': 'json',
    '.jpg':  'jpeg',
    '.jpeg': 'jpeg',
    '.png':  'png',
    '.tif':  'tiff',
    '.gif':  'gif',
    '.html': 'html',
    '.htm':  'html',
    '.bin':  'octet-stream',
}


def _cellule(valeur):
    return '"' + str(valeur).replace('"', '""') + '"'


def _date_fr(date_iso):
    """'2020-05-17 08:30:00' -> '17/05/2020' (format d'export Archifiltre)."""
    dt = datetime.strptime(date_iso, '%Y-%m-%d %H:%M:%S')
    return dt.strftime('%d/%m/%Y')


def generer_csv(fichiers, racine, chemin_csv):
    """Ecrit le CSV au format Archifiltre « CSV avec empreinte »."""
    # L'id Archifiltre est '/NomRacine/<chemin relatif A LA racine>' :
    # le relatif doit etre calcule depuis racine (pas son parent, sinon le
    # nom de la racine apparait deux fois dans le chemin)
    root_str  = str(racine)
    root_name = racine.name

    # Agregats par dossier (poids total, bornes de dates, nb de fichiers)
    dossiers = {}   # {chemin_absolu: {'poids', 'dates', 'nb'}}
    for f in fichiers:
        p = Path(f['chemin_absolu'])
        for parent in p.parents:
            sp = str(parent)
            if not sp.startswith(str(racine)):
                break
            d = dossiers.setdefault(sp, {'poids': 0, 'dates': [], 'nb': 0})
            d['poids'] += f['poids']
            d['dates'].append(f['date'])
            d['nb']    += 1

    md5_compte = {}
    for f in fichiers:
        md5_compte[f['md5']] = md5_compte.get(f['md5'], 0) + 1

    lignes = [';'.join(_cellule(c) for c in ENTETES_ARCHIFILTRE)]

    def ajouter_ligne(id_unix, nom, poids, date_min, date_max,
                      fichier_ou_rep, nb_fichiers, type_, md5, redondance):
        chemin_sys = os.path.normpath(id_unix)   # \racine\... sous Windows
        ext = os.path.splitext(nom)[1].lower() if fichier_ou_rep == 'fichier' else \
              os.path.splitext(nom)[1]
        lignes.append(';'.join(_cellule(c) for c in [
            '',                                   # colonne vide
            chemin_sys,                           # chemin
            len(chemin_sys),                      # longueur du chemin
            nom,                                  # nom
            ext,                                  # extension
            poids,                                # poids (octets)
            date_min,                             # date de première modification
            date_max,                             # date de dernière modification
            '', '', '', '', '',                   # nouvelles dates/chemin/nom, description
            fichier_ou_rep,                       # fichier/répertoire
            len(id_unix.split('/')) - 2,          # profondeur
            nb_fichiers,                          # nombre de fichiers
            type_,                                # type
            md5,                                  # empreinte (MD5)
            redondance,                           # redondance
        ]))

    # Ligne du dossier racine puis des sous-dossiers
    # (l'export Archifiltre liste chaque repertoire ; leur empreinte est laissee
    #  vide, l'application de suppression ignore de toute facon ces lignes)
    tous_dossiers = sorted(set(dossiers) | {root_str})
    for sp in tous_dossiers:
        infos = dossiers.get(sp, {'poids': 0, 'dates': [], 'nb': 0})
        id_unix = chemin_archifiltre(root_name, sp, root_str) if sp != root_str \
                  else '/' + root_name
        dates = sorted(infos['dates'])
        ajouter_ligne(
            id_unix, os.path.basename(sp), infos['poids'],
            _date_fr(dates[0]) if dates else '', _date_fr(dates[-1]) if dates else '',
            'répertoire', infos['nb'], 'répertoire', '', 'Non',
        )

    # Lignes des fichiers
    for f in fichiers:
        id_unix = chemin_archifiltre(root_name, f['chemin_absolu'], root_str)
        ext     = os.path.splitext(f['nom'])[1].lower()
        ajouter_ligne(
            id_unix, f['nom'], f['poids'],
            _date_fr(f['date']), _date_fr(f['date']),
            'fichier', 1, MIME_SOUS_TYPES.get(ext, 'inconnu'),
            f['md5'], 'Oui' if md5_compte[f['md5']] > 1 else 'Non',
        )

    with open(chemin_csv, 'w', encoding='utf-8', newline='') as fout:
        fout.write('\n'.join(lignes))


# ── Stats ─────────────────────────────────────────────────────────────────────

def afficher_stats(fichiers, racine, chemin_csv=None):
    from collections import Counter
    md5c  = Counter(f['md5'] for f in fichiers)
    groupes = sum(1 for c in md5c.values() if c > 1)
    copies  = sum(c - 1 for c in md5c.values() if c > 1)
    # Espace recuperable = taille de toutes les copies (toutes sauf 1 par groupe)
    md5_vu = {}
    espace = 0
    for f in fichiers:
        m = f['md5']
        if md5c[m] > 1:
            if m in md5_vu:
                espace += f['poids']  # c'est une copie
            else:
                md5_vu[m] = True       # premier = original, on garde
    taille_totale = sum(f['poids'] for f in fichiers)

    sep = "-" * 55
    print(f"\n{sep}")
    print(f"  RESUME")
    print(f"{sep}")
    print(f"  Dossier racine      : {racine}")
    print(f"  Fichiers generes    : {len(fichiers)}")
    print(f"  Taille totale       : {format_size(taille_totale)}")
    print(f"  Groupes de doublons : {groupes}")
    print(f"  Copies a supprimer  : {copies}")
    print(f"  Espace recuperable  : {format_size(espace)}")
    if chemin_csv:
        print(f"  CSV Archifiltre     : {chemin_csv}")
        print(f"{sep}")
        print(f"  Dans l'application :")
        print(f"    1. CSV        -> {chemin_csv.name}")
        print(f"    2. Repertoire -> {racine.name}")
    else:
        print(f"  CSV Archifiltre     : non genere (case decochee)")
    print(f"{sep}\n")


# ── Execution (commun CLI / menu) ─────────────────────────────────────────────

def executer_generation(racine, chemin_csv, nb_fichiers, taux_doublon,
                        taille_cible, seed, verbose, profondeur, extensions,
                        avec_csv=True):
    """Genere l'archive (+ le CSV Archifiltre si avec_csv) et affiche les stats.
    Le dossier cible ne doit plus exister (l'appelant gere l'ecrasement)."""
    sep = "=" * 55
    print(f"\n{sep}")
    print(f"  GENERATEUR D'ARCHIVES DE TEST")
    print(f"{sep}")
    print(f"  Dossier      : {racine}")
    print(f"  Fichiers     : {nb_fichiers}")
    print(f"  Taux doublons: {taux_doublon:.0f}%")
    print(f"  Profondeur   : {profondeur} niveau(x) de sous-dossiers")
    print(f"  Extensions   : {', '.join(extensions)}")
    if taille_cible > 0:
        print(f"  Taille cible : {taille_cible} Go")
    print()

    fichiers = generer_structure(
        racine, nb_fichiers, taux_doublon, taille_cible, seed, verbose,
        profondeur_max=profondeur, extensions=extensions,
    )

    if avec_csv:
        print("  Generation du CSV Archifiltre (avec empreintes)...")
        generer_csv(fichiers, racine, chemin_csv)

    afficher_stats(fichiers, racine, chemin_csv if avec_csv else None)


# ── Menu graphique ────────────────────────────────────────────────────────────

def lancer_menu():
    """Petit menu Tkinter pour parametrer la generation sans ligne de commande."""
    import queue
    import shutil
    import threading
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("Générateur d'archives de test — Doublons Archifiltre")
    root.resizable(False, False)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)

    # ── Paramètres ──
    params = ttk.Labelframe(frm, text="Paramètres", padding=10)
    params.pack(fill=tk.X)
    params.columnconfigure(1, weight=1)

    var_dossier    = tk.StringVar(value=DEFAUT_DOSSIER)
    var_sortie     = tk.StringVar(value=os.getcwd())
    var_fichiers   = tk.IntVar(value=DEFAUT_NB_FICHIERS)
    var_taux       = tk.IntVar(value=DEFAUT_TAUX_DOUBLON)
    var_profondeur = tk.IntVar(value=DEFAUT_PROFONDEUR)
    var_taille     = tk.DoubleVar(value=DEFAUT_TAILLE_CIBLE)
    var_seed       = tk.IntVar(value=42)

    def ligne(row, texte, widget):
        ttk.Label(params, text=texte).grid(row=row, column=0, sticky='w',
                                           pady=3, padx=(0, 8))
        widget.grid(row=row, column=1, sticky='ew', pady=3)

    ligne(0, "Nom du dossier racine :", ttk.Entry(params, textvariable=var_dossier))

    sortie_fr = ttk.Frame(params)
    sortie_fr.columnconfigure(0, weight=1)
    e_sortie = ttk.Entry(sortie_fr, textvariable=var_sortie)
    e_sortie.grid(row=0, column=0, sticky='ew')
    ttk.Button(sortie_fr, text="…", width=3,
               command=lambda: var_sortie.set(
                   filedialog.askdirectory(initialdir=var_sortie.get())
                   or var_sortie.get())
               ).grid(row=0, column=1, padx=(4, 0))
    ligne(1, "Dossier de sortie :", sortie_fr)

    ligne(2, "Nombre de fichiers :",
          ttk.Spinbox(params, from_=1, to=100000, increment=50,
                      textvariable=var_fichiers))
    ligne(3, "Taux de doublons (%) :",
          ttk.Spinbox(params, from_=0, to=90, increment=5, textvariable=var_taux))
    ligne(4, "Profondeur de sous-dossiers :",
          ttk.Spinbox(params, from_=0, to=8, textvariable=var_profondeur))
    ligne(5, "Taille cible totale (Go, 0 = petits fichiers) :",
          ttk.Spinbox(params, from_=0, to=500, increment=0.5, format='%.1f',
                      textvariable=var_taille))
    ligne(6, "Graine aléatoire (seed) :",
          ttk.Spinbox(params, from_=0, to=999999, textvariable=var_seed))

    # ── Typologie d'extensions ──
    typolf = ttk.Labelframe(frm, text="Typologie d'extensions de fichiers", padding=10)
    typolf.pack(fill=tk.X, pady=(8, 0))
    vars_typo = {}
    for i, (nom, exts) in enumerate(EXT_TYPOLOGIES.items()):
        v = tk.BooleanVar(value=True)
        vars_typo[nom] = v
        ttk.Checkbutton(
            typolf, variable=v,
            text=f"{nom.capitalize()}  ({', '.join(e.lstrip('.') for e in exts)})"
        ).grid(row=i // 2, column=i % 2, sticky='w', padx=4, pady=2)
    var_autres = tk.StringVar()
    ttk.Label(typolf, text="Autres extensions (ex: .gz,.zip) :").grid(
        row=(len(EXT_TYPOLOGIES) + 1) // 2, column=0, sticky='w', padx=4, pady=(6, 0))
    ttk.Entry(typolf, textvariable=var_autres, width=24).grid(
        row=(len(EXT_TYPOLOGIES) + 1) // 2, column=1, sticky='ew', padx=4, pady=(6, 0))

    # ── Export CSV ──
    var_csv = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        frm, variable=var_csv,
        text="Générer le CSV Archifiltre « avec empreinte » "
             "(même format que l'export officiel)"
    ).pack(anchor='w', pady=(8, 0))

    # ── Journal ──
    journal = tk.Text(frm, height=14, width=76, state='disabled',
                      font=('Consolas', 8), bg='#F5F5F5')
    journal.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

    class RedirJournal:
        """Redirige stdout vers le Text (gere \\r : reecrit la derniere ligne)."""
        def __init__(self):
            self._cr = False
        def write(self, s):
            root.after(0, self._append, s)
        def flush(self):
            pass
        def _append(self, s):
            journal.config(state='normal')
            for i, part in enumerate(s.replace('\r\n', '\n').split('\r')):
                if i > 0:
                    self._cr = True   # \r rencontré : la prochaine écriture remplace la ligne
                if part:
                    if self._cr:
                        journal.delete('end-1c linestart', 'end-1c')
                        self._cr = False
                    journal.insert('end', part)
            journal.see('end')
            journal.config(state='disabled')

    # ── Lancement ──
    btn_fr = ttk.Frame(frm)
    btn_fr.pack(fill=tk.X, pady=(8, 0))
    btn_gen = ttk.Button(btn_fr, text="Générer l'archive de test")
    btn_gen.pack(side=tk.RIGHT)
    ttk.Button(btn_fr, text="Fermer", command=root.destroy).pack(
        side=tk.RIGHT, padx=(0, 8))

    def extensions_choisies():
        exts = []
        for nom, v in vars_typo.items():
            if v.get():
                exts.extend(EXT_TYPOLOGIES[nom])
        for tok in var_autres.get().split(','):
            tok = tok.strip().lower()
            if tok:
                exts.append(tok if tok.startswith('.') else '.' + tok)
        return list(dict.fromkeys(exts))

    def generer():
        try:
            nb    = int(var_fichiers.get())
            taux  = float(var_taux.get())
            prof  = int(var_profondeur.get())
            cible = float(var_taille.get())
            seed  = int(var_seed.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Paramètres", "Valeurs numériques invalides.")
            return
        avec_csv = bool(var_csv.get())
        exts = extensions_choisies()
        if not exts:
            messagebox.showerror("Extensions",
                                 "Sélectionnez au moins une typologie d'extensions.")
            return
        if nb < 1 or not var_dossier.get().strip():
            messagebox.showerror("Paramètres",
                                 "Nombre de fichiers et nom de dossier requis.")
            return

        racine     = Path(var_sortie.get()) / var_dossier.get().strip()
        chemin_csv = Path(var_sortie.get()) / f"{var_dossier.get().strip()}_archifiltre.csv"
        if racine.exists():
            if not messagebox.askyesno("Écraser ?",
                                       f"'{racine}' existe déjà.\nÉcraser son contenu ?"):
                return
            shutil.rmtree(racine)

        journal.config(state='normal')
        journal.delete('1.0', 'end')
        journal.config(state='disabled')
        btn_gen.config(state='disabled')

        def travail():
            import contextlib
            redir = RedirJournal()
            try:
                with contextlib.redirect_stdout(redir):
                    executer_generation(racine, chemin_csv, nb, taux, cible,
                                        seed, False, prof, exts,
                                        avec_csv=avec_csv)
            except Exception as e:
                redir.write(f"\nERREUR : {e}\n")
            finally:
                root.after(0, lambda: btn_gen.config(state='normal'))

        threading.Thread(target=travail, daemon=True).start()

    btn_gen.config(command=generer)
    root.mainloop()


# ── Point d'entree ────────────────────────────────────────────────────────────

def main():
    # Sans argument : menu graphique. Avec arguments : ligne de commande.
    if len(sys.argv) == 1:
        lancer_menu()
        return

    p = argparse.ArgumentParser(
        description="Genere une archive de test avec doublons + CSV Archifiltre"
    )
    p.add_argument('--dossier',       default=DEFAUT_DOSSIER,
                   help=f"Nom du dossier racine (def: {DEFAUT_DOSSIER})")
    p.add_argument('--fichiers',      type=int, default=DEFAUT_NB_FICHIERS,
                   help=f"Nombre total de fichiers (def: {DEFAUT_NB_FICHIERS})")
    p.add_argument('--taux-doublons', type=float, default=DEFAUT_TAUX_DOUBLON,
                   dest='taux_doublon',
                   help=f"Pourcentage de doublons (def: {DEFAUT_TAUX_DOUBLON})")
    p.add_argument('--taille-cible',  type=float, default=DEFAUT_TAILLE_CIBLE,
                   dest='taille_cible',
                   help="Taille totale cible en Go (0 = petits fichiers texte, def: 0)")
    p.add_argument('--profondeur',    type=int, default=DEFAUT_PROFONDEUR,
                   help=f"Niveau max de sous-dossiers, 0 = tout a la racine "
                        f"(def: {DEFAUT_PROFONDEUR})")
    p.add_argument('--extensions',    default='',
                   help="Typologies et/ou extensions, separees par des virgules. "
                        f"Typologies : {', '.join(EXT_TYPOLOGIES)}. "
                        "Ex: 'bureautique,images' ou '.pdf,.txt,texte' "
                        "(def: jeu historique)")
    p.add_argument('--sortie',        default='.',
                   help="Dossier parent de sortie (def: repertoire courant)")
    p.add_argument('--sans-csv',      action='store_true', dest='sans_csv',
                   help="Ne pas generer le CSV Archifiltre")
    p.add_argument('--seed',          type=int, default=42)
    p.add_argument('--verbose',       action='store_true')
    p.add_argument('--defaut',        action='store_true',
                   help="Generation directe avec les valeurs par defaut (sans menu)")
    args = p.parse_args()

    try:
        extensions = parse_extensions(args.extensions)
    except ValueError as e:
        p.error(str(e))

    racine     = Path(args.sortie) / args.dossier
    chemin_csv = Path(args.sortie) / f"{args.dossier}_archifiltre.csv"

    if racine.exists():
        rep = input(f"\n  '{racine}' existe deja. Ecraser ? (o/N) : ").strip().lower()
        if rep != 'o':
            print("  Annule.")
            return
        import shutil
        shutil.rmtree(racine)

    executer_generation(racine, chemin_csv, args.fichiers, args.taux_doublon,
                        args.taille_cible, args.seed, args.verbose,
                        args.profondeur, extensions, avec_csv=not args.sans_csv)


if __name__ == "__main__":
    main()

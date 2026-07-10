#!/usr/bin/env python3
"""
Generateur d'archives de test pour l'application Suppression des Doublons Archifiltre.

Cree un dossier d'archives avec des fichiers reels (dont des doublons)
ET le fichier CSV au format Archifiltre correspondant, pret a charger dans l'appli.

Usage :
    py generer_archives_test.py
    py generer_archives_test.py --fichiers 2500 --taux-doublons 45 --taille-cible 5
    py generer_archives_test.py --dossier MonTest --fichiers 500 --taux-doublons 30
"""

import argparse
import csv
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
DEFAUT_TAILLE_MIN_KB = 10    # Ko min par fichier (mode sans cible)
DEFAUT_TAILLE_MAX_KB = 200   # Ko max par fichier (mode sans cible)

FILLER_SIZE = 512 * 1024     # 512 Ko de donnees de remplissage

EXTS = [".txt", ".csv", ".xml", ".html", ".md", ".log", ".json", ".dat", ".bin", ".bak"]

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

def creer_arborescence(rng, racine, nb_fichiers):
    racine.mkdir(parents=True, exist_ok=True)
    dossiers = [racine]
    nb_sous = max(6, nb_fichiers // 12)
    for _ in range(nb_sous):
        parent = rng.choice(dossiers)
        profondeur = len(parent.relative_to(racine).parts)
        if profondeur < 4:
            nom = (rng.choice(NOMS_DOSSIERS) if profondeur < 2
                   else rng.choice(SOUS_DOSSIERS))
            d = parent / f"{nom}_{rng.randint(1, 9)}"
            d.mkdir(exist_ok=True)
            dossiers.append(d)
    return dossiers


# ── Generation principale ─────────────────────────────────────────────────────

def generer_structure(racine, nb_fichiers, taux_doublon, taille_cible_go, seed, verbose):
    rng    = random.Random(seed)
    filler = generer_filler(seed)

    dossiers   = creer_arborescence(rng, racine, nb_fichiers)
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
        ext   = rng.choice(EXTS)
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


# ── Generation du CSV Archifiltre ─────────────────────────────────────────────

def generer_csv(fichiers, racine, chemin_csv):
    root_name = racine.name
    root_str  = str(racine)

    dossiers_vus = set()
    for f in fichiers:
        p = Path(f['chemin_absolu'])
        for parent in p.parents:
            if str(parent).startswith(root_str):
                dossiers_vus.add(str(parent))

    with open(chemin_csv, 'w', encoding='utf-8-sig', newline='') as fout:
        w = csv.writer(fout, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        w.writerow([
            'fichier/repertoire', 'nom', 'chemin',
            'poids (octets)', 'empreinte (MD5)',
            'date de premiere modification', 'derniere modification',
            'profondeur', 'nb enfants',
        ])
        # Repertoires
        for d in sorted(dossiers_vus):
            chemin_d = chemin_archifiltre(root_name, d, str(racine.parent))
            w.writerow(['repertoire', os.path.basename(d), chemin_d,
                        0, '', '', '', len(Path(d).relative_to(racine).parts), ''])
        # Fichiers
        for f in fichiers:
            chemin_f = chemin_archifiltre(root_name, f['chemin_absolu'], str(racine.parent))
            w.writerow(['fichier', f['nom'], chemin_f,
                        f['poids'], f['md5'], f['date'], f['date'],
                        len(Path(f['chemin_absolu']).relative_to(racine).parts), 0])


# ── Stats ─────────────────────────────────────────────────────────────────────

def afficher_stats(fichiers, racine, chemin_csv):
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
    print(f"  CSV Archifiltre     : {chemin_csv}")
    print(f"{sep}")
    print(f"  Dans l'application :")
    print(f"    1. CSV        -> {chemin_csv.name}")
    print(f"    2. Repertoire -> {racine.name}")
    print(f"{sep}\n")


# ── Point d'entree ────────────────────────────────────────────────────────────

def main():
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
    p.add_argument('--sortie',        default='.',
                   help="Dossier parent de sortie (def: repertoire courant)")
    p.add_argument('--seed',          type=int, default=42)
    p.add_argument('--verbose',       action='store_true')
    args = p.parse_args()

    racine     = Path(args.sortie) / args.dossier
    chemin_csv = Path(args.sortie) / f"{args.dossier}_archifiltre.csv"

    sep = "=" * 55
    print(f"\n{sep}")
    print(f"  GENERATEUR D'ARCHIVES DE TEST")
    print(f"{sep}")
    print(f"  Dossier      : {racine}")
    print(f"  Fichiers     : {args.fichiers}")
    print(f"  Taux doublons: {args.taux_doublon:.0f}%")
    if args.taille_cible > 0:
        print(f"  Taille cible : {args.taille_cible} Go")

    if racine.exists():
        rep = input(f"\n  '{racine}' existe deja. Ecraser ? (o/N) : ").strip().lower()
        if rep != 'o':
            print("  Annule.")
            return
        import shutil
        shutil.rmtree(racine)

    print()
    fichiers = generer_structure(
        racine, args.fichiers, args.taux_doublon,
        args.taille_cible, args.seed, args.verbose
    )

    print("  Generation du CSV...")
    generer_csv(fichiers, racine, chemin_csv)

    afficher_stats(fichiers, racine, chemin_csv)


if __name__ == "__main__":
    main()

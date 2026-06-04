#!/usr/bin/env python3
"""
Tests de la logique de suppression (sans interface graphique).

Vérifie les parties sensibles de application_doublon.py :
- fonctions utilitaires (to_int, parse_date, format_size)
- indexation et gestion des collisions de noms (FileIndex)
- sélection de la cible : chemin exact, vérification MD5, exclusion de l'original
- groupement des doublons et choix de l'original (le plus ancien)
- suppression réelle sur disque (end-to-end)

Lancer :  python test_doublons.py
"""
import os
import sys
import tempfile
import shutil
from collections import defaultdict

# Importer le module de l'application (quel que soit le répertoire courant)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import application_doublon as app


echecs = []


def check(nom, cond):
    print(("  OK  " if cond else " FAIL ") + nom)
    if not cond:
        echecs.append(nom)


# Réplique de la stratégie de _resoudre_originaux / _selectionner_cible
def resoudre_originaux(index, chemin_csv):
    exact = index.resoudre_chemin_exact(chemin_csv)
    return {os.path.normcase(os.path.abspath(exact))} if exact else set()


def selectionner(index, nom, chemin_csv, hash_md5, originaux, verifier_md5):
    attendu = (hash_md5 or "").lower()

    def est_original(p):
        return os.path.normcase(os.path.abspath(p)) in originaux

    def md5_ok(p):
        if not verifier_md5:
            return True
        try:
            return app.calculer_md5(p).lower() == attendu
        except OSError:
            return False

    exact = index.resoudre_chemin_exact(chemin_csv)
    if exact and not est_original(exact) and md5_ok(exact):
        return exact, "ok-exact"
    for c in index.candidats_par_nom(nom):
        if not est_original(c) and md5_ok(c):
            return c, "ok-nom"
    return None, "aucun"


def main():
    base = tempfile.mkdtemp(prefix="test_doublons_")
    print(f"Dossier de test: {base}\n")
    try:
        # Contenu A : original + 2 copies (meme contenu -> meme MD5)
        contenu_a = b"contenu identique pour le groupe A " * 50
        # Piege : meme NOM qu'une copie, mais contenu different
        contenu_b = b"contenu totalement different, ne doit PAS etre supprime " * 30

        for sous in ("original", "copie1", "copie2", "piege"):
            os.makedirs(os.path.join(base, sous))

        p_original = os.path.join(base, "original", "rapport.pdf")
        p_copie1 = os.path.join(base, "copie1", "rapport.pdf")
        p_copie2 = os.path.join(base, "copie2", "rapport.pdf")
        p_piege = os.path.join(base, "piege", "rapport.pdf")

        for p in (p_original, p_copie1, p_copie2):
            with open(p, "wb") as f:
                f.write(contenu_a)
        with open(p_piege, "wb") as f:
            f.write(contenu_b)

        md5_a = app.calculer_md5(p_original)
        poids_a = len(contenu_a)

        # [1] Fonctions utilitaires
        print("[1] Fonctions utilitaires")
        check("to_int('1234 ') == 1234", app.to_int("1234 ") == 1234)
        check("to_int('') == 0", app.to_int("") == 0)
        check("to_int('abc') == 0", app.to_int("abc") == 0)
        check("parse_date: 1999 < 2020 (JJ/MM/AAAA)",
              app.parse_date("01/12/1999") < app.parse_date("31/01/2020"))
        check("parse_date inconnue => datetime.max",
              app.parse_date("???") == app.parse_date(""))
        check("format_size(1536) en KB", app.format_size(1536).endswith("KB"))

        # [2] FileIndex
        print("\n[2] FileIndex (indexation + collisions de noms)")
        idx = app.FileIndex()
        idx.indexer_repertoire(base)
        check("total_files == 4", idx.total_files == 4)
        check("collision: 4 candidats par nom",
              len(idx.candidats_par_nom("rapport.pdf")) == 4)
        exact_c1 = idx.resoudre_chemin_exact(os.path.join("copie1", "rapport.pdf"))
        check("chemin exact resout copie1 sans confusion",
              exact_c1 is not None and os.path.normcase(exact_c1) == os.path.normcase(p_copie1))

        # [3] Selection de cible
        print("\n[3] Selection de cible (exclusion original + verif MD5)")
        originaux = resoudre_originaux(idx, os.path.join("original", "rapport.pdf"))
        check("originaux ne contient QUE l'original",
              originaux == {os.path.normcase(os.path.abspath(p_original))})

        cible, raison = selectionner(idx, "rapport.pdf",
                                     os.path.join("copie1", "rapport.pdf"),
                                     md5_a, originaux, verifier_md5=True)
        check("copie1: cible via chemin exact", raison == "ok-exact")
        check("copie1: l'original n'est PAS cible", cible != p_original)
        check("copie1: cible == copie1",
              cible and os.path.normcase(cible) == os.path.normcase(p_copie1))

        cible_p, _ = selectionner(idx, "rapport.pdf", "chemin/inexistant.pdf",
                                  md5_a, originaux, verifier_md5=True)
        check("piege: cible MD5-valide trouvee (pas le piege)",
              cible_p is not None and os.path.normcase(cible_p) != os.path.normcase(p_piege))
        check("piege: contenu different ignore",
              app.calculer_md5(p_piege).lower() != md5_a.lower())

        # [4] Groupement + original par date
        print("\n[4] Groupement doublons + choix de l'original par date")
        lignes = [
            {"nom": "rapport.pdf", "chemin": os.path.join("copie2", "rapport.pdf"),
             "poids": poids_a, "date": "31/01/2020"},
            {"nom": "rapport.pdf", "chemin": os.path.join("original", "rapport.pdf"),
             "poids": poids_a, "date": "01/12/1999"},
            {"nom": "rapport.pdf", "chemin": os.path.join("copie1", "rapport.pdf"),
             "poids": poids_a, "date": "15/06/2010"},
        ]
        groupes = defaultdict(list)
        for ligne in lignes:
            groupes[md5_a].append(ligne)
        tries = sorted(groupes[md5_a], key=lambda f: app.parse_date(f.get("date", "")))
        original, copies = tries[0], tries[1:]
        check("original = le plus ancien (1999)", original["date"] == "01/12/1999")
        check("2 copies a supprimer", len(copies) == 2)

        stats = app.DoublonsStats({md5_a: {"original": original, "copies": copies}})
        check("DoublonsStats: 1 groupe", stats.total_groupes == 1)
        check("DoublonsStats: 2 copies", stats.total_copies == 2)
        check("DoublonsStats: espace == 2x poids", stats.espace_total == 2 * poids_a)

        # [5] Suppression reelle sur disque
        print("\n[5] Suppression reelle (os.remove) - end-to-end")
        idx2 = app.FileIndex()
        idx2.indexer_repertoire(base)
        originaux2 = resoudre_originaux(idx2, os.path.join("original", "rapport.pdf"))
        supprimes = []
        for copie in copies:
            cible, _ = selectionner(idx2, copie["nom"], copie["chemin"], md5_a,
                                    originaux2, verifier_md5=True)
            if cible:
                os.remove(cible)
                supprimes.append(cible)
        check("2 fichiers reellement supprimes", len(supprimes) == 2)
        check("l'original existe TOUJOURS", os.path.isfile(p_original))
        check("copie1 supprimee", not os.path.isfile(p_copie1))
        check("copie2 supprimee", not os.path.isfile(p_copie2))
        check("le fichier piege est INTACT", os.path.isfile(p_piege))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print()
    if echecs:
        print(f"RESULTAT: {len(echecs)} test(s) en echec -> {echecs}")
        return 1
    print("RESULTAT: TOUS LES TESTS PASSENT [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

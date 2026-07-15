# 🗑️ Suppression Doublons — Nettoyage des fichiers dupliqués Archifiltre

Application de bureau (Python / Tkinter) pour **supprimer en masse les fichiers
en double** détectés par [Archifiltre](https://archifiltre.fabrique.social.gouv.fr/),
en toute sécurité : vérification du contenu par empreinte MD5, envoi à la
corbeille, protection des originaux et rapport détaillé.

> 💡 **Cas d'usage** : vous avez analysé un fonds documentaire avec Archifiltre,
> exporté le « CSV avec empreinte », et vous voulez supprimer les centaines de
> copies détectées sans y passer la journée.

---

## ✨ Fonctionnalités

- 📋 **Charge** l'export CSV d'Archifiltre (« CSV avec empreinte »)
- 📁 **Indexe** le répertoire source en arrière-plan (interface fluide, même sur de gros volumes)
- 🔍 **Analyse automatique** dès que le CSV et le répertoire sont chargés
- ☑️ **Sélection fine** : cocher/décocher chaque copie, un groupe entier, ou tout d'un coup
- 🔎 **Filtre instantané** par nom ou chemin (`Ctrl+F`)
- 🔐 **Vérification MD5** du contenu réel avant chaque suppression
- ♻️ **Corbeille** par défaut (suppression réversible), avec bouton **Annuler** en cours d'opération
- 📊 **Statut en temps réel** fichier par fichier, et **rapport détaillé** généré après chaque opération

---

## 📦 Installation

### 1. Avoir Python

[Télécharger Python 3.8+](https://www.python.org/downloads/) (Windows, Mac ou Linux), puis vérifier :
```bash
python --version
```

### 2. Télécharger ce projet

Bouton vert **`<> Code`** → **`Download ZIP`**, puis extraire le dossier.

### 3. Installer la dépendance corbeille (recommandé)

```bash
python -m pip install -r requirements.txt
```
> Sans `send2trash`, l'application fonctionne mais la suppression devient
> **définitive** (un avertissement clair est affiché).

### 4. Lancer

- **Windows** : double-cliquer sur `launcher_application.bat`
  *(installe `send2trash` automatiquement si besoin)*
- **Manuel** :
  ```bash
  python application_doublon.py
  ```

---

## 🚀 Utilisation

```
1️⃣ Carte "Export CSV Archifiltre" → Parcourir…
   → Sélectionner le fichier .csv exporté par Archifiltre (avec empreintes)
   ↓
2️⃣ Carte "Répertoire source" → Parcourir…
   → Choisir le dossier qui a été analysé par Archifiltre
   → Indexation en arrière-plan, puis analyse AUTOMATIQUE
   ↓
3️⃣ Vérifier les résultats
   → Tuiles de statistiques : groupes, copies, espace à libérer
   → Filtrer (Ctrl+F), cocher/décocher fichier par fichier ou par groupe
   ↓
4️⃣ Choisir les options : vérification MD5 ✅ · corbeille ♻️
   ↓
5️⃣ "Supprimer la sélection" → confirmation → suppression
   → Statut en temps réel, bouton Annuler disponible
   ↓
6️⃣ ✅ Terminé ! Rapport généré dans Rapports_Doublons/
```

> ℹ️ **Pourquoi indiquer le répertoire source ?** Le CSV d'Archifiltre contient
> des chemins *relatifs* à la racine analysée (ex : `\Archives\dossier\fichier.txt`),
> jamais de chemin absolu. Le répertoire source ancre ces chemins sur le disque,
> permet la recherche de secours par nom + MD5, et le recalcul de l'empreinte
> avant suppression.

### 🖱️ Raccourcis et astuces

| Action | Comment |
|--------|---------|
| Filtrer la liste | `Ctrl+F` puis taper (Échap pour effacer) |
| Tout cocher / décocher | Boutons `☑ Tout` / `☐ Aucun`, ou clic sur l'en-tête `☑` |
| (Dé)cocher un groupe entier | Clic sur la case de la ligne **ORIGINAL** |
| Replier / déplier un groupe | Flèche à gauche de la ligne **ORIGINAL** |
| Ouvrir un fichier dans l'Explorateur | Double-clic sur sa ligne |
| Comprendre un fichier « ignoré » | Bouton **Diagnostiquer les chemins** |

---

## 🛡️ Sécurité des suppressions

- 🔐 Le **MD5 du fichier réel** est recalculé et comparé au CSV : un fichier
  dont le contenu ne correspond pas est **ignoré**.
- 🛡️ L'**original** (le plus ancien de chaque groupe) n'est **jamais** supprimé.
- 🎯 Les **noms identiques** dans des dossiers différents sont résolus par
  **chemin exact**, et seulement à défaut par nom (toujours filtré par MD5).
- ♻️ Suppression vers la **corbeille** par défaut → réversible.
- 📄 Un **rapport détaillé** est généré dans `Rapports_Doublons/` après chaque opération.

---

## 🧪 Tester sans risque : le générateur d'archives

`generer_archives_test.py` crée un dossier d'archives factices (avec doublons)
et, en option, le CSV Archifiltre correspondant — prêts à charger dans
l'application, sans toucher à vos fichiers.

**Menu graphique** (lancé sans argument) :
```bash
python generer_archives_test.py
```
Paramètres disponibles : nombre de fichiers, taux de doublons, **profondeur de
sous-dossiers** (0 à 8), **typologie d'extensions** (bureautique, texte,
données, images, web, système + extensions libres), taille cible, seed,
dossier de sortie. Une **case à cocher** contrôle la génération du CSV.

**Ligne de commande** (dès qu'un argument est passé) :
```bash
python generer_archives_test.py --defaut
python generer_archives_test.py --fichiers 2500 --taux-doublons 45
python generer_archives_test.py --profondeur 2 --extensions bureautique,images
python generer_archives_test.py --extensions .pdf,.txt,texte
python generer_archives_test.py --defaut --sans-csv    # archives seules
```

> Le CSV généré est **identique à l'export officiel Archifiltre
> « CSV avec empreinte »** (mêmes colonnes, mêmes libellés, même format de
> cellules), d'après le code source de
> [archifiltre-docs](https://github.com/SocialGouv/archifiltre-docs).

---

## 🛠️ Technique

### Technos

- 🐍 **Python 3.8+** · 🎨 **Tkinter** (interface) · 📊 **Threading**
  (chargements et suppression sans blocage) · 🔐 **hashlib / MD5** ·
  ♻️ **send2trash** *(optionnel)*

### Structure du projet

```
Script_Suppression_Doublons/
├── application_doublon.py        ← L'application de suppression (tout le code)
├── generer_archives_test.py      ← Générateur d'archives de test (menu + CLI)
├── launcher_application.bat      ← Lanceur simple pour Windows
├── requirements.txt              ← Dépendance optionnelle (send2trash)
└── README.md                     ← Ce fichier
```

### Performances

| Action | Temps |
|--------|-------|
| Analyser 70 000 fichiers | **< 5 sec** 🚀 |
| Supprimer 1 000 fichiers | **10-30 sec** ⚡ |
| Utilisation mémoire | **~30 MB** 💾 |

---

## 📝 Problèmes ?

### « Module tkinter non trouvé »
```bash
# Windows
python -m pip install tk

# Mac
brew install python-tk

# Linux
sudo apt-get install python3-tk
```

### L'application se ferme sans message
Lancer en **manuel** (`python application_doublon.py` dans un terminal) pour voir l'erreur.

### Des fichiers sont « ignorés »
- ✅ Utiliser le bouton **Diagnostiquer les chemins** : il compare chaque chemin
  du CSV avec le disque et explique chaque échec
- ✅ Vérifier que le répertoire sélectionné est bien **celui analysé par Archifiltre**
- ✅ Vérifier que le CSV est bien l'export **« avec empreinte »** (colonne MD5 remplie)

---

## 🤝 Contribuer

- 🐛 [Signaler un bug](../../issues)
- 💬 Proposer une amélioration

---

## 📄 Licence

Projet libre d'utilisation, créé pour simplifier le nettoyage de fonds
documentaires et l'archivage.

**Vous trouvez ce projet utile ?** ⭐ N'oubliez pas de mettre une star !

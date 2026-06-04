# 🗑️ Suppression Doublons - Application de Nettoyage Fichiers

Une application simple et rapide pour **supprimer les fichiers en double** sur votre ordinateur.

> 💡 **Parfait pour** : Nettoyer votre disque dur des fichiers dupliqués détectés par [Archifiltre](https://archifiltre.fabrique.social.gouv.fr/)

---

## 🎯 C'est quoi ce projet?

Vous avez des **milliers de fichiers dupliqués** en double sur votre disque?  
Cette application vous permet de:

✅ **Charger** un fichier liste de doublons (CSV)  
✅ **Analyser** les fichiers trouvés (automatique dès que CSV + dossier sont chargés)  
✅ **Vérifier** le contenu réel des fichiers (empreinte MD5) avant toute suppression  
✅ **Supprimer** les doublons en 1 clic — **vers la corbeille** (réversible) par défaut  
✅ **Voir** les résultats en temps réel et **annuler** à tout moment  

**Avant:** Supprimer 1000 fichiers manuellement = 5-10 minutes 😴  
**Après:** Supprimer avec cette app = 10-30 secondes ⚡

---

## 📦 Installation (4 étapes)

### ✅ Étape 1 : Avoir Python sur votre ordinateur

[Télécharger Python 3.8+](https://www.python.org/downloads/) (Windows, Mac ou Linux)

Vérifier que Python est bien installé :
```bash
python --version
```

### ✅ Étape 2 : Télécharger ce projet

Cliquer sur le bouton vert **`<> Code`** → **`Download ZIP`**  
Puis extraire le dossier sur votre ordinateur.

### ✅ Étape 3 : Installer la dépendance corbeille (recommandé)

Pour que les fichiers aillent à la **corbeille** (suppression réversible) :
```bash
python -m pip install -r requirements.txt
```
> 💡 Optionnel : sans `send2trash`, l'application fonctionne quand même mais la suppression devient **définitive** (avec un avertissement clair).

### ✅ Étape 4 : Lancer l'application

#### Méthode Simple (Windows)
Double-cliquer sur le fichier `launcher_application.bat`  
*(il installe `send2trash` automatiquement si besoin)*

#### Méthode Manuelle
Ouvrir PowerShell/Terminal et taper :
```bash
cd C:\Users\VotreUtilisateur\...\Script_Suppression_Doublons-main
python application_doublon.py
```

---

## 🚀 Comment utiliser?

### Étape par Étape

```
1️⃣ L'application démarre
   ↓
2️⃣ Cliquer sur "Parcourir CSV"
   → Sélectionner le fichier .csv créé par Archifiltre
   ↓
3️⃣ Cliquer sur "Parcourir dossier"
   → Choisir le dossier principal où se trouvent vos fichiers
   → L'analyse se lance AUTOMATIQUEMENT (pas de bouton "Analyser")
   ↓
4️⃣ Vérifier les résultats
   → Nombre de doublons trouvés, espace à libérer
   ↓
5️⃣ (Options) Choisir : vérification MD5 ✅ et corbeille ♻️
   ↓
6️⃣ Cliquer sur "Supprimer les doublons"
   → Confirmation, puis suppression vers la corbeille (réversible)
   → Bouton "Annuler" disponible pendant l'opération
   ↓
7️⃣ ✅ Terminé! Voir le rapport généré
```

---

## 🛠️ Technique (Pour les curieux)

### Technos Utilisées

- 🐍 **Python 3.8+** - Langage de programmation
- 🎨 **Tkinter** - Interface graphique simple
- 📊 **Threading** - Traitement sans bloquer l'interface
- 🔐 **Hashlib (MD5)** - Vérifie le contenu réel des fichiers avant suppression
- ♻️ **send2trash** *(optionnel)* - Envoi à la corbeille (suppression réversible)

### Sécurité des suppressions

- 🔐 Le **MD5 du fichier réel** est recalculé et comparé au CSV avant suppression : un fichier dont le contenu ne correspond pas est **ignoré**.
- 🛡️ L'**original** (le plus ancien de chaque groupe) n'est **jamais** supprimé.
- ♻️ Suppression vers la **corbeille** par défaut → **réversible**.
- 📄 Un **rapport** détaillé est généré dans `Rapports_Doublons/` après chaque opération.

### Structure du Projet

```
Script_Suppression_Doublons-main/
├── application_doublon.py        ← Le cœur de l'appli (tout le code)
├── launcher_application.bat       ← Lanceur simple pour Windows
├── requirements.txt               ← Dépendance optionnelle (send2trash)
└── README.md                      ← Ce fichier
```

### Performances

| Action | Temps |
|--------|-------|
| Supprimer 1000 fichiers | **10-30 sec** ⚡ |
| Analyser 70 000 fichiers | **< 5 sec** 🚀 |
| Utilisation mémoire | **30 MB** 💾 |

---

## 💡 Conseils d'Utilisation

⚠️ **IMPORTANT** :
- ✅ Faire une **sauvegarde** avant de supprimer (bonne pratique, même avec la corbeille)
- ✅ **Vérifier** les fichiers à supprimer dans l'aperçu
- ♻️ Par défaut, les fichiers vont à la **corbeille** → récupérables
- ⚠️ Si `send2trash` n'est pas installé (ou option décochée), la suppression est **définitive**

---

## 📝 Problèmes?

Si vous avez une erreur:

### "Module tkinter non trouvé"
```bash
# Windows
python -m pip install tk

# Mac
brew install python-tk@3.9

# Linux
sudo apt-get install python3-tk
```

### L'application se ferme sans message
Essayer la **Méthode Manuelle** pour voir l'erreur en détail.

### Les fichiers ne sont pas trouvés
- ✅ Vérifier que le dossier CSV est correct
- ✅ Vérifier que le répertoire source existe
- ✅ Vérifier l'encodage du fichier CSV (UTF-8)

---

## 🤝 Contribuer

Vous avez une idée d'amélioration?  
N'hésitez pas à:
- 🐛 [Signaler un bug](../../issues)
- 💬 Proposer une amélioration

---

## 📄 Licence

Ce projet est libre d'utilisation. Voir la section [Licence](#) pour plus d'infos.

---

## ✨ Fait avec ❤️

Créé pour simplifier le nettoyage de disques et l'archivage efficace.

**Vous trouvez ce projet utile?** ⭐ N'oubliez pas de mettre une star!


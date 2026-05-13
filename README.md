# 🗑️ Suppression Doublons - Application de Nettoyage Fichiers

Une application simple et rapide pour **supprimer les fichiers en double** sur votre ordinateur.

> 💡 **Parfait pour** : Nettoyer votre disque dur des fichiers dupliqués détectés par [Archifiltre](https://archifiltre.fabrique.social.gouv.fr/)

---

## 🎯 C'est quoi ce projet?

Vous avez des **milliers de fichiers dupliqués** en double sur votre disque?  
Cette application vous permet de:

✅ **Charger** un fichier liste de doublons (CSV)  
✅ **Analyser** les fichiers trouvés  
✅ **Supprimer** automatiquement les doublons en 1 clic  
✅ **Voir** les résultats en temps réel  

**Avant:** Supprimer 1000 fichiers manuellement = 5-10 minutes 😴  
**Après:** Supprimer avec cette app = 10-30 secondes ⚡

---

## 📦 Installation (3 étapes)

### ✅ Étape 1 : Avoir Python sur votre ordinateur

[Télécharger Python 3.8+](https://www.python.org/downloads/) (Windows, Mac ou Linux)

Vérifier que Python est bien installé :
```bash
python --version
```

### ✅ Étape 2 : Télécharger ce projet

Cliquer sur le bouton vert **`<> Code`** → **`Download ZIP`**  
Puis extraire le dossier sur votre ordinateur.

### ✅ Étape 3 : Lancer l'application

#### Méthode Simple (Windows)
Double-cliquer sur le fichier `launcher_application.bat`

#### Méthode Manuelle
Ouvrir PowerShell/Terminal et taper :
```bash
cd C:\Users\VotreUtilisateur\...\Script_Suppresion_V4
python application_doublon.py
```

---

## 🚀 Comment utiliser?

### Étape par Étape

```
1️⃣ L'application démarre
   ↓
2️⃣ Cliquer sur "Charger CSV"
   → Sélectionner le fichier .csv créé par Archifiltre
   ↓
3️⃣ Cliquer sur "Sélectionner Répertoire"
   → Choisir le dossier principal où se trouvent vos fichiers
   ↓
4️⃣ Cliquer sur "Analyser"
   → L'app scanne le dossier et cherche les doublons
   ↓
5️⃣ Vérifier les résultats
   → Nombre de doublons trouvés, espace économisé
   ↓
6️⃣ Cliquer sur "Supprimer Doublons"
   → Les fichiers en double sont supprimés définitivement
   ↓
7️⃣ ✅ Terminé! Voir le rapport généré
```

---

## 🛠️ Technique (Pour les curieux)

### Technos Utilisées

- 🐍 **Python 3.8+** - Langage de programmation
- 🎨 **Tkinter** - Interface graphique simple
- 📊 **Threading** - Traitement sans bloquer l'interface
- 🔐 **Hashlib** - Vérification des fichiers en double

### Structure du Projet

```
Script_Suppresion_V4/
├── application_doublon.py        ← Le cœur de l'appli (tout le code)
├── launcher_application.bat       ← Lanceur simple pour Windows
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
- ✅ Faire une **sauvegarde** avant de supprimer
- ✅ **Vérifier** les fichiers à supprimer dans l'aperçu
- ⚠️ **Impossible d'annuler** une suppression (les fichiers ne vont pas à la corbeille)

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


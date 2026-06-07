# 🎵 SoundCloud Downloader

Télécharge automatiquement toutes les musiques d'un profil SoundCloud (uploads + reposts) en haute qualité, avec une interface web moderne.

---

## ✨ Fonctionnalités

- Télécharge **tous les uploads et reposts** d'un profil SoundCloud
- Formats supportés : **WAV**, **FLAC**, **MP3 320kbps**, **MP3 128kbps**
- Compatible **SoundCloud Go+** (qualité AAC 256kbps)
- Reprend là où il s'est arrêté (ne re-télécharge pas les fichiers déjà présents)
- Interface web moderne avec progression en temps réel
- Gère automatiquement les rate-limits de SoundCloud

---

## 🚀 Démarrage rapide

### Option 1 — Avec le lanceur (recommandé)

Double-clique sur **`SoundCloudDownloader.exe`**

Le programme va automatiquement :
1. Vérifier que Python est installé (l'installe si besoin)
2. Installer les packages nécessaires
3. Vérifier que ffmpeg est installé (l'installe si besoin)
4. Ouvrir l'interface dans ton navigateur

### Option 2 — Manuellement

```bash
python launcher.py
```

---

## 📋 Prérequis

| Logiciel | Version minimum | Lien |
|----------|----------------|------|
| Python   | 3.8+           | [python.org](https://www.python.org/downloads/) |
| ffmpeg   | Toute version  | [ffmpeg.org](https://ffmpeg.org/download.html) |

> **Note :** Le lanceur installe Python et ffmpeg automatiquement si nécessaire.

---

## 🔧 Installation manuelle des packages

Si tu préfères installer toi-même :

```bash
pip install flask curl_cffi
```

Puis lancer :

```bash
python app.py
```

---

## 🔑 Trouver ton OAuth Token et Client ID

Ces informations sont nécessaires pour accéder aux musiques (surtout en haute qualité avec Go+).  
Des boutons **`?`** dans l'interface expliquent comment les trouver étape par étape.

### Résumé rapide

**OAuth Token :**
1. Ouvre SoundCloud dans ton navigateur et connecte-toi
2. Appuie sur `F12` → onglet **Network**
3. Lance une musique
4. Filtre les requêtes avec `stream`
5. Clique sur une requête → **Headers** → cherche `authorization`
6. Copie la valeur après `OAuth ` (ex: `2-123456-...`)

**Client ID :**
1. Même procédure, filtre avec `client_id`
2. Dans l'URL d'une requête, copie les caractères après `client_id=` jusqu'au prochain `&`

---

## 🎵 Formats disponibles

| Format | Description | Qualité |
|--------|-------------|---------|
| **WAV** | Lossless non compressé | ⭐⭐⭐⭐⭐ (nécessite Go+) |
| **FLAC** | Lossless compressé | ⭐⭐⭐⭐⭐ (nécessite Go+) |
| **MP3 320kbps** | Haute qualité compressée | ⭐⭐⭐⭐ (nécessite Go+) |
| **MP3 128kbps** | Qualité standard SoundCloud | ⭐⭐⭐ (gratuit) |

> Sans compte **SoundCloud Go+**, la qualité maximale est **128kbps**.  
> Avec Go+, tu accèdes aux flux AAC 256kbps qui sont convertis dans le format choisi.

---

## 🗂️ Structure des fichiers

```
SoundCloudDownloader.exe   ← Lanceur principal (double-clic pour démarrer)
app.py                     ← Serveur web (interface)
downloader.py              ← Moteur de téléchargement
launcher.py                ← Code source du lanceur
README.md                  ← Ce fichier
downloads/                 ← Dossier de sortie par défaut
  └── .scdl_archive        ← Liste des fichiers déjà téléchargés (ne pas supprimer)
```

---

## ⚙️ Configuration

Tous les paramètres se configurent dans l'interface web :

| Champ | Description |
|-------|-------------|
| **URL du profil** | Lien SoundCloud (ex: `https://soundcloud.com/leap1`) |
| **Dossier de destination** | Où sauvegarder les fichiers (ex: `D:\Musique`) |
| **OAuth Token** | Clé de connexion à ton compte SoundCloud |
| **Client ID** | Identifiant API SoundCloud |
| **Format** | WAV / FLAC / MP3 320kbps / MP3 128kbps |

---

## ❓ Problèmes fréquents

### Le téléchargement s'arrête avec des erreurs 403

SoundCloud limite le nombre de requêtes par Client ID. Solutions :
- Le script attend automatiquement quelques secondes et réessaie
- Si ça persiste, récupère un nouveau **Client ID** depuis F12 > Network

### La barre de progression ne s'actualise pas

- Rafraîchis la page du navigateur (`F5`)
- Vérifie que le serveur tourne encore dans la console

### ffmpeg introuvable / pas de conversion audio

- Redémarre le lanceur après l'installation de ffmpeg
- Ou ajoute ffmpeg manuellement au PATH Windows

### "Dossier de destination introuvable"

- Assure-toi que le disque/dossier existe (ex: `D:\` doit exister)
- Le script crée automatiquement le sous-dossier si nécessaire

---

## 🔨 Recompiler l'exe (développeurs)

```bash
build_exe.bat
```

Ou manuellement :

```bash
pip install pyinstaller
pyinstaller --onefile --console --name "SoundCloudDownloader" launcher.py
```

L'exe généré se trouve dans le dossier `dist/`.  
Copie-le dans le même dossier que `app.py` et `downloader.py`.

---

## 📄 Licence

Usage personnel uniquement. Respecte les conditions d'utilisation de SoundCloud.

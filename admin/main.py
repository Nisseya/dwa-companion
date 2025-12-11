# r2_uploader.py (Version autonome avec sélection de dossier)

import json
import os
import sys
import base64
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import re
import time
import io # Pour gérer les fichiers binaires et StringIO

# NOUVEAU: Imports pour l'interface graphique et la saisie
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:
    tk = filedialog = None 

# --- 1. CONFIGURATION ET FONCTIONS UTILES ---

# Charge les variables d'environnement
load_dotenv() 

# Récupération des variables d'environnement
# ... (le code de lecture des variables et de vérification reste inchangé) ...
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, ACCOUNT_ID, BUCKET_NAME]):
    print(json.dumps({"status": "error", "message": "Erreur: Les variables R2 (clés et identifiants) ne sont pas correctement définies dans r2.env."}))
    sys.exit(1)

ENDPOINT_URL = f'https://{ACCOUNT_ID}.r2.cloudflarestorage.com'

# Définition de l'interface des données (simplifiée en Python)
class FileToUpload:
    def __init__(self, relative_path, content, is_binary):
        self.relativePath = relative_path
        self.content = content # Contenu en bytes (binaire) ou string (texte)
        self.isBinary = is_binary

# --- 2. LOGIQUE DE LECTURE RÉCURSIVE DU DOSSIER LOCAL ---

def gather_files_for_upload(folder_path: str, template_name: str) -> list[FileToUpload]:
    """Lit un dossier local de manière récursive et prépare les données."""
    files_to_upload = []
    
    # Extensions considérées comme binaires
    BINARY_EXTENSIONS = re.compile(r'\.(png|jpg|jpeg|gif|ico|zip|gz|tar|woff|woff2|ttf)$', re.I)

    def traverse_dir(current_path: str, relative_prefix: str = ''):
        items = os.listdir(current_path)

        for item in items:
            item_path = os.path.join(current_path, item)
            
            # Exclusion des dossiers de développement et des fichiers cachés
            if item in ('node_modules', '.git') or item.startswith('.'):
                continue

            if os.path.isdir(item_path):
                traverse_dir(item_path, os.path.join(relative_prefix, item))
            else:
                # C'est un fichier
                relative_path = os.path.join(relative_prefix, item).replace(os.path.sep, '/')
                is_binary = BINARY_EXTENSIONS.search(item) is not None
                
                # Lecture du contenu
                mode = 'rb' if is_binary else 'r'
                encoding = None if is_binary else 'utf-8'

                with open(item_path, mode, encoding=encoding) as f:
                    content = f.read()
                
                files_to_upload.append(FileToUpload(relative_path, content, is_binary))

    traverse_dir(folder_path)
    return files_to_upload

# --- 3. FONCTION PRINCIPALE D'UPLOAD ---

def upload_template(template_name: str, source_folder: str):
    
    s3_client = boto3.client(
        service_name='s3',
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name='auto' 
    )

    # 3.1 Lecture des fichiers locaux
    print(f"Lecture récursive des fichiers depuis : {source_folder}")
    files_data = gather_files_for_upload(source_folder, template_name)

    if not files_data:
        print(json.dumps({"status": "error", "message": "Aucun fichier à uploader trouvé dans le dossier sélectionné."}))
        sys.exit(1)

    print(f"Démarrage de l'upload de {len(files_data)} fichiers pour le template: {template_name}")

    # 3.2 Upload des Fichiers
    new_files_paths = []
    for file_data in files_data:
        # Clé R2: [templateName]/[relativePath]
        object_key = f"{template_name}/{file_data.relativePath}" 
        
        # Le contenu est déjà en bytes pour les binaires, ou string pour le texte
        body = file_data.content.encode('utf-8') if not file_data.isBinary else file_data.content

        try:
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=object_key,
                Body=body
            )
            print(f"  -> Upload réussi: {object_key}")
            new_files_paths.append(file_data.relativePath)
            
        except ClientError as e:
            error_msg = e.response['Error']['Message']
            print(json.dumps({"status": "error", "message": f"Erreur R2 lors de l'upload de {object_key}: {error_msg}"}))
            sys.exit(1)

    # 3.3 Mise à Jour du Manifeste (templates.json)
    MANIFEST_KEY = 'templates.json'
    
    # ... (Le code de téléchargement, mise à jour et upload du manifeste reste inchangé) ...
    # Le code de cette section est identique à celui du script précédent (parties 4 et 5).

    # Télécharger l'ancien manifeste
    try:
        manifest_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=MANIFEST_KEY)
        manifest_content = manifest_obj['Body'].read().decode('utf-8')
        manifest = json.loads(manifest_content)
    except ClientError:
        manifest = {"templates": []}

    # Création de la nouvelle entrée
    new_template_entry = {
        "name": template_name,
        "label": template_name.replace('-', ' ').title(),
        "description": f"Template uploadé manuellement à {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "files": new_files_paths,
        "install_command": "pnpm install" if 'package.json' in new_files_paths else None 
    }

    # Mise à jour et upload du manifeste
    templates = manifest.get('templates', [])
    templates = [t for t in templates if t['name'] != template_name] 
    templates.append(new_template_entry)
    manifest['templates'] = templates

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=MANIFEST_KEY,
        Body=json.dumps(manifest, indent=2),
        ContentType='application/json'
    )
    
    print(json.dumps({"status": "success", "message": f"Template {template_name} uploadé et manifeste mis à jour."}))

# --- 4. POINT D'ENTRÉE DU SCRIPT ---

if __name__ == "__main__":
    
    # DÉTECTION ET SÉLECTION DU DOSSIER SOURCE
    
    source_folder = None
    
    # Cas d'utilisation N°1: Appel par VS Code avec un chemin d'entrée (non implémenté ici)
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        source_folder = sys.argv[1]
        
    # Cas d'utilisation N°2: Utilisation manuelle avec GUI
    elif tk and filedialog:
        root = tk.Tk()
        root.withdraw() 
        
        print("Veuillez sélectionner le dossier du template à uploader...")
        
        # Ouvre la boîte de dialogue pour CHOISIR UN DOSSIER
        source_folder = filedialog.askdirectory(
            title="Sélectionnez le dossier RACINE du template"
        )
        
        if not source_folder:
            print(json.dumps({"status": "error", "message": "Sélection de dossier annulée par l'utilisateur."}))
            sys.exit(0) 
            
    else:
        print(json.dumps({"status": "error", "message": "Usage: python r2_uploader.py <path_to_folder> ou utilisez Tkinter pour la sélection manuelle."}))
        sys.exit(1)

    # SAISIE DU NOM DU TEMPLATE
    if source_folder:
        default_name = os.path.basename(source_folder).lower().replace(' ', '-')
        
        # NOTE: La saisie doit se faire via la console/terminal car tkinter.simpledialog 
        # peut être difficile à utiliser en contexte console.
        template_name = input(f"Entrez le nom du template R2 (ex: mon-nouveau-projet, défaut: {default_name}) : ")
        
        if not template_name:
            template_name = default_name

        if not re.match(r'^[a-z0-9-]+$', template_name):
            print(json.dumps({"status": "error", "message": "Nom de template invalide. Utilisez uniquement minuscules, chiffres et tirets."}))
            sys.exit(1)

        # LANCEMENT DE LA LOGIQUE
        upload_template(template_name, source_folder)
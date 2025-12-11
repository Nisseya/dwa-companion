# r2_uploader.py (Version Finale avec Multipart Upload et Barre de Progression)

import json
import os
import sys
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import re
import time
import argparse 
import io 
from tqdm import tqdm # NOUVEL IMPORT

# Imports pour l'interface graphique (Tkinter)
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:
    tk = filedialog = None 

# --- NOUVEAU : CLASSE DE GESTION DE LA BARRE DE PROGRESSION ---

# Classe Wrapper pour lier l'upload de boto3 à tqdm
class TqdmFile(io.FileIO):
    def __init__(self, fd, *args, **kwargs):
        super().__init__(fd, *args, **kwargs)
        self.tqdm_instance = None
        self._total_size = os.fstat(fd).st_size

    def set_tqdm(self, tqdm_instance):
        self.tqdm_instance = tqdm_instance
        self.tqdm_instance.total = self._total_size

    # Cette méthode est appelée par boto3 à chaque écriture (chunk de données)
    def read(self, size):
        chunk = super().read(size)
        if self.tqdm_instance:
            self.tqdm_instance.update(len(chunk))
        return chunk


# --- 1. CONFIGURATION ET VÉRIFICATION ---

load_dotenv('r2.env') 

AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, ACCOUNT_ID, BUCKET_NAME]):
    print(json.dumps({"status": "error", "message": "Erreur: Les variables R2 (clés et identifiants) ne sont pas correctement définies dans r2.env."}))
    sys.exit(1)

ENDPOINT_URL = f'https://{ACCOUNT_ID}.r2.cloudflarestorage.com'

# DÉFINITION CLÉ : Stocke le chemin local au lieu du contenu en mémoire
class FileToUpload:
    def __init__(self, relative_path, local_path):
        self.relativePath = relative_path
        self.localPath = local_path # Chemin complet sur le système de fichiers

# --- 2. LOGIQUE DE LECTURE RÉCURSIVE DU DOSSIER LOCAL ---

def gather_files_for_upload(folder_path: str) -> list[FileToUpload]:
    """Lit un dossier local de manière récursive et prépare les métadonnées pour l'upload."""
    files_to_upload = []

    def traverse_dir(current_path: str, relative_prefix: str = ''):
        items = os.listdir(current_path)

        for item in items:
            item_path = os.path.join(current_path, item)
            
            if item in ('node_modules', '.git', '__pycache__') or item.startswith('.'):
                continue

            if os.path.isdir(item_path):
                traverse_dir(item_path, os.path.join(relative_prefix, item))
            else:
                relative_path = os.path.join(relative_prefix, item).replace(os.path.sep, '/') 
                files_to_upload.append(FileToUpload(relative_path, item_path))

    traverse_dir(folder_path)
    return files_to_upload

# --- 3. FONCTION PRINCIPALE D'UPLOAD (AVEC MULTIPART AUTOMATIQUE ET PROGRESS BAR) ---

def upload_template(template_name: str, source_folder: str):
    
    s3_client = boto3.client(
        service_name='s3',
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name='auto' 
    )

    print(f"Lecture récursive des fichiers depuis : {source_folder}")
    files_data = gather_files_for_upload(source_folder)

    if not files_data:
        print(json.dumps({"status": "error", "message": "Aucun fichier à uploader trouvé dans le dossier sélectionné."}))
        sys.exit(1)

    print(f"Démarrage de l'upload de {len(files_data)} fichiers pour le template: {template_name}")

    new_files_paths = []
    
    TEXT_MIME_TYPES = {
        '.json': 'application/json', '.html': 'text/html', '.css': 'text/css',
        '.js': 'application/javascript', '.txt': 'text/plain', '.csv': 'text/csv',
        '.md': 'text/markdown', '.py': 'text/x-python', '.ipynb': 'application/x-ipynb+json', 
        '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.gif': 'image/gif', '.ico': 'image/x-icon'
    }

    for file_data in files_data:
        object_key = f"{template_name}/{file_data.relativePath}" 
        file_ext = os.path.splitext(file_data.localPath)[1].lower()
        content_type = TEXT_MIME_TYPES.get(file_ext, 'application/octet-stream')
        
        try:
            # OUVERTURE DU FICHIER EN MODE BINAIRE ET WRAPPER POUR LA PROGRESSION
            
            # Utiliser os.open et le descripteur de fichier pour TqdmFile
            file_descriptor = os.open(file_data.localPath, os.O_RDONLY | os.O_BINARY)
            
            with TqdmFile(file_descriptor) as data_wrapper:
                
                # Initialiser la barre de progression pour le fichier actuel
                with tqdm(
                    desc=f" {file_data.relativePath}",
                    unit='B', unit_scale=True, unit_divisor=1024, miniters=1,
                    bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
                ) as t:
                    
                    data_wrapper.set_tqdm(t) # Lier la barre de progression au wrapper
                    
                    s3_client.upload_fileobj(
                        Fileobj=data_wrapper, # Utiliser le wrapper TqdmFile comme source
                        Bucket=BUCKET_NAME,
                        Key=object_key,
                        ExtraArgs={'ContentType': content_type}
                    )
            
            # Message de succès est maintenant inclus dans la progression de tqdm
            new_files_paths.append(file_data.relativePath)
            
        except ClientError as e:
            error_msg = e.response['Error']['Message']
            print(f"\n[ERREUR R2] Échec de l'upload de {object_key}: {error_msg}")
            sys.exit(1)
        except Exception as e:
            print(f"\n[ERREUR GÉNÉRALE] Échec de la lecture/upload de {file_data.localPath}: {e}")
            sys.exit(1)


    # 3.3 Mise à Jour du Manifeste (Reste inchangé)
    # ... (Code inchangé pour la mise à jour du manifeste) ...
    MANIFEST_KEY = 'templates.json'
    
    try:
        manifest_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=MANIFEST_KEY)
        manifest_content = manifest_obj['Body'].read().decode('utf-8')
        manifest = json.loads(manifest_content)
    except ClientError:
        manifest = {"templates": []}

    new_template_entry = {
        "name": template_name,
        "label": template_name.replace('-', ' ').title(),
        "description": f"Template uploadé via l'extension VS Code",
        "files": new_files_paths,
        "install_command": "pnpm install" if 'package.json' in new_files_paths else None 
    }

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

# --- 4. POINT D'ENTRÉE DU SCRIPT (inchangé) ---

def select_folder_gui():
    """Ouvre une boîte de dialogue pour sélectionner un dossier."""
    if tk and filedialog:
        root = tk.Tk()
        root.withdraw() 
        print("Veuillez sélectionner le dossier du template à uploader...")
        return filedialog.askdirectory(title="Sélectionnez le dossier RACINE du template")
    return None

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="Uploader un template local sur Cloudflare R2.")
    parser.add_argument('-u', '--upload-folder', type=str, help="Chemin du dossier à uploader (utilisé par VS Code).")
    args = parser.parse_args()

    source_folder = None
    
    if args.upload_folder and os.path.isdir(args.upload_folder):
        source_folder = args.upload_folder
    elif args.upload_folder is None:
        source_folder = select_folder_gui()
    
    if not source_folder:
        print(json.dumps({"status": "error", "message": "Sélection de dossier annulée ou dossier source invalide."}))
        sys.exit(1)

    if source_folder:
        default_name = os.path.basename(source_folder).lower().replace(' ', '-')
        
        template_name = input(f"Entrez le nom du template R2 (ex: mon-nouveau-projet, défaut: {default_name}) : ")
        
        if not template_name:
            template_name = default_name

        if not re.match(r'^[a-z0-9-]+$', template_name):
            print(json.dumps({"status": "error", "message": "Nom de template invalide. Utilisez uniquement minuscules, chiffres et tirets."}))
            sys.exit(1)

        upload_template(template_name, source_folder)
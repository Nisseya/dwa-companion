import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as cp from 'child_process';

// --- CONSTANTES ---
// La variable process.env.R2_PUBLIC_URL est injectée par le build (esbuild/dotenv)
const R2_PUBLIC_URL = "https://pub-8ce83ca8885d4c62832aa87251a2d7ef.r2.dev/";
const MANIFEST_URL = `${R2_PUBLIC_URL}templates.json`;

// Chemin vers le script Python (à la racine de l'extension)
const PYTHON_SCRIPT = path.join(vscode.extensions.getExtension('your-publisher.dwa-companion')?.extensionPath || path.join(process.cwd(), '..'), 'r2_uploader.py');


// --- INTERFACE POUR LE TYPAGE DU QUICK PICK ---
interface TemplateQuickPickItem extends vscode.QuickPickItem {
    templateData: {
        name: string;
        label: string;
        description: string;
        files: string[];
        install_command: string | null;
    };
}


export function activate(context: vscode.ExtensionContext) {

    // --- COMMANDE 1: Initialiser un Template (Lecture R2) ---
    let disposableInit = vscode.commands.registerCommand('dwa-companion.initTemplate', async () => {
        
        vscode.window.showInformationMessage('Connexion à R2 pour récupérer la liste des templates...');

        let manifestData: any;
        try {
            const response = await fetch(MANIFEST_URL);
            if (!response.ok) {
                throw new Error(`Erreur HTTP ${response.status} lors du téléchargement du manifeste.`);
            }
            manifestData = await response.json();
        } catch (error) {
            vscode.window.showErrorMessage(`Échec de la récupération du manifeste R2 : ${error instanceof Error ? error.message : String(error)}`);
            return;
        }

        const templates = manifestData.templates || [];
        
        if (templates.length === 0) {
            vscode.window.showWarningMessage("Le manifeste est vide ou invalide.");
            return;
        }
        
        // Créer la liste d'options TYPÉE
        const templateOptions: TemplateQuickPickItem[] = templates.map((t: any) => ({
            label: t.label || t.name.toUpperCase(),
            description: t.description || 'Template R2',
            templateData: t 
        }));
        
        // Sélection du template (Utilise l'interface TemplateQuickPickItem pour le typage)
        const selectedOption = await vscode.window.showQuickPick<TemplateQuickPickItem>(templateOptions, {
            placeHolder: 'Choisissez le template DWA à initialiser...'
        });

        if (!selectedOption){ 
            return;
        }

        // SÉLECTION DU DOSSIER DE DESTINATION
        const options: vscode.OpenDialogOptions = {
            canSelectFolders: true, canSelectFiles: false, canSelectMany: false, openLabel: 'Créer le Projet Ici'
        };

        const folderUris = await vscode.window.showOpenDialog(options);
        if (!folderUris || folderUris.length === 0) { 
            return;
        }
        
        const destinationPath = folderUris[0].fsPath;

        try {
            // TÉLÉCHARGEMENT ET COPIE DES FICHIERS
            const templateName = selectedOption.templateData.name;
            vscode.window.showInformationMessage(`Téléchargement de ${selectedOption.templateData.files.length} fichiers pour ${templateName}...`);

            for (const relativePath of selectedOption.templateData.files) {
                
                // Normaliser le chemin pour R2/URL (même si Python devrait l'avoir corrigé, c'est une sécurité)
                const normalizedPath = relativePath.replace(/\\/g, '/'); 
                
                // Construction de l'URL
                const r2Url = `${R2_PUBLIC_URL}${templateName}/${normalizedPath}`; 
                
                const response = await fetch(r2Url);
                if (!response.ok) {
                    throw new Error(`Échec du téléchargement de ${relativePath}. URL: ${r2Url}`);
                }
                
                const fileContent = await response.text();
                
                // Écriture locale
                const filePath = path.join(destinationPath, normalizedPath);
                
                const dir = path.dirname(filePath);
                if (!fs.existsSync(dir)) {
                    fs.mkdirSync(dir, { recursive: true });
                }
                
                fs.writeFileSync(filePath, fileContent);
            }

            vscode.window.showInformationMessage(`Template DWA : ${selectedOption.label} initialisé avec succès !`);
            
            await vscode.commands.executeCommand('vscode.openFolder', folderUris[0]);

            const installCommand = selectedOption.templateData.install_command;
            if (installCommand) {
                const terminal = vscode.window.createTerminal(`Installation Dépendances (${templateName})`);
                terminal.show();
                terminal.sendText(installCommand); 
            }

        } catch (error) {
            vscode.window.showErrorMessage(`Échec de l'initialisation R2 : ${error instanceof Error ? error.message : String(error)}`);
        }
    });
    
    // --- COMMANDE 2: Uploader un Template (Appel Python) ---
    let disposableUpload = vscode.commands.registerCommand('dwa-companion.uploadTemplate', async () => {
        
        // 1. SÉLECTION DU DOSSIER SOURCE LOCAL
        const options: vscode.OpenDialogOptions = {
            canSelectFolders: true,
            canSelectFiles: false,
            canSelectMany: false,
            openLabel: 'Sélectionner le Dossier à Uploader comme Template'
        };

        const folderUris = await vscode.window.showOpenDialog(options);
        if (!folderUris || folderUris.length === 0){ 
            return;
        }
        
        const sourcePath = folderUris[0].fsPath;
        
        // 2. EXÉCUTION DU SCRIPT PYTHON POUR L'UPLOAD
        vscode.window.showInformationMessage('Lancement du script Python pour l\'upload R2...');

        try {
            // L'extension appelle le script Python en lui passant le chemin du dossier source.
            const pythonCommand = `python "${PYTHON_SCRIPT}" -u "${sourcePath}"`;
            
            const terminal = vscode.window.createTerminal(`Upload R2`);
            terminal.show();
            
            // Exécute la commande dans le terminal et laisse le script Python gérer l'invite de saisie (nom du template)
            terminal.sendText(pythonCommand); 
            vscode.window.showInformationMessage(`Script d'upload lancé. Vérifiez le terminal pour les prompts (nom du template).`);

        } catch (error) {
            vscode.window.showErrorMessage(`Échec du lancement du script Python : ${error instanceof Error ? error.message : String(error)}`);
        }
    });

    context.subscriptions.push(disposableInit, disposableUpload);
}
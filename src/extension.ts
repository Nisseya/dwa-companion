import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as cp from 'child_process';
import fetch, { Response } from 'node-fetch'; 

const R2_PUBLIC_URL = "https://pub-8ce83ca8885d4c62832aa87251a2d7ef.r2.dev/";
const MANIFEST_URL = `${R2_PUBLIC_URL}templates.json`;

const extension = vscode.extensions.getExtension('your-publisher.dwa-companion');
const PYTHON_SCRIPT = path.join(extension?.extensionPath || path.join(process.cwd(), '..'), 'r2_uploader.py');


interface TemplateQuickPickItem extends vscode.QuickPickItem {
    templateData: {
        name: string;
        label: string;
        description: string;
        files: string[];
        install_command: string | null;
    };
}


/**
 * Fonction utilitaire pour télécharger un fichier en streaming
 * @param r2Url URL complète du fichier
 * @param filePath Chemin local où le fichier doit être enregistré
 */

async function downloadFileStream(r2Url: string, filePath: string): Promise<void> {
    const response: Response = await fetch(r2Url);

    if (!response.ok || !response.body) {
        throw new Error(`Échec du téléchargement. HTTP ${response.status}.`);
    }

    // 1. Créer le répertoire si nécessaire
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }

    // 2. Créer un WritableStream Node.js
    const fileStream = fs.createWriteStream(filePath);

    // 3. Piper le ReadableStream HTTP directement dans le WritableStream du fichier
    return new Promise((resolve, reject) => {
        // Le corps de la réponse fetch est un ReadableStream Node.js (ou peut être converti)
        response.body!.pipe(fileStream);

        response.body!.on('error', (err) => {
            fileStream.close();
            reject(new Error(`Erreur de lecture du flux R2 : ${err.message}`));
        });
        
        fileStream.on('finish', () => {
            resolve();
        });
        
        fileStream.on('error', (err) => {
            reject(new Error(`Erreur d'écriture du fichier : ${err.message}`));
        });
    });
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
        
        const templateOptions: TemplateQuickPickItem[] = templates.map((t: any) => ({
            label: t.label || t.name.toUpperCase(),
            description: t.description || 'Template R2',
            templateData: t 
        }));
        
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
            vscode.window.showInformationMessage(`Démarrage du téléchargement de ${selectedOption.templateData.files.length} fichiers pour ${templateName}...`);

            // Utilisation de vscode.window.withProgress pour afficher la barre de progression globale
            await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: `Téléchargement du template ${templateName}`,
                cancellable: false
            }, async (progress, token) => {
                
                let completedFiles = 0;
                const totalFiles = selectedOption.templateData.files.length;

                for (const relativePath of selectedOption.templateData.files) {
                    
                    const normalizedPath = relativePath.replace(/\\/g, '/'); 
                    const r2Url = `${R2_PUBLIC_URL}${templateName}/${normalizedPath}`; 
                    const filePath = path.join(destinationPath, normalizedPath);
                    
                    const message = `Fichier ${++completedFiles}/${totalFiles}: ${normalizedPath}`;
                    progress.report({ message: message, increment: (1 / totalFiles) * 100 });

                    try {
                        // Utilisation de la nouvelle fonction de STREAMING
                        await downloadFileStream(r2Url, filePath);
                    } catch (e) {
                        throw new Error(`Échec du téléchargement de ${relativePath}: ${e instanceof Error ? e.message : String(e)}`);
                    }
                }
            });


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
            // Le script Python gère le Multipart Upload et la progression dans son propre terminal.
            const pythonCommand = `python "${PYTHON_SCRIPT}" -u "${sourcePath}"`;
            
            const terminal = vscode.window.createTerminal(`Upload R2`);
            terminal.show();
            
            terminal.sendText(pythonCommand); 
            vscode.window.showInformationMessage(`Script d'upload lancé. Vérifiez le terminal pour les prompts (nom du template) et la barre de progression.`);

        } catch (error) {
            vscode.window.showErrorMessage(`Échec du lancement du script Python : ${error instanceof Error ? error.message : String(error)}`);
        }
    });

    context.subscriptions.push(disposableInit, disposableUpload);
}
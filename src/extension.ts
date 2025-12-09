import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Copie récursive de fichiers/dossiers.
 * @param source Chemin source du template.
 * @param destination Chemin de destination du nouveau projet.
 */
function copyTemplate(source: string, destination: string): void {
    if (!fs.existsSync(destination)) {
        fs.mkdirSync(destination, { recursive: true });
    }

    const files = fs.readdirSync(source);

    files.forEach(file => {
        const sourceFile = path.join(source, file);
        const destinationFile = path.join(destination, file);
        const stat = fs.statSync(sourceFile);

        if (stat.isDirectory()) {
            copyTemplate(sourceFile, destinationFile); 
        } else {
            fs.copyFileSync(sourceFile, destinationFile);
        }
    });
}

export function activate(context: vscode.ExtensionContext) {

    // Enregistrement de la commande définie dans package.json
    let disposable = vscode.commands.registerCommand('dwa-companion.initTemplate', async () => {
        
        // 1. DÉFINITION ET SÉLECTION DU TEMPLATE DWA
        const templates = [
            { label: 'Template DWA Base', description: 'Fichiers HTML/CSS/JS de démarrage', dirName: 'dwa-base' },
            { label: 'Template DWA Avancé', description: 'Template avec dépendances et pnpm', dirName: 'dwa-advanced' } 
            // NOTE: Vous devrez créer le dossier 'dwa-advanced' et son package.json pour qu'il fonctionne
        ];
        
        const selectedOption = await vscode.window.showQuickPick(templates, {
            placeHolder: 'Choisissez le template DWA à initialiser...'
        });

        if (!selectedOption) {
            return; // Annulé
        }

        // 2. SÉLECTION DU DOSSIER DE DESTINATION
        // Permet de choisir le dossier sur le système (essentiel quand VS Code est vierge)
        const options: vscode.OpenDialogOptions = {
            canSelectFolders: true,
            canSelectFiles: false,
            canSelectMany: false,
            openLabel: 'Créer le Projet Ici'
        };

        const folderUris = await vscode.window.showOpenDialog(options);

        if (!folderUris || folderUris.length === 0) {
            return; // Annulé
        }
        
        const destinationPath = folderUris[0].fsPath;
        const templateSourcePath = path.join(context.extensionPath, 'templates', selectedOption.dirName);

        if (!fs.existsSync(templateSourcePath)) {
             vscode.window.showErrorMessage(`Erreur : Le template "${selectedOption.dirName}" est introuvable.`);
             return;
        }

        try {
            // 3. COPIE DES FICHIERS
            copyTemplate(templateSourcePath, destinationPath);
            vscode.window.showInformationMessage(`Template DWA : ${selectedOption.label} initialisé avec succès !`);
            
            // 4. OUVERTURE DU NOUVEL ESPACE DE TRAVAIL
            await vscode.commands.executeCommand('vscode.openFolder', folderUris[0]);

            // 5. TÂCHES POST-INITIALISATION (si c'est le template avancé)
            if (selectedOption.dirName === 'dwa-advanced') {
                const terminal = vscode.window.createTerminal(`Installation Dépendances DWA (pnpm)`);
                terminal.show();
                // Utilisation de pnpm comme convenu
                terminal.sendText('pnpm install'); 
            }

        } catch (error) {
            vscode.window.showErrorMessage(`Échec de l'initialisation : ${error instanceof Error ? error.message : String(error)}`);
        }
    });

    context.subscriptions.push(disposable);
}
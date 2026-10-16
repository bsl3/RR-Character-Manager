# RR Character Manager — 1.1

Manage and customize RR characters, slots, icons, voices, and patches. Import, export, and share characters using `.mkchara` and `.mkpack`, with backups and previews.

## Run from source

Requires Python 3.10 or newer. On Windows, run **Install Dependencies.bat**, then **Run Retro Rewind Character Manager.bat**. On macOS or Linux, create a virtual environment, install `requirements.txt`, then run `python main.py`.

Choose your `Character` folder, `Assets/ReplacedAssets.szs`, and `Patches` folder. Standard Mode edits Patches only. Developer Mode allows changes to the base distribution.

## Character editing

Import characters, edit names and voices, preview models, and organize slots. In Patches Mode, click a base RR skin's CSS or minimap preview to replace its icon. Overrides live in `Patches/RRIcons/`; original RR assets stay untouched. The revert arrow removes the override, revealing the original icon or none if no original exists. Conflicting loose icons are retained under `RRIcons/Conflicts`.

RR's stock SD loader scans only the top level of Patches. Use **File → Export Patches for RR SD…** and copy the exported Patches folder to your SD installation. The managed project keeps its folder organization. Console loading still requires in-game verification.

Imports skip unused red/blue team, battle `_BT`, and split-screen `_2`/`_4` vehicle archives. Original mods and existing installations are not deleted. Required menu AllKart resources remain supported.

## Sharing characters

Export individual characters as `.mkchara`. Select two or more characters, then choose **Characters → Export as Character Pack (.mkpack)** or the matching context-menu action. Enter a pack name and choose where to save. Mass Export still saves separate `.mkchara` files.

Import `.mkpack` through **Import Character → Choose character assets**, or drop it onto the manager. Review its name and contents, then confirm. The existing batch importer uses available slots without overwriting installed characters and reports successes and failures. Successful installations remain installed if another character fails.

A `.mkpack` is a ZIP containing `manifest.json` and complete standalone `.mkchara` files under `characters/`. The manifest contains `format: "mkpack"`, `version: 1`, `name`, and `characters` entries with `path` and `sha256`. All embedded packages are validated before installation. Limits: 500 characters and 1 GiB aggregate uncompressed resources; individual-package limits also apply.

## Backups

Click **Backup Patches** beside **Import Character** to save the complete Patches folder to your chosen location outside the RR installation. Edits and restores do not create automatic snapshots. Character and Assets folders are excluded. The **Backups** menu lets you change the location, browse backups, or restore Patches. Make a manual backup before restoring if you need to keep the current files.

## Updates and releases

The app checks the official [RR Character Manager releases](https://github.com/bsl3/RR-Character-Manager/releases) at startup. **Help → Check for Updates** checks manually. Stable updates open in your browser; nothing is installed automatically.

Release builds use Python 3.11 and `requirements-release.txt`. Run **Build Windows EXE.bat** on Windows or `python tools/build_release.py` on the target platform. Publish a release tag matching the internal version, currently `v1.1`. Windows builds keep the filename `RR character manager.exe`.

The application uses third-party libraries; see `LICENSE` and the generated third-party notices included with release packages.
